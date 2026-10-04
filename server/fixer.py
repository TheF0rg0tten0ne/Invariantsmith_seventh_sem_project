"""
The fix engine: wraps the local GGUF model and turns
(broken_code, error) -> (diff, rationale, confidence).

Model: Qwen2.5-Coder-1.5B-Instruct, Q8_0 GGUF (~1.65GB), CPU inference via
llama-cpp-python. Swappable — see models_registry.py.

The model outputs a full corrected file ("fixed_code"), not a diff. The
server computes the diff itself with difflib (see make_diff) and verifies
against the model's actual candidate code, never against a hand-written
diff the model produced. Earlier versions asked the model to emit a
unified diff directly; a 1.5B model reliably understood WHAT to fix but
not precise line-count/marker bookkeeping, which produced diffs that
either failed to apply or silently corrupted unrelated lines. Full-file
output sidesteps that whole failure class -- "write correct code" is a
task small models are already decent at, unlike "track exact diff hunk
arithmetic."

When you fine-tune your own checkpoint (LoRA on top of Qwen2.5-Coder-1.5B,
trained on the fixed_code-output format described in the README/
data_pipeline), you swap MODEL_PATH and nothing else in this file needs
to change — the interface (prompt in, diff+rationale+confidence out to
callers) stays stable.
"""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import config, chunker, error_detector, languages
from .diff_utils import make_diff

_llm_fix = None      # lazy-loaded singleton for suggest_fix()/explain_error()
_llm_convert = None  # lazy-loaded singleton for convert_code() -- a SEPARATE
                     # adapter/model file when one's configured, since the
                     # two tasks are trained separately on purpose
_load_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="invariantsmith-model")

# Guards model loading. warm_up() runs in a background thread at startup
# while /model/status, /suggest_fix etc. can arrive on request threads; with
# no lock two of them could both see "_llm_fix is None" and each load their
# own ~1.5 GB copy. _load_error remembers a failed load so /model/status can
# report it instead of retrying (and blocking) on every 5-second poll.
_load_lock = threading.Lock()
_loading = False
_load_error: Optional[str] = None


def _system_prompt(language: str) -> str:
    label = languages.LANGUAGES.get(language, languages.PYTHON).label
    return f"""You are Invariantsmith's fix engine, a focused code-repair model.
You are given {label} code and a detected error. Respond ONLY with a JSON object,
no prose outside it, in this exact shape:

{{"fixed_code": "<the ENTIRE corrected file, not just the changed lines>",
 "rationale": "<one or two sentences explaining what was wrong and why this fixes it>",
 "confidence": <float 0.0-1.0>}}

Rules:
- "fixed_code" must be the complete file with the fix applied -- every line,
  not a snippet or a diff. The server computes the diff for you.
- The code is {label}. Keep every fix idiomatic {label} -- correct syntax,
  correct standard-library usage, correct conventions for this language.
- Make the smallest possible change that fixes the stated error. Do not
  rewrite unrelated code, formatting, comments, or variable names.
- If you cannot produce a fix you're confident in, return "fixed_code" as an
  empty string and "confidence" as 0.0 rather than guessing.
"""


def _scoped_system_prompt(language: str) -> str:
    """Used instead of _system_prompt() when suggest_fix() is operating in
    chunked mode (see chunker.py / CHUNK_FILE_LINE_THRESHOLD in config.py):
    the model is shown a SNIPPET of a larger file, not the whole thing, and
    is told explicitly not to try to reason about anything outside it."""
    label = languages.LANGUAGES.get(language, languages.PYTHON).label
    return f"""You are Invariantsmith's fix engine, a focused code-repair model.
You are given a SNIPPET taken from a larger {label} file -- not the whole
file -- along with an error whose reported location falls inside this
snippet, and the exact line range the snippet covers within the full file.
Respond ONLY with a JSON object, no prose outside it, in this exact shape:

{{"fixed_code": "<the corrected version of ONLY the snippet you were given>",
 "rationale": "<one or two sentences explaining what was wrong and why this fixes it>",
 "confidence": <float 0.0-1.0>}}

Rules:
- "fixed_code" must be the complete snippet with the fix applied -- every
  line of the snippet you were given, not a shorter excerpt, and nothing
  from outside the snippet.
- The code is {label}. Keep every fix idiomatic {label} -- correct syntax,
  correct standard-library usage, correct conventions for this language.
- Make the smallest possible change that fixes the stated error. Do not
  rewrite unrelated code, formatting, comments, or variable names within
  the snippet.
- Do not reference, describe, or attempt to fix anything outside the given
  snippet -- you cannot see the rest of the file, and it is not part of
  your response. If the reported error genuinely cannot be fixed using
  only what's shown, return "fixed_code" as an empty string and
  "confidence" as 0.0 rather than guessing about code you can't see.
"""


CONVERT_SYSTEM_PROMPT = """You are Invariantsmith's code-conversion engine.
You are given a complete program in one language and a target language.
Respond ONLY with a JSON object, no prose outside it, in this exact shape:

{"converted_code": "<the ENTIRE program, rewritten in the target language>",
 "notes": "<1-3 sentences on anything non-trivial about the conversion>"}

Rules:
- Preserve the program's behavior and logic exactly. Translate idioms to
  the target language's conventions rather than transliterating syntax
  literally (e.g. Python's dynamic typing -> explicit, sensibly-inferred
  types; print()/System.out.println()/printf() are the same operation in
  three different languages, not three different concepts).
- "converted_code" must be complete and self-contained: correct
  includes/imports, a correct entry point for the target language
  (int main(...) for C, public static void main(String[] args) inside a
  public class for Java, top-level or `if __name__ == "__main__":` for
  Python), and nothing left as a stub or "// TODO".
- Keep names and overall structure recognizable where the target
  language's conventions allow it.
- If some part of the source has no direct equivalent, translate it as
  faithfully as possible and mention the tradeoff in "notes" -- never
  silently drop functionality.
"""


@dataclass
class FixResult:
    diff: str
    rationale: str
    confidence: float
    raw_model_output: str
    verified: bool = False
    # Structured "Checks & Verification" rows for the UI: each is
    # {"status": "pass" | "fail" | "warn" | "info", "text": str}. The legacy
    # `rationale` string still carries the same notes inline in [brackets]
    # (tests and older clients read that); `summary` is the clean model
    # explanation with all bracketed bookkeeping stripped out.
    checks: list = field(default_factory=list)
    summary: str = ""


@dataclass
class ConvertResult:
    converted_code: str
    notes: str
    raw_model_output: str
    ok: bool = False


def _load_llm(model_path):
    from llama_cpp import Llama  # imported lazily so the server can boot without it installed
    if not model_path.exists():
        raise FileNotFoundError(
            f"Model not found at {model_path}. "
            f"Run scripts/download_model.sh first."
        )
    size_mb = model_path.stat().st_size / (1024 * 1024)
    is_stock_base = "instruct" in model_path.name and "fix" not in model_path.name and "convert" not in model_path.name
    print(f"[invariantsmith] Loading model: {model_path} ({size_mb:.0f} MB)")
    if is_stock_base:
        print(f"[invariantsmith] WARNING: '{model_path.name}' looks like the stock, "
              f"un-fine-tuned base model, not a trained fix/convert adapter. If you expected "
              f"trained behavior, confirm the fine-tuned .gguf is actually in {config.MODELS_DIR} "
              f"under its expected name (see server/config.py).")
    return Llama(
        model_path=str(model_path),
        n_ctx=config.LLAMA_CTX_SIZE,
        n_threads=config.LLAMA_THREADS,
        n_gpu_layers=config.LLAMA_N_GPU_LAYERS,
        verbose=False,
    )


