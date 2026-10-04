# Invariantsmith

A local-first, offline AI code editor backend for **Python, C, and Java**,
built around a lightweight fine-tuned code-fixer model instead of a
general-purpose LLM API.

No web UI. Everything is served over a local API (FastAPI, binds to
127.0.0.1 only) that a native client (Qt/Tauri/etc.) talks to.

## Model

Target: **Qwen2.5-Coder-1.5B-Instruct**, quantized to **Q8_0 GGUF** (~1.65 GB).
Served locally via `llama-cpp-python` (CPU-friendly, no GPU required, no
network calls at inference time).

This repo does not ship model weights. Run `scripts/download_model.sh` to
fetch the GGUF file into `models/`.

## Layout

```
invariantsmith/
├── server/               # API server + inference + logging
│   ├── main.py           # FastAPI app, all endpoints
│   ├── config.py         # paths, thresholds, theme config
│   ├── db.py             # SQLite logging (explainability store)
│   ├── languages.py      # language profiles + offline auto-detect heuristics
│   ├── error_detector.py # multi-language static analysis (ast/pyflakes for
│   │                      # Python; gcc/javac when available for C/Java,
│   │                      # heuristic fallback otherwise)
│   ├── fixer.py           # llama.cpp model wrapper + fix generation +
│   │                      # verification + cross-language conversion
│   ├── diff_utils.py     # unified diff generation/application/validation
│   └── models_registry.py# tracks available local model files
├── client/                # PySide6 desktop client
│   ├── main.py            # entry point
│   ├── main_window.py     # window layout: editor + suggestion panel +
│   │                      # language picker + theme switcher + history
│   ├── languages.py       # client-side language id/label/extension table
│   ├── editor_widget.py   # buffer, line numbers, debounced live-analysis
│   │                      # loop, error squiggles, language mode tracking
│   ├── highlighter.py     # tree-sitter syntax highlighting for Python/C/Java,
│   │                      # switchable at runtime
│   ├── suggestion_panel.py# diff view, confidence badge, accept/reject
│   ├── convert_dialog.py  # cross-language conversion preview + accept/reject
│   ├── theme.py           # theme JSON -> Qt palette/colors
│   └── api_client.py      # HTTP wrapper around the server API
├── themes/               # token-based theme JSON files
├── scripts/
│   ├── download_model.sh # fetch the GGUF (run locally, needs HF access)
│   ├── init_db.py        # create the SQLite schema
│   └── smoke_test.py     # scripted end-to-end check of the running server
├── data_pipeline/
│   └── mine_fix_pairs.py # mines GitHub commits for (broken, fixed) pairs
├── tests/
└── models/                # (empty) drop the .gguf here
```

## Quickstart

```bash
cd invariantsmith
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r client/requirements.txt

# fetch the model (needs internet access to huggingface.co)
bash scripts/download_model.sh

# init the logging DB
python scripts/init_db.py

# run the API server (localhost only)
uvicorn server.main:app --host 127.0.0.1 --port 8731

# in a second terminal, run the desktop client
python -m client.main
```

C/Java syntax checking prefers the real compiler (`gcc -fsyntax-only`,
`javac`) when one is on `PATH`, and falls back to a heuristic pass
(brace/paren balance + a few structural checks) when it isn't. Neither is
required to run Invariantsmith -- they're an optional accuracy upgrade for
those two languages.

## Desktop client

A minimal but fully wired PySide6 editor:
- **Multi-language support (Python / C / Java)** with a language picker in
  the title bar. "Auto-detect" (the default) lets the server's heuristics
  classify the buffer as you type and updates the status-bar badge and
  syntax highlighting live; picking a language explicitly pins it
  regardless of content, and opening a `.py`/`.c`/`.h`/`.java` file pins it
  by extension automatically.
- **Cross-language conversion.** The "Convert to ▾" toolbar button turns
  the whole current file into a complete, runnable program in one of the
  other two supported languages (idiomatic translation, not a literal
  transliteration), shown side-by-side in a preview dialog before you
  decide whether to replace your buffer with it.
