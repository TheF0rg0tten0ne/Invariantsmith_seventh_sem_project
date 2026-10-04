"""
Invariantsmith API server.

Local-only (binds 127.0.0.1). No web UI is served here — this is purely
the backend a native editor client talks to.

Run:
    uvicorn server.main:app --host 127.0.0.1 --port 8731
"""
import json
import threading
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import config, db, error_detector, fixer, models_registry, languages
from .diff_utils import apply_diff

app = FastAPI(title="Invariantsmith API", version="0.1.0")


@app.on_event("startup")
def startup():
    db.init_db()
    # Load the GGUF model now, off the request path. Without this the first
    # /suggest_fix call silently eats both the model-load time AND inference
    # time with no feedback -- which is what "stuck on pending" usually is.
    threading.Thread(target=fixer.warm_up, daemon=True, name="model-warmup").start()


# ---------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    session_id: str
    file_path: str
    code: str
    language: Optional[str] = None  # None/"auto" -> detect; else "python"|"c"|"java"


class SuggestFixRequest(BaseModel):
    session_id: str
    file_path: str
    code: str
    error_type: str
    error_message: str
    line: Optional[int] = None
    language: Optional[str] = None


class ApplyFixRequest(BaseModel):
    session_id: str
    file_path: str
    action_id: int
    code: str
    diff: str
    outcome: str = "accepted"  # 'accepted' | 'edited'


class ExplainRequest(BaseModel):
    session_id: str
    file_path: str
    code: str
    error_type: str
    error_message: str
    language: Optional[str] = None


class DetectLanguageRequest(BaseModel):
    code: str
    file_path: Optional[str] = None


class ConvertRequest(BaseModel):
    session_id: str
    file_path: str
    code: str
    target_language: str
    source_language: Optional[str] = None  # None/"auto" -> detect


class ConvertApplyRequest(BaseModel):
    session_id: str
    file_path: str
    action_id: int
    outcome: str = "accepted"  # 'accepted' | 'rejected'


# ---------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------

@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    """Fast static pass. Meant to run on every debounced keystroke."""
    detected = languages.resolve_language(req.language, req.code, req.file_path)
    errors = error_detector.analyze(req.code, req.file_path, detected)
    db.log_action(
        session_id=req.session_id, file_path=req.file_path, action_type="analyze",
        error_type=errors[0].error_type if errors else None,
        error_message=errors[0].message if errors else None,
    )
    return {"errors": [e.to_dict() for e in errors], "detected_language": detected}


@app.post("/suggest_fix")
def suggest_fix(req: SuggestFixRequest):
    """Invoke the model to propose a diff-based fix for a specific error."""
    if not fixer.is_ready():
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Run scripts/download_model.sh, "
                   "then place the .gguf in models/.",
        )

    result = fixer.suggest_fix(
        code=req.code,
        error_type=req.error_type,
        error_message=req.error_message,
        filename=req.file_path,
        language=req.language,
        line=req.line,  # was previously collected in the schema but never forwarded --
                         # fixer.suggest_fix() needs it to scope a chunked fix (see chunker.py)
    )

    action_id = db.log_action(
        session_id=req.session_id, file_path=req.file_path, action_type="suggest_fix",
        error_type=req.error_type, error_message=req.error_message,
        diff=result.diff, rationale=result.rationale, confidence=result.confidence,
        outcome=None,  # pending — client tells us accepted/rejected/edited later
    )

    return {
        "action_id": action_id,
        "diff": result.diff,
        # `rationale` keeps the legacy string (with inline [bracketed] notes)
        # for older clients; new clients show `summary` as the Rationale and
        # render `checks` in the Checks & Verification section instead.
        "rationale": result.rationale,
        "summary": result.summary,
        "checks": result.checks,
        "confidence": result.confidence,
        "verified": result.verified,
        "auto_apply_recommended": result.verified and result.confidence >= config.AUTO_APPLY_THRESHOLD,
    }