def _get_model():
    """The suggest_fix()/explain_error() model."""
    global _llm_fix, _loading, _load_error
    if _llm_fix is None:
        with _load_lock:
            if _llm_fix is None:
                _loading = True
                try:
                    _llm_fix = _load_llm(config.MODEL_PATH)
                    _load_error = None
                except Exception as e:
                    _load_error = str(e)
                    raise
                finally:
                    _loading = False
    return _llm_fix


def _get_convert_model():
    """The convert_code() model -- config.CONVERT_MODEL_PATH falls back to
    the same file as MODEL_PATH when no separate conversion model is
    configured, so single-model deployments are unaffected. When it IS a
    different file, this is cached completely independently of _llm_fix:
    both can be loaded simultaneously (~3.2GB Q8_0 each), which is the
    point -- they're different fine-tunes, not the same weights reused."""
    global _llm_convert
    if _llm_convert is None:
        if config.CONVERT_MODEL_PATH == config.MODEL_PATH:
            _llm_convert = _get_model()  # same file -- just reuse the fix model's instance
        else:
            with _load_lock:
                if _llm_convert is None:
                    _llm_convert = _load_llm(config.CONVERT_MODEL_PATH)
    return _llm_convert


def _normalize_message(message: str) -> str:
    """Strip quoted identifiers/literals from an error message before
    comparing before/after state.

    Without this, renaming a broken identifier to a DIFFERENT broken
    identifier (bar -> bar_typo) produces a technically-different message
    string ("undefined name 'bar'" vs "undefined name 'bar_typo'"), so an
    exact-string comparison sees the original message as gone and reports
    the fix as fully verified -- even though the code is exactly as broken
    as before. Normalizing collapses both to "undefined name '<X>'" so the
    comparison catches the dodge. Tradeoff: this can also flag a fix as
    "still broken" if it coincidentally leaves behind an unrelated error of
    the same shape elsewhere in the file. That false-negative is the safer
    failure mode -- consistent with confidence only ever being adjusted
    down, never up, when verification is uncertain.
    """
    return re.sub(r"'[^']*'", "'<X>'", message)


_STILL_PRESENT_NOTE = "Verification failed: the originally reported error is still present"


def _verify_fix(original_code: str, candidate: str, error_type: str, error_message: str,
                 filename: str, language: str) -> tuple[float, bool, str]:
    """
    Never take the model's confidence at face value. Re-run the same static
    analysis that flagged the original error against the model's proposed
    full-file rewrite, and check whether it's actually gone.

    Returns (confidence_ceiling, verified, note). The caller combines
    confidence_ceiling with the model's self-reported confidence via min()
    -- verification can only push confidence DOWN from what the model
    claimed, never up.
    """
    errors_after = error_detector.analyze(candidate, filename, language)
    syntax_after = next((e for e in errors_after if e.severity == "syntax"), None)
    if syntax_after:
        return 0.0, False, (
            f"Verification failed: applying this fix introduces a syntax error "
            f"({syntax_after.message})."
        )

    normalized_original = _normalize_message(error_message)
    original_still_present = any(
        e.message == error_message or _normalize_message(e.message) == normalized_original
        for e in errors_after
    )

    if original_still_present:
        return 0.0, False, _STILL_PRESENT_NOTE + " after applying this fix."

    # Resolving the targeted error isn't enough on its own -- a fix that
    # introduces a DIFFERENT problem (e.g. fixing an undefined name by
    # duplicating a line that leaves some other name undefined) must not
    # be reported as fully verified just because the original error's
    # specific message is gone. Compare against what was already wrong
    # in the original code so pre-existing, unrelated issues don't block
    # an otherwise-good fix.
    #
    # Important: only count genuinely new ERRORS (severity == "syntax") as
    # blocking. gcc -Wall / -Wextra emit warnings that are often suppressed
    # on broken code due to cascading syntax errors -- they then surface
    # cleanly on the fixed file and look "new" even though the fix didn't
    # introduce them. Treating those warnings as blocking causes correct C
    # and Java fixes to be incorrectly rejected. New lint warnings are
    # surfaced via the other_new_errors path below (partial-verified, 0.5).
    errors_before = error_detector.analyze(original_code, filename, language)
    pre_existing = {_normalize_message(e.message) for e in errors_before}
    new_errors = [
        e for e in errors_after
        if _normalize_message(e.message) not in pre_existing
        and e.severity == "syntax"
    ]
    if new_errors:
        return 0.0, False, (
            f"Verification failed: this fix introduces a new problem not present "
            f"before ({new_errors[0].error_type}: {new_errors[0].message})."
        )

    other_new_errors = [e for e in errors_after if e.message != error_message]
    if other_new_errors:
        preview = "; ".join(e.message for e in other_new_errors[:3])
        return 0.5, True, (
            f"Verified: original error resolved, but the fix introduces or leaves "
            f"other issue(s): {preview}"
        )

    return 1.0, True, "Verified: the reported error is resolved with no new issues introduced."


def warm_up() -> None:
    """Load the model in the background at server startup instead of on the
    first /suggest_fix request. Without this, the user's first click on an
    error pays for both the ~1-5s GGUF load AND generation in one request,
    with the UI showing nothing but a static "Thinking..." the whole time."""
    try:
        _get_model()
    except Exception:
        pass  # is_ready()/suggest_fix will surface the real error on first use