- **Live syntax highlighting** via tree-sitter (Python/C/Java grammars,
  swapped at runtime as the language changes), reparsed on every debounced
  keystroke (250ms, matches `LIVE_ANALYSIS_DEBOUNCE_MS` in both configs)
- **Live error squiggles** from `/analyze`, run off the GUI thread so typing
  never stalls, plus a **current-line highlight** that tracks the caret
- **Problems panel** below the editor listing every live error/warning at
  once (not just the one under the cursor) with an error/warning count;
  click a row to jump straight to that line and request a fix
- **Toolbar** with New/Open/Save, "Fix next problem" (`Ctrl+.`), and
  "Convert to ▾" for cross-language translation
- **Status bar** showing live model status (polled every 5s off the GUI
  thread — ready/loading/unreachable), the detected/active language, and
  the caret's line/column
- **Click an underlined error, or a Problems-panel row,** to request a fix
  — this calls `/suggest_fix` and shows the diff, verified confidence
  badge, and rationale in the side panel. Accept applies it through
  `/apply_fix`; Reject logs the rejection.
- **Explain**, next to Accept/Reject in the suggestion panel, calls
  `/explain` for a plain-English answer to "what does this error mean"
  without committing to any code change — independent of whether a fix
  was ever accepted or rejected.
- **Theme switcher** in the title bar, backed by `/themes`; the toolbar,
  status bar, and problems panel are all themed along with everything else.
- **History strip** at the bottom showing the latest logged AI action

Note: clicking an error (in the editor or the problems panel) is
deliberately the *only* thing that triggers a fix request — not cursor
movement — since `suggest_fix` is an expensive CPU-bound model call and
shouldn't fire on every arrow-key press.


## API (all local, JSON over HTTP)

| Endpoint            | Method | Purpose                                                     |
|----------------------|--------|----------------------------------------------------------------|
| `/analyze`           | POST   | Run static + model error detection on a code buffer            |
| `/suggest_fix`       | POST   | Get a full-file fix suggestion + verified confidence score     |
| `/apply_fix`         | POST   | Apply a previously suggested fix, log the action                |
| `/explain`           | POST   | Explain an error without changing code                          |
| `/languages`         | GET    | List supported languages (id/label/extensions)                  |
| `/detect_language`   | POST   | Cheap offline language guess for a code buffer                  |
| `/convert`           | POST   | Translate a whole file into another supported language          |
| `/convert/apply`     | POST   | Log accept/reject of a proposed conversion                      |
| `/history`           | GET    | Fetch the AI-action log for a file or session                   |
| `/model/status`      | GET    | Check whether the model is loaded and ready                     |
| `/themes`            | GET    | List available themes                                           |

All of `/analyze`, `/suggest_fix`, and `/explain` take an optional
`language` field (omit it or send `"auto"` to let the server detect;
send `"python"`/`"c"`/`"java"` to pin it).

See `server/main.py` for request/response schemas.

## Design notes

- **Full-file rewrites, verified server-side.** The model is prompted to
  emit the entire corrected file rather than a hand-written diff -- small
  models are unreliable at diff/hunk bookkeeping, but writing correct code
  is exactly what they're tuned for. The server computes the actual diff
  itself with `difflib` (which cannot get line numbers wrong the way a
  model can) and only trusts the result once static analysis confirms the
  targeted error is actually gone. Cross-language conversion reuses the
  same "model writes the whole file, server verifies" shape, just without
  a diff at the end (there's no meaningful line-diff between, say, Python
  and Java source).
- **Language detection is layered, not model-based.** Filename extension
  wins outright when known; otherwise a small offline, dependency-free
  heuristic (weighted keyword/pattern scoring) picks among the three
  supported grammars. This never calls the LLM and never leaves the
  machine, matching every other analysis step in this project.
- **Every AI action is logged** (`server/db.py`) — the error detected, the
  diff proposed, the model's short rationale, confidence score, and whether
  the user accepted/rejected/edited it. This is both your "why did the AI do
  that" UI panel and your fine-tuning flywheel (accepted fixes → positive
  data, rejected/edited fixes → hard negatives).
- **Confidence-gated auto-apply.** `config.py` has an `AUTO_APPLY_THRESHOLD`;
  below it, fixes are suggest-only.