@app.post("/apply_fix")
def apply_fix(req: ApplyFixRequest):
    """Apply a previously-suggested diff to the code and log the outcome.

    A diff can fail to apply even when `code` is byte-for-byte what the
    client's suggestion panel snapshotted at request time: if the user (or
    an "Apply & Next" chain) already applied a DIFFERENT fix for the same
    file in the meantime, that earlier diff and this one were both computed
    against the same original buffer, but only the first one to land still
    matches reality -- this one's context lines are now stale. That's 409
    Conflict (the request is well-formed, the resource just moved on),
    not 400 Bad Request, and the client uses the structured "stale_diff"
    reason to disable retrying this exact fix and point the user at
    Regenerate instead of letting them resubmit the same doomed request.
    """
    try:
        new_code = apply_diff(req.code, req.diff)
    except Exception as e:
        db.update_outcome(req.action_id, "rejected")
        raise HTTPException(
            status_code=409,
            detail={
                "error": "stale_diff",
                "message": (
                    "This fix no longer matches the current code -- something else "
                    "changed the buffer since this fix was generated (often another "
                    "fix applied to the same file). Regenerate for a fresh fix "
                    "instead of retrying this one."
                ),
                "reason": str(e),
            },
        )

    db.update_outcome(req.action_id, req.outcome)
    return {"code": new_code}


@app.post("/reject_fix")
def reject_fix(action_id: int):
    db.update_outcome(action_id, "rejected")
    return {"status": "ok"}


@app.post("/explain")
def explain(req: ExplainRequest):
    if not fixer.is_ready():
        raise HTTPException(status_code=503, detail="Model not loaded.")
    try:
        text = fixer.explain_error(req.code, req.error_type, req.error_message, req.language)
    except TimeoutError as e:
        raise HTTPException(status_code=408, detail=str(e))
    db.log_action(
        session_id=req.session_id, file_path=req.file_path, action_type="explain",
        error_type=req.error_type, error_message=req.error_message, rationale=text,
    )
    return {"explanation": text}


@app.get("/history")
def history(file_path: Optional[str] = None, session_id: Optional[str] = None,
            limit: int = 100):
    return {"history": db.get_history(file_path=file_path, session_id=session_id, limit=limit)}


@app.get("/model/status")
def model_status():
    active = models_registry.active_model()
    state = fixer.model_state()   # non-blocking: never triggers a model load
    return {
        "ready": state["ready"],
        "state": state["state"],       # missing | idle | loading | ready | error
        "error": state["error"],
        "active_model": active.__dict__ if active else None,
        "available_models": [m.__dict__ for m in models_registry.list_models()],
        "auto_apply_threshold": config.AUTO_APPLY_THRESHOLD,
    }


@app.get("/languages")
def list_languages():
    """Supported languages for the client's language picker."""
    return {"languages": languages.list_profiles(), "default": "auto"}


@app.post("/detect_language")
def detect_language(req: DetectLanguageRequest):
    """Cheap, offline heuristic language guess -- used by the client to
    show/confirm auto-detection without running a full /analyze pass."""
    detected = languages.resolve_language(None, req.code, req.file_path)
    return {"language": detected}


@app.post("/convert")
def convert(req: ConvertRequest):
    """Convert a complete program from one supported language to another.

    Unlike /suggest_fix, this returns a full replacement program (there's
    no meaningful diff between, say, Python and Java source) -- the
    client shows it as a whole-file preview, not a diff view.
    """
    if req.target_language not in languages.LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unknown target language '{req.target_language}'.")
    if not fixer.is_ready():
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Run scripts/download_model.sh, "
                   "then place the .gguf in models/.",
        )

    result = fixer.convert_code(
        code=req.code,
        target_language=req.target_language,
        source_language=req.source_language,
        filename=req.file_path,
    )

    action_id = db.log_action(
        session_id=req.session_id, file_path=req.file_path, action_type="convert",
        error_type=None, error_message=None,
        diff=result.converted_code, rationale=result.notes,
        confidence=1.0 if result.ok else 0.0, outcome=None,
    )

    return {
        "action_id": action_id,
        "converted_code": result.converted_code,
        "notes": result.notes,
        "ok": result.ok,
        "target_language": req.target_language,
    }


@app.post("/convert/apply")
def convert_apply(req: ConvertApplyRequest):
    """Log the user's accept/reject decision on a proposed conversion.
    The client applies the code to its own buffer directly (it already
    has `converted_code` from /convert) -- this just closes out the
    history entry, mirroring /apply_fix and /reject_fix for suggest_fix."""
    db.update_outcome(req.action_id, req.outcome)
    return {"status": "ok"}


@app.get("/themes")
def list_themes():
    themes = []
    for f in config.THEMES_DIR.glob("*.json"):
        try:
            themes.append(json.loads(f.read_text()))
        except json.JSONDecodeError:
            continue
    return {"themes": themes, "default": config.DEFAULT_THEME}


@app.get("/session/new")
def new_session():
    return {"session_id": str(uuid.uuid4())}