def _token_count(llm, text: str) -> int:
    """Actual tokenized length via the loaded model's own tokenizer, not a
    guess. This is what the dynamic budget below is computed from, so it
    needs to be exact -- a heuristic (e.g. chars/4) drifts enough on real
    code (indentation, punctuation-heavy lines) to under- or over-shoot the
    context window right at the size where it matters."""
    try:
        return len(llm.tokenize(text.encode("utf-8"), add_bos=False))
    except Exception:
        return max(1, len(text) // 3)  # crude fallback if tokenize() ever misbehaves


@dataclass
class _Budget:
    max_tokens: int
    timeout: float
    prompt_tokens: int
    error: Optional[str] = None


def _dynamic_budget(llm, prompt_tokens: int, floor_tokens: int, ceiling_tokens: int,
                     floor_timeout: float) -> _Budget:
    """Turn an actual prompt token count into a (max_tokens, timeout) pair
    sized for THIS request, instead of using the same flat numbers for a
    20-line file and a 2000-line one.

    Output budget: the model's response is always roughly the same order of
    magnitude as the input (a full rewritten file, not a short diff), so
    size the output allowance off the input rather than a constant --
    with headroom for the rationale/notes text and JSON punctuation.

    Timeout: converts the total token traffic (prompt + allowed output)
    into wall-clock time using a conservative tokens/sec estimate, so a
    big request gets proportionally more time instead of hitting the same
    ceiling a small request would.

    If the prompt alone doesn't leave enough room in the context window for
    a useful reply, this returns an Optional error message instead of a
    budget, so the caller can fail fast with a clear explanation rather
    than either truncating the model's output or waiting out a timeout on
    a request that could never have fit.
    """
    available = config.LLAMA_CTX_SIZE - prompt_tokens - 64  # safety margin for special tokens
    min_useful_output = 64
    if available < min_useful_output:
        return _Budget(
            max_tokens=0, timeout=0.0, prompt_tokens=prompt_tokens,
            error=(
                f"This file is too large for the model's context window: the prompt "
                f"alone is ~{prompt_tokens} tokens against a {config.LLAMA_CTX_SIZE}-token "
                f"limit, leaving no room for a response. Raise INVARIANTSMITH_CTX_SIZE "
                f"(server/config.py) if your hardware has the RAM for a bigger KV cache, "
                f"or split the file and fix/convert it in smaller pieces."
            ),
        )

    desired = int(prompt_tokens * 1.4) + 150  # input-proportional + JSON/rationale overhead
    max_tokens = max(floor_tokens, min(desired, ceiling_tokens, available))

    timeout = min(
        config.LLAMA_TIMEOUT_CEILING_S,
        max(
            floor_timeout,
            config.LLAMA_TIMEOUT_OVERHEAD_S
            + (prompt_tokens + max_tokens) / config.LLAMA_EST_TOKENS_PER_SEC,
        ),
    )
    return _Budget(max_tokens=max_tokens, timeout=timeout, prompt_tokens=prompt_tokens)


def _run_with_timeout(fn, *args, timeout: float = config.SUGGEST_FIX_TIMEOUT_S):
    """llama.cpp's generate call can't be cleanly cancelled mid-token, but we
    can at least stop WAITING on it and hand the client a real error instead
    of leaving the request (and the panel's "Thinking...") hanging forever."""
    future = _load_executor.submit(fn, *args)
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError:
        raise TimeoutError(
            f"Model did not respond within {timeout}s. The underlying "
            f"generation call is still running in the background and will "
            f"finish eventually, but this request is giving up rather than "
            f"blocking further."
        )


def model_state() -> dict:
    """Non-blocking snapshot for /model/status. Unlike is_ready(), this NEVER
    triggers a load: the client polls it every few seconds, and a status
    probe that silently blocks for the whole GGUF load (and then times out
    client-side as "server unreachable") is exactly the wrong behavior."""
    if not config.MODEL_PATH.exists():
        return {"state": "missing", "ready": False,
                "error": f"Model file not found: {config.MODEL_PATH.name}"}
    if _llm_fix is not None:
        return {"state": "ready", "ready": True, "error": None}
    if _loading:
        return {"state": "loading", "ready": False, "error": None}
    if _load_error:
        return {"state": "error", "ready": False, "error": _load_error}
    return {"state": "idle", "ready": False, "error": None}


def is_ready() -> bool:
    """
    True only if the model file exists AND can actually be loaded by
    llama.cpp. Existence alone isn't enough — a truncated download or a
    llama-cpp-python version that doesn't understand this GGUF's tokenizer
    format will fail at load time, not at file-check time.
    """
    if not config.MODEL_PATH.exists():
        return False
    try:
        _get_model()
        return True
    except Exception:
        return False


def _splice(lines_full: list[str], start: int, end: int) -> Callable[[str], str]:
    """Build the `reconstruct` function _parse_model_output() uses in
    chunked mode: replace exactly lines [start, end] (1-indexed, inclusive)
    of the ORIGINAL file with whatever the model returned for that scope,
    and leave every other line byte-for-byte untouched. The model's
    returned scope doesn't have to be the same number of lines as the
    original (adding a missing brace on its own line, say) -- this is a
    plain list-slice replacement, not a line-for-line substitution."""
    scope_line_count = end - start + 1

    def reconstruct(fixed_scope_text: str) -> str:
        fixed_lines = fixed_scope_text.split("\n")
        # The scoped system prompt explicitly tells the model to return
        # "every line of the snippet you were given," but small models
        # sometimes ignore that and return only the line(s) they actually
        # changed instead of the full scope. Splicing that in naively
        # doesn't just leave a slightly-off diff -- it silently DELETES
        # the rest of the scope from the file. In the worst observed case
        # a 71-line scope came back as a single changed line, which wiped
        # out an entire function definition; the compiler's resulting
        # error ("interactive_loop" implicitly declared) didn't even hint
        # at what actually happened, because nothing here ever checked.
        # A returned scope that's drastically shorter than what was sent
        # is almost certainly truncation, not a real edit -- legitimate
        # scope-preserving fixes (dropping one duplicate line, collapsing
        # two lines into one) don't lose the majority of the snippet.
        # CHUNK_MIN_SCOPE_LINES keeps real scopes well above this floor,
        # so this only ever fires on genuine truncation, not small scopes.
        if scope_line_count >= 8 and len(fixed_lines) < max(3, scope_line_count * 0.5):
            raise ValueError(
                f"model returned {len(fixed_lines)} line(s) for a "
                f"{scope_line_count}-line scope (lines {start}-{end}) -- "
                f"this looks like truncation, not a real edit, so the "
                f"splice was refused rather than silently deleting the "
                f"rest of the scope"
            )
        return "\n".join(lines_full[:start - 1] + fixed_lines + lines_full[end:])
    return reconstruct


# ---------------------------------------------------------------------
# Python string-literal repair
# ---------------------------------------------------------------------
# Root cause of the "unterminated string literal" failures on converted /
# pasted Python: the model writes "\n" inside a string literal as the
# two-character JSON escape \n, which json.loads() faithfully decodes into a
# REAL line break. By then it is indistinguishable from a line break the
# model meant as code, so print('Done!\n') arrives as
#     print('Done!
#     ')
# C/Java already had a repair for this; Python silently didn't. A 1.5B model
# also can't be asked to repair it afterwards -- it re-emits the same
# decoded-newline mistake -- so this is done deterministically, no LLM.

_PY_MAX_JOIN_LINES = 4
_PY_TAIL_RE = re.compile(r"^\s*[)\]},:;]*\s*(#.*)?$")
_PY_BLOCK_START_RE = re.compile(
    r"^\s*(def|class|if|elif|else|for|while|try|except|finally|with|return|import|from|@|#)\b|^\s*[@#]")


def _py_find_close(line: str, quote: str) -> int:
    """Index of the first unescaped `quote` in `line`, or -1."""
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\":
            i += 2
            continue
        if c == quote:
            return i
        i += 1
    return -1


def _py_try_join(lines: list, idx: int, quote: str):
    """A single-quoted Python string opened on lines[idx] ran off the end of
    the line. Decide whether the following line(s) are the rest of a string
    that was split by a decoded "\\n". Returns (joined_tail, last_idx) where
    joined_tail is what to append after lines[idx] (escaped newlines + the
    continuation text up to and including the closing quote), or None."""
    pieces = []
    for k in range(1, _PY_MAX_JOIN_LINES + 1):
        j = idx + k
        if j >= len(lines):
            return None
        nxt = lines[j]
        close = _py_find_close(nxt, quote)
        if close != -1:
            # Closing quote found. Only trust it if what follows looks like
            # the tail of an expression (')' ',' etc.), not fresh code --
            # otherwise this was a genuinely missing quote and we'd be
            # gluing two unrelated statements together.
            if not _PY_TAIL_RE.match(nxt[close + 1:]):
                return None
            return "\\n" + "\\n".join(pieces + [nxt]), j
        if _PY_BLOCK_START_RE.match(nxt):
            return None  # next line starts a new statement/comment: not a string body
        pieces.append(nxt)
    return None


def repair_python_strings(code: str, close_missing: bool = True) -> str:
    """Re-join Python string literals that were broken across lines by a
    decoded "\\n", and close ones that are simply missing their closing
    quote. Line-oriented and conservative: triple-quoted strings and
    comments are left alone, and every join is gated on the continuation
    looking like the tail of an expression. Callers should only use the
    result if it parses better than the input (see _py_repair_is_improvement).

    close_missing=False restricts this to the join-split-string repair only.
    The model-output path uses that: an f-string the MODEL left unclosed is a
    genuine bug in its answer and must still fail verification, not be
    quietly patched up here."""
    lines = code.split("\n")
    out = []
    i = 0
    in_triple = None
    while i < len(lines):
        line = lines[i]
        if in_triple:
            out.append(line)
            if in_triple in line:
                in_triple = None
            i += 1
            continue

        # Scan this physical line for an unterminated single-line string.
        pos = 0
        n = len(line)
        quote = None
        start = -1
        while pos < n:
            c = line[pos]
            if c == "#":
                break
            if c in "'\"":
                if line.startswith(c * 3, pos):
                    end = line.find(c * 3, pos + 3)
                    if end == -1:
                        in_triple = c * 3
                        break
                    pos = end + 3
                    continue
                j = pos + 1
                closed = False
                while j < n:
                    if line[j] == "\\":
                        j += 2
                        continue
                    if line[j] == c:
                        closed = True
                        break
                    j += 1
                if closed:
                    pos = j + 1
                    continue
                quote, start = c, pos
                break
            pos += 1

        if quote is None:
            out.append(line)
            i += 1
            continue

        # Dangling backslash at EOL is a legal continuation, not a break.
        if line.endswith("\\") and not line.endswith("\\\\"):
            out.append(line)
            i += 1
            continue

        joined = _py_try_join(lines, i, quote)
        if joined is not None:
            tail, last = joined
            out.append(line + tail)
            i = last + 1
        elif close_missing:
            out.append(line + quote)   # missing closing quote: close it
            i += 1
        else:
            out.append(line)
            i += 1
    return "\n".join(out)


def _syntax_error_line(code: str) -> Optional[int]:
    import ast
    try:
        ast.parse(code)
        return None
    except SyntaxError as e:
        return e.lineno or 0


def _py_repair_is_improvement(before: str, after: str) -> bool:
    b, a = _syntax_error_line(before), _syntax_error_line(after)
    if b is None:
        return False          # was already valid: never touch it
    return a is None or a > b


_PY_STRING_REPAIR_TEXT = (
    "A string literal was split across lines -- a '\\n' escape inside the string "
    "was turned into a real line break (typical of converted or pasted code). "
    "Python string literals can't span lines, so the pieces were rejoined with "
    "an escaped \\n and any string missing its closing quote was closed."
)


def _try_python_string_repair(code: str, error_type: str, error_message: str,
                              filename: str, language: str,
                              line: Optional[int]) -> Optional["FixResult"]:
    """Deterministic repair for Python 'unterminated string literal' errors
    (see repair_python_strings). Runs before the model, and its candidate
    still goes through _verify_fix() like any other fix."""
    if language != "python":
        return None
    msg = error_message.lower()
    if "unterminated string" not in msg and "eol while scanning" not in msg \
            and "unterminated f-string" not in msg:
        return None
    cand = repair_python_strings(code)
    if cand == code or not _py_repair_is_improvement(code, cand):
        return None
    ceiling, verified, note = _verify_fix(code, cand, error_type, error_message, filename, language)
    if not verified:
        return None
    return FixResult(
        diff=make_diff(code, cand, filename),
        confidence=min(0.95, ceiling), verified=True, raw_model_output="",
        rationale=_PY_STRING_REPAIR_TEXT, summary=_PY_STRING_REPAIR_TEXT,
        checks=[
            {"status": "info", "text": "Deterministic repair -- no model call needed"},
            {"status": "pass" if verified else "fail", "text": note},
        ],
    )


_SCANF_CALL_START = re.compile(r"\b((?:f|s)?scanf)\s*\(")


def _split_top_level_args(arglist: str) -> list[str]:
    """Split a C call's argument text on top-level commas, respecting
    nested parens/brackets and skipping commas inside string/char literals.
    Good enough for real-world scanf-family calls; not a full C parser."""
    args, depth, buf = [], 0, []
    in_str: Optional[str] = None
    i, n = 0, len(arglist)
    while i < n:
        c = arglist[i]
        if in_str:
            buf.append(c)
            if c == "\\" and i + 1 < n:
                buf.append(arglist[i + 1])
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in ("'", '"'):
            in_str = c
            buf.append(c)
        elif c in "([{":
            depth += 1
            buf.append(c)
        elif c in ")]}":
            depth -= 1
            buf.append(c)
        elif c == "," and depth == 0:
            args.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    args.append("".join(buf))
    return args


def _find_matching_paren(code: str, open_idx: int) -> Optional[int]:
    depth = 0
    in_str: Optional[str] = None
    i, n = open_idx, len(code)
    while i < n:
        c = code[i]
        if in_str:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in ("'", '"'):
            in_str = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


_BARE_PERCENT_ARG = re.compile(
    r"^%\s*([A-Za-z_]\w*(?:\s*(?:\[[^\[\]]*\]|->\s*\w+|\.\s*\w+))*)$"
)


def repair_scanf_address_of(code: str) -> str:
    """Deterministic repair for the classic C beginner typo of writing
    'scanf("%d", %n)' instead of 'scanf("%d", &n)' -- a stray '%' where an
    '&' (address-of) was meant. Only touches arguments that come AFTER the
    call's format string and look like a bare '%identifier' (optionally with
    array/member access); never touches the format string itself, so a
    genuine '%n' format specifier inside the quoted string is untouched.
    """
    out = code
    search_from = 0
    while True:
        m = _SCANF_CALL_START.search(out, search_from)
        if not m:
            break
        open_idx = m.end() - 1
        close_idx = _find_matching_paren(out, open_idx)
        if close_idx is None:
            break
        inner = out[open_idx + 1:close_idx]
        args = _split_top_level_args(inner)
        if len(args) < 2:
            search_from = close_idx + 1
            continue
        # The format string is the first argument that is actually a quoted
        # string literal (fscanf/sscanf have a stream/buffer arg before it).
        fmt_idx = next((i for i, a in enumerate(args) if a.strip().startswith('"')), None)
        if fmt_idx is None:
            search_from = close_idx + 1
            continue
        changed = False
        new_args = list(args)
        for i in range(fmt_idx + 1, len(args)):
            stripped = args[i].strip()
            bm = _BARE_PERCENT_ARG.match(stripped)
            if bm:
                leading_ws = args[i][:len(args[i]) - len(args[i].lstrip())]
                trailing_ws = args[i][len(args[i].rstrip()):]
                new_args[i] = f"{leading_ws}&{bm.group(1)}{trailing_ws}"
                changed = True
        if changed:
            out = out[:open_idx + 1] + ",".join(new_args) + out[close_idx:]
            # Re-search from the same call in case there's another one later;
            # length may have shifted by a few chars, so just continue past
            # this call's original close position plus the small delta.
            search_from = open_idx + 1 + len(",".join(new_args))
        else:
            search_from = close_idx + 1
    return out


def _try_scanf_address_of_typo(code: str, error_type: str, error_message: str,
                                filename: str, language: str,
                                line: Optional[int]) -> Optional[FixResult]:
    """Deterministic repair for 'scanf("%d", %n)' (stray '%' meant to be
    '&'). This is the single most common first-week-of-C typo and is
    completely unambiguous once a scanf-family call is located, so it's
    handled directly instead of asking the model -- which, for small local
    models, tends to also throw in unrelated, unrequested 'improvements'
    (e.g. rewriting 'int main()' to 'int main(void)') on top of the real
    fix. Runs before the model, and the candidate still goes through
    _verify_fix() like any other fix."""
    if language != "c":
        return None
    if not _SCANF_CALL_START.search(code):
        return None
    cand = repair_scanf_address_of(code)
    if cand == code:
        return None
    ceiling, verified, note = _verify_fix(code, cand, error_type, error_message, filename, language)
    if not verified:
        return None
    return FixResult(
        diff=make_diff(code, cand, filename), confidence=min(0.95, ceiling),
        verified=True, raw_model_output="",
        summary="A scanf() argument used '%' where '&' (address-of) was meant; it was corrected.",
        checks=[{"status": "info", "text": "Deterministic repair -- no model call needed"},
                {"status": "pass", "text": note}],
        rationale=("[Invariantsmith: deterministic repair -- 'scanf' needs the address of "
                   f"each variable (&name), not '%name'.] [{note}]"),
    )


_OPEN_BRACE_HDR = re.compile(
    r"^\s*(typedef\s+)?(struct|union|enum|class|interface)\b[^;{}()]*$"
    r"|^\s*[\w\s\*\[\]<>,]+\([^;{}]*\)\s*(throws\s+[\w., ]+)?\s*$"
)


def _try_missing_open_brace(code: str, error_type: str, error_message: str,
                             filename: str, language: str,
                             line: Optional[int]) -> Optional[FixResult]:
    """Deterministic repair for 'expected \u2018{\u2019 before ...' (C/Java):
    append ' {' to the nearest preceding block header that lacks one. No LLM,
    and still goes through _verify_fix() like any other candidate."""
    if language not in ("c", "java") or line is None:
        return None
    if "expected" not in error_message or "{" not in error_message:
        return None
    lines = code.split("\n")
    for i in range(min(line, len(lines)) - 1, max(-1, line - 8), -1):
        text = lines[i]
        if text.strip() and _OPEN_BRACE_HDR.match(text) and not text.rstrip().endswith("{"):
            fixed = lines[:i] + [text.rstrip() + " {"] + lines[i + 1:]
            cand = "\n".join(fixed)
            ceiling, verified, note = _verify_fix(
                code, cand, error_type, error_message, filename, language)
            if not verified:
                return None
            return FixResult(
                diff=make_diff(code, cand, filename), confidence=min(0.95, ceiling),
                verified=True, raw_model_output="",
                summary=f"A block header on line {i + 1} was missing its opening '{{'; it was added.",
                checks=[{"status": "info", "text": "Deterministic repair -- no model call needed"},
                        {"status": "pass", "text": note}],
                rationale=(f"[Invariantsmith: deterministic repair -- added the missing "
                           f"'{{' at the end of line {i + 1}.] [{note}]"))
    return None


def suggest_fix(code: str, error_type: str, error_message: str,
                 filename: str = "buffer.py", language: Optional[str] = None,
                 line: Optional[int] = None) -> FixResult:
    lang = languages.resolve_language(language, code, filename)
    fence = languages.LANGUAGES[lang].fence
    quick = (_try_python_string_repair(code, error_type, error_message, filename, lang, line)
             or _try_scanf_address_of_typo(code, error_type, error_message, filename, lang, line)
             or _try_missing_open_brace(code, error_type, error_message, filename, lang, line))
    if quick:
        return quick
    llm = _get_model()

    total_lines = code.count("\n") + 1
    scope = None
    if total_lines > config.CHUNK_FILE_LINE_THRESHOLD and line is not None:
        scope = chunker.find_scope(
            code, lang, line,
            min_lines=config.CHUNK_MIN_SCOPE_LINES,
            max_lines=config.CHUNK_MAX_SCOPE_LINES,
        )

    reconstruct = None
    scope_note = ""
    if scope:
        start, end = scope
        lines_full = code.split("\n")
        scope_code = "\n".join(lines_full[start - 1:end])
        system_prompt = _scoped_system_prompt(lang)
        user_prompt = (
            f"Filename: {filename}\n"
            f"Error type: {error_type}\n"
            f"Error message: {error_message}\n"
            f"This snippet is lines {start}-{end} of a {total_lines}-line file.\n\n"
            f"Snippet:\n```{fence}\n{scope_code}\n```\n"
        )
        reconstruct = _splice(lines_full, start, end)
        scope_note = (
            f"[Invariantsmith: this file is {total_lines} lines, so the fix was "
            f"scoped to lines {start}-{end} (containing the reported error) "
            f"rather than sent to the model as a whole -- smaller, focused "
            f"chunks are both faster and more reliable for this model than "
            f"reasoning over the entire file at once.] "
        )
    else:
        system_prompt = _system_prompt(lang)
        user_prompt = (
            f"Filename: {filename}\n"
            f"Error type: {error_type}\n"
            f"Error message: {error_message}\n\n"
            f"Code:\n```{fence}\n{code}\n```\n"
        )

    prompt_tokens = _token_count(llm, system_prompt) + _token_count(llm, user_prompt)
    budget = _dynamic_budget(
        llm, prompt_tokens,
        floor_tokens=config.LLAMA_MAX_TOKENS,
        ceiling_tokens=config.LLAMA_MAX_TOKENS_CEILING,
        floor_timeout=config.SUGGEST_FIX_TIMEOUT_S,
    )
    if budget.error:
        return FixResult(diff="", rationale=budget.error, confidence=0.0,
                          raw_model_output="", verified=False)

    def _generate():
        return llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=config.LLAMA_TEMPERATURE,
            max_tokens=budget.max_tokens,
        )

    start_t = time.monotonic()
    try:
        completion = _run_with_timeout(_generate, timeout=budget.timeout)
    except TimeoutError as e:
        return FixResult(diff="", rationale=str(e), confidence=0.0,
                          raw_model_output="", verified=False)

    elapsed = time.monotonic() - start_t
    if elapsed > 5:
        print(f"[fixer] suggest_fix generation took {elapsed:.1f}s "
            f"(prompt_tokens={prompt_tokens}, max_tokens={budget.max_tokens}, "
            f"timeout={budget.timeout:.0f}s, chunked={scope is not None})")

    finish_reason = completion["choices"][0].get("finish_reason")
    raw = completion["choices"][0]["message"]["content"]
    print(f"[fixer] suggest_fix finish_reason={finish_reason!r} chunked={scope is not None} "
        f"raw_len={len(raw)} raw={raw!r}")
    if finish_reason == "length":
        return FixResult(
            diff="", confidence=0.0, raw_model_output=raw, verified=False,
            rationale=(
                scope_note +
                f"Model output was cut off at the {budget.max_tokens}-token budget "
                f"computed for this request (prompt was ~{prompt_tokens} tokens) "
                "before it finished writing the fixed code. Raise "
                "LLAMA_MAX_TOKENS_CEILING and/or INVARIANTSMITH_CTX_SIZE in "
                "server/config.py and retry -- this is a generation-budget "
                "problem, not a bad fix."
            ),
        )
    result = _parse_model_output(raw, code, filename, error_type, error_message, lang,
                                  reconstruct=reconstruct)
    if scope_note:
        result.rationale = scope_note + result.rationale
        result.checks.insert(0, {"status": "info",
                                 "text": f"Scoped to lines {scope[0]}-{scope[1]} of a {total_lines}-line file"})
    return result


def explain_error(code: str, error_type: str, error_message: str,
                   language: Optional[str] = None) -> str:
    """Explain-only mode: no code change, just the 'why'."""
    lang = languages.resolve_language(language, code)
    label = languages.LANGUAGES[lang].label
    fence = languages.LANGUAGES[lang].fence
    llm = _get_model()

    system_prompt = (
        f"You explain {label} errors clearly and briefly for a developer. "
        "Do not propose code changes. 2-4 sentences max."
    )
    user_prompt = (
        f"Error type: {error_type}\nMessage: {error_message}\n\n"
        f"Code:\n```{fence}\n{code}\n```"
    )

    # Explanations are always short (2-4 sentences), so the output budget
    # itself doesn't need to scale with input size the way suggest_fix's
    # does -- but the PROMPT still grows with a large file, so this still
    # needed the same context-overflow guard and a real timeout (it
    # previously had neither: no _run_with_timeout call at all, so a large
    # file could hang this request indefinitely with no way to surface an
    # error to the client).
    prompt_tokens = _token_count(llm, system_prompt) + _token_count(llm, user_prompt)
    budget = _dynamic_budget(
        llm, prompt_tokens,
        floor_tokens=256, ceiling_tokens=256,  # fixed -- explanations don't need more
        floor_timeout=config.SUGGEST_FIX_TIMEOUT_S,
    )
    if budget.error:
        raise TimeoutError(budget.error)  # main.py already handles this for suggest_fix/convert

    def _generate():
        return llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=budget.max_tokens,
        )

    completion = _run_with_timeout(_generate, timeout=budget.timeout)
    return completion["choices"][0]["message"]["content"].strip()


def convert_code(code: str, target_language: str, source_language: Optional[str] = None,
                  filename: str = "buffer") -> ConvertResult:
    """Translate a complete program from one supported language to another.

    Unlike suggest_fix, this always emits a full replacement program (there
    is no meaningful "diff" between, say, Python and C source), so the
    caller is expected to show it as a whole-file preview rather than a
    diff view.
    """
    src_lang = languages.resolve_language(source_language, code, filename)
    if target_language not in languages.LANGUAGES:
        return ConvertResult(converted_code="", notes=f"Unknown target language '{target_language}'.",
                              raw_model_output="", ok=False)
    if target_language == src_lang:
        return ConvertResult(converted_code=code,
                              notes=f"Source was already detected as {languages.LANGUAGES[src_lang].label}; nothing to convert.",
                              raw_model_output="", ok=True)

    src_label = languages.LANGUAGES[src_lang].label
    tgt_label = languages.LANGUAGES[target_language].label
    src_fence = languages.LANGUAGES[src_lang].fence

    llm = _get_convert_model()
    user_prompt = (
        f"Source language: {src_label}\n"
        f"Target language: {tgt_label}\n\n"
        f"Source code:\n```{src_fence}\n{code}\n```\n"
    )

    prompt_tokens = _token_count(llm, CONVERT_SYSTEM_PROMPT) + _token_count(llm, user_prompt)
    budget = _dynamic_budget(
        llm, prompt_tokens,
        floor_tokens=config.CONVERT_MAX_TOKENS,
        ceiling_tokens=config.CONVERT_MAX_TOKENS_CEILING,
        floor_timeout=config.CONVERT_TIMEOUT_S,
    )
    if budget.error:
        return ConvertResult(converted_code="", notes=budget.error, raw_model_output="", ok=False)

    def _generate():
        return llm.create_chat_completion(
            messages=[
                {"role": "system", "content": CONVERT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=config.LLAMA_TEMPERATURE,
            max_tokens=budget.max_tokens,
        )

    start = time.monotonic()
    try:
        completion = _run_with_timeout(_generate, timeout=budget.timeout)
    except TimeoutError as e:
        return ConvertResult(converted_code="", notes=str(e), raw_model_output="", ok=False)

    elapsed = time.monotonic() - start
    if elapsed > 5:
        print(f"[fixer] convert_code generation took {elapsed:.1f}s "
            f"(prompt_tokens={prompt_tokens}, max_tokens={budget.max_tokens}, "
            f"timeout={budget.timeout:.0f}s)")

    finish_reason = completion["choices"][0].get("finish_reason")
    raw = completion["choices"][0]["message"]["content"]
    if finish_reason == "length":
        # convert_code previously had NO check for this at all -- a
        # truncated response just fell through to _parse_convert_output,
        # which would usually fail as malformed JSON with a confusing
        # error, or (worse) occasionally parse a partial/broken program as
        # if it were a complete, valid conversion.
        return ConvertResult(
            converted_code="", raw_model_output=raw, ok=False,
            notes=(
                f"Model output was cut off at the {budget.max_tokens}-token budget "
                f"computed for this request (prompt was ~{prompt_tokens} tokens) "
                "before it finished writing the converted program. Raise "
                "CONVERT_MAX_TOKENS_CEILING and/or INVARIANTSMITH_CTX_SIZE in "
                "server/config.py and retry -- this is a generation-budget "
                "problem, not a bad conversion."
            ),
        )
    return _parse_convert_output(raw, target_language, filename)


def _lenient_unescape(s: str) -> str:
    """Decode common JSON escape sequences without requiring the
    surrounding text to be strictly valid JSON.

    Used only as a fallback when json.loads() fails because the model
    left a stray, unescaped quote inside a string value -- everything
    else about its output was fine. Any 2-character sequence we don't
    recognize as a JSON escape (including a bare embedded quote, which is
    exactly what broke strict parsing in the first place) is passed
    through literally rather than raising.
    """
    escapes = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', "'": "'",
               '\\': '\\', '/': '/', 'b': '\b', 'f': '\f'}
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in escapes:
                out.append(escapes[nxt])
                i += 2
                continue
            if nxt == 'u' and i + 5 < len(s):
                try:
                    out.append(chr(int(s[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
        out.append(c)
        i += 1
    return "".join(out)


def _lenient_parse_fields(blob: str) -> Optional[dict]:
    """Best-effort recovery when json.loads() rejects the model's output.

    The failure mode this targets is specific and common with a 1.5B
    model: it gets the overall {"fixed_code": ..., "rationale": ...,
    "confidence": ...} shape right, but leaves a stray unescaped '"'
    somewhere inside the fixed_code string -- usually a Python string
    literal (an f-string, a "/" separator, a dict literal) it forgot to
    escape for its OWN output format. That single unescaped character
    makes a strict parser reject the entire response even though the
    model's intent is fully recoverable.

    Instead of parsing JSON, this locates the three keys the system
    prompt guarantees will be present, in the order it guarantees they'll
    appear, and slices between them -- tolerating whatever's inside each
    slice, embedded quotes included. It deliberately does NOT try to
    handle output where even the key markers are missing or reordered;
    in that case something other than "one unescaped quote" went wrong,
    and returning None lets the caller fall back to the plain
    malformed-JSON result rather than fabricating a guess.
    """
    try:
        fc_key = blob.index('"fixed_code"')
        colon = blob.index(':', fc_key)
        i = colon + 1
        while i < len(blob) and blob[i] in " \t\r\n":
            i += 1
        if i < len(blob) and blob[i] == '"':
            i += 1
        fc_start = i

        rat_key = blob.rindex('"rationale"')
        if rat_key <= fc_start:
            return None
        fc_raw = blob[fc_start:rat_key].rstrip()
        if fc_raw.endswith(","):
            fc_raw = fc_raw[:-1].rstrip()
        if fc_raw.endswith('"'):
            fc_raw = fc_raw[:-1]

        rat_colon = blob.index(':', rat_key)
        j = rat_colon + 1
        while j < len(blob) and blob[j] in " \t\r\n":
            j += 1
        if j < len(blob) and blob[j] == '"':
            j += 1
        rat_start = j

        conf_key = blob.rindex('"confidence"')
        if conf_key <= rat_start:
            return None
        rat_raw = blob[rat_start:conf_key].rstrip()
        if rat_raw.endswith(","):
            rat_raw = rat_raw[:-1].rstrip()
        if rat_raw.endswith('"'):
            rat_raw = rat_raw[:-1]

        conf_match = re.search(r'"confidence"\s*:\s*([0-9.eE+-]+)', blob[conf_key:])
        confidence = float(conf_match.group(1)) if conf_match else 0.0

        return {
            "fixed_code": _lenient_unescape(fc_raw),
            "rationale": _lenient_unescape(rat_raw),
            "confidence": confidence,
        }
    except (ValueError, IndexError):
        return None


def _fix_overescaped_newlines(code: str) -> str:
    """Undo a rarer, opposite mistake: the model double-escapes control
    characters, emitting a JSON-VALID '\\\\n' (backslash then literal 'n')
    instead of an actual newline. json.loads() parses this without
    complaint -- it's valid JSON -- but the resulting "code" is one long
    line with literal backslash-n text sitting where line breaks belong,
    which is not valid Python.

    Heuristic, applied only when it's a near-certain signature of this
    specific bug: if fixed_code has NO real newlines at all but DOES
    contain literal backslash-n sequences, those were almost certainly
    meant to be newlines. This can't make a good result worse in
    practice -- _verify_fix() re-checks syntax on whatever comes out of
    this, so a wrong guess here just falls through to a normal
    verification failure instead of silently producing broken code.
    """
    if "\n" not in code and "\\n" in code:
        code = code.replace("\\n", "\n").replace("\\t", "\t")
    return code


def _re_escape_newlines_in_strings(code: str, language: str) -> str:
    """Re-escape real newline characters that appear inside C/Java string
    literals after json.loads() has decoded them.

    The model correctly emits '\\n' inside C/Java string literals (e.g.
    printf(\"hello\\n\")), which JSON encodes as '\\\\n'. When json.loads()
    decodes the response, both code-level newlines AND in-string \\n
    escapes become real newline characters -- indistinguishable at that
    point. The result is that printf(\"hello\\n\") becomes:

        printf(\"hello
    \");

    ...which gcc/javac reject with 'missing terminating \" character'.
    C and Java string literals cannot span real newlines (unlike Python
    triple-quoted strings), so any real newline inside a string literal
    was unambiguously a \\n escape sequence and must be restored.
    Python is unaffected -- this function is a no-op for it.
    """
    if language == "python":
        # Python string literals can't span real newlines either (only
        # triple-quoted ones can), so the same decode ambiguity applies.
        # Only touch code that doesn't already parse, and only keep the
        # repair if it genuinely gets further -- valid code is never edited.
        if _syntax_error_line(code) is None:
            return code
        repaired = repair_python_strings(code, close_missing=False)
        return repaired if _py_repair_is_improvement(code, repaired) else code
    if language not in ("c", "java"):
        return code
    result = []
    i = 0
    n = len(code)
    in_string = False
    in_char = False
    while i < n:
        c = code[i]
        if not in_string and not in_char:
            if c == "/" and code[i + 1:i + 2] == "/":
                j = code.find("\n", i)
                j = n if j == -1 else j
                result.append(code[i:j])
                i = j
                continue
            if c == "/" and code[i + 1:i + 2] == "*":
                j = code.find("*/", i + 2)
                j = n if j == -1 else j + 2
                result.append(code[i:j])
                i = j
                continue
            if c == '"':
                in_string = True
                result.append(c)
            elif c == "'":
                in_char = True
                result.append(c)
            else:
                result.append(c)
        elif in_string:
            if c == "\\":
                result.append(c)
                i += 1
                if i < n:
                    result.append(code[i])
            elif c == '"':
                in_string = False
                result.append(c)
            elif c == "\n":
                # Real newline inside a C/Java string literal: restore the escape
                result.append("\\n")
            else:
                result.append(c)
        elif in_char:
            if c == "\\":
                result.append(c)
                i += 1
                if i < n:
                    result.append(code[i])
            elif c == "'":
                in_char = False
                result.append(c)
            elif c == "\n":
                result.append("\\n")
            else:
                result.append(c)
        i += 1
    return "".join(result)


def _parse_model_output(raw: str, original_code: str, filename: str,
                         error_type: str = "", error_message: str = "",
                         language: str = languages.PYTHON.id,
                         reconstruct: Optional[Callable[[str], str]] = None) -> FixResult:
    """
    Parse the model's JSON response. Falls back gracefully if the model
    didn't follow format (small models sometimes wobble on strict JSON) --
    a low-confidence, empty-diff result is safer than crashing the request.

    `reconstruct`, when given (chunked-fix mode -- see chunker.py), turns
    the model's "fixed_code" -- which in that mode is only the fixed
    SNIPPET, not the whole file -- into the full reconstructed file by
    splicing it back into `original_code` at the scope's line range.
    Everything below that point (the unchanged-code check, verification,
    diff computation) then operates on the full file exactly as it does
    in whole-file mode, so chunked and whole-file fixes get identical
    safety guarantees.
    """
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return FixResult(diff="", rationale="Model did not return a parseable fix.",
                          confidence=0.0, raw_model_output=raw, verified=False)

    blob = match.group(0)
    recovered_note = ""
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError:
        parsed = _lenient_parse_fields(blob)
        if parsed is None:
            return FixResult(diff="", rationale="Model returned malformed JSON.",
                              confidence=0.0, raw_model_output=raw, verified=False)
        recovered_note = (
            "[Invariantsmith: recovered from malformed JSON -- the model's raw "
            "output had an unescaped character breaking strict parsing, so "
            "fields were extracted by key position instead of json.loads().] "
        )

    try:
        fixed_code = parsed.get("fixed_code", "")
        summary = str(parsed.get("rationale", "") or "").strip()
        rationale = recovered_note + parsed.get("rationale", "")
        confidence = float(parsed.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
        verified = False
        diff = ""
        checks: list = []
        if recovered_note:
            checks.append({"status": "info",
                           "text": "Model output had malformed JSON; fields were recovered by position"})

        fixed_code = _fix_overescaped_newlines(fixed_code)
        fixed_code = _re_escape_newlines_in_strings(fixed_code, language)

        if reconstruct is not None and fixed_code.strip():
            # Only splice when the model actually returned something --
            # splicing an empty string would silently delete the scope
            # from the file. An empty/no-op response falls through to the
            # "no usable fix" branch below unchanged, exactly as it does
            # in whole-file mode.
            try:
                fixed_code = reconstruct(fixed_code)
            except Exception as e:
                return FixResult(
                    diff="", confidence=0.0, raw_model_output=raw, verified=False,
                    rationale=f"[Invariantsmith: failed to splice the scoped fix back "
                              f"into the full file: {e}]",
                    summary=summary,
                    checks=checks + [{"status": "fail",
                                      "text": f"Could not splice the scoped fix back into the file: {e}"}],
                )

        # A model that just echoes the input back unchanged, or returns
        # nothing, has no fix to offer -- don't let a confidently-wrong
        # self-reported confidence through.
        if not fixed_code.strip() or fixed_code.strip() == original_code.strip():
            rationale = (
                (rationale + " " if rationale else "")
                + "[Invariantsmith: model returned no usable fix (empty or "
                  "unchanged code) -- forcing confidence to 0.]"
            )
            checks.append({"status": "fail", "text": "Model returned no usable fix (empty or unchanged code)"})
            confidence = 0.0

        else:
            # The model only had to write correct code, not track line
            # numbers or diff markers -- we compute the diff ourselves with
            # difflib, which cannot get hunk bookkeeping wrong the way a
            # small model's hand-written diff repeatedly did.
            ceiling, verified, note = _verify_fix(
                original_code, fixed_code, error_type, error_message, filename, language
            )
            confidence = min(confidence, ceiling)
            rationale = (rationale + " " if rationale else "") + f"[{note}]"
            if verified:
                status = "warn" if "but the fix introduces or leaves" in note else "pass"
            else:
                status = "fail"
            checks.append({"status": status, "text": note})

            if not verified and note.startswith(_STILL_PRESENT_NOTE):
                # The candidate changed the text but the reported error is
                # exactly as present as before (e.g. only a comment was
                # added). A diff for that is noise, not a candidate to
                # review -- showing it invites accepting a no-op.
                diff = ""
                rationale += " [No effective change: the reported error is unaffected, so no diff is shown.]"
            else:
                # Always surface the candidate diff so the user can SEE what
                # was proposed. `verified` stays False on failure, so
                # auto-apply (main.py: verified and confidence >= threshold)
                # remains gated.
                diff = make_diff(original_code, fixed_code, filename)
                if not verified:
                    rationale += " [Unverified candidate shown for review -- not safe to auto-apply.]"

        return FixResult(diff=diff, rationale=rationale, confidence=confidence,
                          raw_model_output=raw, verified=verified,
                          checks=checks, summary=summary)
    except (ValueError, TypeError):
        return FixResult(diff="", rationale="Model returned malformed JSON.",
                          confidence=0.0, raw_model_output=raw, verified=False)


def _lenient_parse_convert_fields(blob: str) -> Optional[dict]:
    """Same recovery strategy as _lenient_parse_fields, adapted for the
    two-key {"converted_code", "notes"} shape convert_code() expects.
    Handles the same failure mode: an otherwise well-formed response with
    one stray unescaped quote inside a code string breaking strict JSON."""
    try:
        cc_key = blob.index('"converted_code"')
        colon = blob.index(':', cc_key)
        i = colon + 1
        while i < len(blob) and blob[i] in " \t\r\n":
            i += 1
        if i < len(blob) and blob[i] == '"':
            i += 1
        cc_start = i

        notes_key = blob.rindex('"notes"')
        if notes_key <= cc_start:
            return None
        cc_raw = blob[cc_start:notes_key].rstrip()
        if cc_raw.endswith(","):
            cc_raw = cc_raw[:-1].rstrip()
        if cc_raw.endswith('"'):
            cc_raw = cc_raw[:-1]

        notes_colon = blob.index(':', notes_key)
        j = notes_colon + 1
        while j < len(blob) and blob[j] in " \t\r\n":
            j += 1
        if j < len(blob) and blob[j] == '"':
            j += 1
        notes_start = j
        notes_raw = blob[notes_start:].rstrip()
        if notes_raw.endswith("}"):
            notes_raw = notes_raw[:-1].rstrip()
        if notes_raw.endswith('"'):
            notes_raw = notes_raw[:-1]

        return {
            "converted_code": _lenient_unescape(cc_raw),
            "notes": _lenient_unescape(notes_raw),
        }
    except (ValueError, IndexError):
        return None


def _parse_convert_output(raw: str, target_language: str, filename: str) -> ConvertResult:
    """Parse the model's conversion JSON response, with the same
    malformed-JSON recovery path as _parse_model_output, and verify the
    result at least parses cleanly in the target language before calling
    it usable."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return ConvertResult(converted_code="", notes="Model did not return a parseable conversion.",
                              raw_model_output=raw, ok=False)

    blob = match.group(0)
    recovered_note = ""
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError:
        parsed = _lenient_parse_convert_fields(blob)
        if parsed is None:
            return ConvertResult(converted_code="", notes="Model returned malformed JSON.",
                                  raw_model_output=raw, ok=False)
        recovered_note = (
            "[Invariantsmith: recovered from malformed JSON.] "
        )

    try:
        converted_code = _fix_overescaped_newlines(parsed.get("converted_code", ""))
        converted_code = _re_escape_newlines_in_strings(converted_code, target_language)
        notes = recovered_note + parsed.get("notes", "")

        if not converted_code.strip():
            return ConvertResult(converted_code="", notes="Model returned no usable conversion.",
                                  raw_model_output=raw, ok=False)

        errors = error_detector.analyze(converted_code, filename, target_language)
        syntax_err = next((e for e in errors if e.severity == "syntax"), None)
        if syntax_err:
            notes = (notes + " " if notes else "") + (
                f"[Warning: the converted code has a detected syntax issue "
                f"({syntax_err.message}) -- review before running it.]"
            )
        return ConvertResult(converted_code=converted_code, notes=notes.strip(),
                              raw_model_output=raw, ok=True)
    except (ValueError, TypeError, AttributeError):
        return ConvertResult(converted_code="", notes="Model returned malformed JSON.",
                              raw_model_output=raw, ok=False)
