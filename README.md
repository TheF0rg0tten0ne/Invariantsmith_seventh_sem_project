# Invariantsmith

A local-first, offline AI code editor for **Python, C, and Java**. A desktop
editor talks to a small FastAPI server on your own machine, which runs a
lightweight fine-tuned code-fixer model. Nothing is sent to a cloud API, and
code never leaves the machine.

The server binds to `127.0.0.1` only. There is no web UI; the desktop client
(PySide6) is the front end.

## What it does

- **Live analysis** while you type: syntax errors, lint warnings, and common
  mistakes in Python, C, and Java, shown as squiggles and in a Problems panel.
- **Verified fixes.** Click an error to request a fix. The fix is shown as a
  diff with a confidence badge and a "Checks & Verification" list. The server
  only marks a fix verified if the reported error is gone and no new errors
  appear. You can then Accept, Reject, Regenerate, or ask for a plain-English
  Explain.
- **Deterministic repairs** for common beginner errors (for example
  `scanf("%d", n)` missing `&`, unterminated Python strings split across lines,
  and missing opening braces). These run without the model, so they are fast
  and predictable.
- **Cross-language conversion.** Convert a whole program between Python, C,
  and Java. The result is previewed side by side before you replace your buffer.
- **Run and debug** inside the editor, with a Terminal tab for program input
  (stdin) and an Output tab. Run warns you when the code reads input and the
  stdin field is empty.
- **History.** Every AI action and its outcome (accepted, rejected, edited) is
  logged to SQLite for review.

## Why a small local model

The model is Qwen2.5-Coder-1.5B-Instruct, fine-tuned with LoRA adapters and
served through `llama-cpp-python` on CPU. It runs on an ordinary laptop with no
GPU and no network access at inference time.

The trade-off is that a 1.5B model is less capable than a large cloud model.
Invariantsmith compensates by checking its work instead of trusting it:

- the server computes the diff itself (the model never writes hunk line numbers);
- each fix must clear static analysis before it is marked verified;
- long files are split into scoped chunks around the reported error, which
  improves accuracy for a small model;
- common errors are fixed deterministically, without the model at all.

## Requirements

- Python 3.11 or newer (3.12 tested)
- About 2 GB of free disk space for the model, plus the repository
- 8 GB RAM recommended
- No GPU required
- Optional: `gcc` and `javac` on `PATH` for more accurate C and Java checks.
  Without them, a heuristic checker is used.

## Quickstart

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/TheF0rg0tten0ne/Invariantsmith_seventh_sem_project.git
cd Invariantsmith_seventh_sem_project
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

The repository does not yet include a root `requirements.txt` for the server,
so install the server packages directly:

```bash
pip install fastapi uvicorn pydantic pyflakes llama-cpp-python
pip install -r client/requirements.txt
```

`client/requirements.txt` provides PySide6, requests, and the tree-sitter
grammars.

### 3. Get the model

The model is not stored in the repository. Place the GGUF file in `models/`.
Two options:

**Option A: stock base model (about 1.65 GB, downloaded automatically)**

```bash
bash scripts/download_model.sh
```

This fetches `Qwen2.5-Coder-1.5B-Instruct` (Q8_0) from Hugging Face and saves it as
`models/qwen2.5-coder-1.5b-instruct.Q8_0.gguf`.

**Option B: fine-tuned model files (from the project Google Drive)**

Download the `.gguf` files from the project folder:
https://drive.google.com/drive/folders/1q3km44Y8uxNlnX34n4BrtZXFsSiktCMW?usp=drive_link

Place them in the `models/` folder inside the cloned repository. The server
picks them up by filename, with no configuration:

| File | Used for |
|------|----------|
| `qwen2.5-coder-1.5b-fix.Q8_0.gguf` | fix suggestions and explanations |
| `qwen2.5-coder-1.5b-convert.Q8_0.gguf` | cross-language conversion (falls back to the fix model if absent) |

If only the stock base file is present, the server uses it for everything.

To point at a different file, set `INVARIANTSMITH_MODEL_FILE` (and
`INVARIANTSMITH_CONVERT_MODEL_FILE`) to a filename inside `models/`.

### 4. Initialize the log database (optional)

The server creates the database on startup. To create it ahead of time:

```bash
python scripts/init_db.py
```

### 5. Start the server

```bash
uvicorn server.main:app --host 127.0.0.1 --port 8731
```

The model loads in the background. Check its state at
`http://127.0.0.1:8731/model/status`, which reports
`missing | idle | loading | ready | error`.

### 6. Start the editor

In a second terminal, from the repository root:

```bash
python -m client.main
```

Open a `.py`, `.c`, `.h`, or `.java` file, or create a new one. Click an
underlined error, or a row in the Problems panel, to request a fix. Accept
applies it.

## Editor features

**Editing**
- Auto-closing brackets and quotes, with smart stepping over closers.
- Enter between braces opens an indented block with the closer on its own line.
- Electric dedent: typing `}` or Python's `else:` / `except:` lines up with the block.
- Bracket matching highlight, with `Ctrl+Shift+\` to jump to the matching bracket.
- Occurrence highlight for the word under the caret, and indent guides.
- Line commands: Shift+Enter (line below), Ctrl+Shift+Enter (line above),
  Ctrl+Shift+K (delete line), Ctrl+L (select line), Ctrl+D (next occurrence),
  Ctrl+] / Ctrl+[ (indent / outdent), smart Home.
- Tidy on save (trims trailing whitespace, ends the file with a newline). It is
  on by default and can be switched off in Settings.

**Suggestions (Ctrl+Space, or start typing)**
- Language keywords, built-ins, common library functions, snippets, and words
  from the current file.
- Context-aware: `#inc` offers headers for C, `import` lists modules for
  Python and Java, and members appear after a dot for well-known receivers.
- Snippets with tab stops for `for`, `main`, `def`, `sout`, `printf`,
  `scanfi`, `malloc`, `try`, `class`, and more. Repeated placeholders mirror
  as you type.
- Keys: Up/Down to move, Tab to accept, Esc to close.

**Navigation**
- Ctrl+P: go to file in the open folder.
- Ctrl+Shift+O: go to a function or class in this file.
- Ctrl+G: go to line. Ctrl+H: find and replace.
- Ctrl+Shift+P: command palette.

**Fixing**
- Ctrl+. fixes the next problem. Ctrl+Enter accepts the fix. Alt+Enter
  accepts and moves to the next problem.
- Accept sends the fix to `/apply_fix`. If the buffer changed since the fix was
  generated, the fix is refused and you are asked to regenerate it, so your
  edits are never overwritten silently.

Press **Ctrl+/** for the full keyboard shortcut sheet, or open it from the menu.

## Architecture

```
┌────────────────────┐   HTTP (localhost)   ┌─────────────────────┐   llama-cpp   ┌──────────────┐
│ Desktop client     │ ───────────────────▶ │ FastAPI server      │ ────────────▶ │ GGUF model   │
│ PySide6 editor     │ ◀─────────────────── │ analysis, fixing,   │ ◀──────────── │ (local, CPU) │
│ (client/)          │                      │ verification (server/)│             └──────────────┘
└────────────────────┘                      └─────────────────────┘
                                                      │
                                                      ▼
                                              SQLite action log
```

The server exposes these endpoints (see `server/main.py` for schemas):

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/analyze` | POST | Static analysis of a buffer (runs on each debounced edit) |
| `/suggest_fix` | POST | Propose a verified fix as a diff, with checks and confidence |
| `/apply_fix` | POST | Apply a previously suggested diff; 409 `stale_diff` if the buffer moved on |
| `/reject_fix` | POST | Log a rejected fix |
| `/explain` | POST | Plain-English explanation of an error, without changing code |
| `/convert` | POST | Translate a whole file into another supported language |
| `/convert/apply` | POST | Log the accept or reject of a conversion |
| `/detect_language` | POST | Offline language guess for a buffer |
| `/languages` | GET | Supported languages |
| `/history` | GET | AI action log for a file or session |
| `/model/status` | GET | Model state and available models |
| `/themes` | GET | Available editor themes |

`/analyze`, `/suggest_fix`, and `/explain` accept an optional `language` field.
Omit it or send `"auto"` to let the server detect the language.

## Configuration

Settings live in `server/config.py`. Common environment overrides:

| Variable | Default | Purpose |
|----------|---------|---------|
| `INVARIANTSMITH_MODEL_FILE` | auto | Fix model filename inside `models/` |
| `INVARIANTSMITH_CONVERT_MODEL_FILE` | auto | Conversion model filename inside `models/` |
| `INVARIANTSMITH_CTX_SIZE` | 8192 | Context window; raise it for very large files |
| `INVARIANTSMITH_GPU_LAYERS` | 0 | Layers offloaded to GPU (0 = CPU only) |
| `INVARIANTSMITH_AUTO_APPLY_THRESHOLD` | 0.85 | Confidence needed before auto-apply is offered |
| `INVARIANTSMITH_EST_TOKENS_PER_SEC` | 12.0 | Throughput estimate used to set request timeouts |

Fixes below the auto-apply threshold are always suggest-only.

## Tests

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests
```

The suite (111 tests at v30) covers diff generation and application, static
analysis, the deterministic repairs, fix verification, language detection,
autocomplete logic, and the editor driven by real key events.

## Repository layout

```
server/        API server, model wrapper, verification, diffs, logging
  main.py        FastAPI app and endpoints
  fixer.py       fix generation, deterministic repairs, verification, conversion
  error_detector.py  static analysis (pyflakes; gcc/javac when available)
  diff_utils.py  unified diff generation and application
  chunker.py     scoped chunks for large files
  languages.py   language profiles and offline detection
  config.py      paths, model names, timeouts, thresholds
  db.py          SQLite action log
client/        PySide6 desktop editor
  main_window.py, editor_widget.py, suggestion_panel.py, bottom_panel.py, ...
  autocomplete.py, completion_data.py   suggestion popup and snippets
  highlighter.py                         tree-sitter syntax highlighting
  api_client.py                          HTTP wrapper around the server
themes/        editor theme JSON files
scripts/       download_model.sh, init_db.py, smoke_test.py
data_pipeline/ fix-pair mining, dataset building, LoRA training, evaluation
tests/         pytest suite
models/        GGUF model files (not in git; see Quickstart step 3)
logs/          SQLite action log
```

## Training pipeline

`data_pipeline/` contains the scripts used to build the fine-tuning data and
train the adapters: mining fix pairs from repositories, generating C and Java
examples, building the conversion dataset, `train_lora.py` (LoRA training and
GGUF export), and `eval_model.py`. See `data_pipeline/README.md` for the steps
and the data format.

## Development history

The project was built iteratively, with training done on Google Colab (GPU).
Version ranges below are approximate and follow the author's own recollection.

- **v1 to v5.** Code correction features added, and the fine-tuned fix model trained.
- **v5 to v10.** Explanations of why an error happens and where the code is fixed.
- **v10 to v16.** C and Java support added.
- **v16 to v22.** Code conversion between C, Python, and Java.
- **v22 to v26.** UI tidying, and support for user code files larger than 300 lines.
- **v27 to v30.** UI revamp and smoothing, and feature classification. The release
  notes are in `CHANGELOG_v27.md` to `CHANGELOG_v30.md`. Highlights:
  - v27: Python string repair, a rebuilt window layout, and structured verification checks.
  - v28: Convert button back in the title bar, `stale_diff` handling for conflicting fixes, a deterministic `scanf` repair, and a stdin warning on Run.
  - v29: Editor polish (auto-close, smart Enter, autocomplete with snippets, Ctrl+P and symbol navigation, bracket matching, tidy on save, shortcut sheet).
  - v30: Fixed Apply returning 409 for model fixes on buffers without a trailing newline.

## Troubleshooting

- **"Model not loaded" (503).** Check `models/` for a `.gguf` file with one of
  the expected names, then check `/model/status`. The first request also loads
  the model, which can take a while on CPU.
- **"This fix no longer matches the current code" (409).** The buffer changed
  after the fix was generated. Click Regenerate.
- **Fix is slow or times out on a large file.** Raise
  `INVARIANTSMITH_EST_TOKENS_PER_SEC` only if your CPU is faster than the
  default estimate. Otherwise, fix one error at a time.
- **C or Java errors look wrong.** Install `gcc` and a JDK so the server can use
  the real compilers instead of the heuristic checker.

## Status and limitations

- Fix quality depends on the model. Verification prevents unverified fixes
  from being offered as safe, but it does not guarantee that a fix is the one
  you wanted. Review the diff before accepting.
- Tested on Linux with an offscreen Qt platform. Windows and macOS keyboard
  layouts, including AltGr, have not been fully tested.
- Conversion produces a complete program, not a line-for-line translation. Read
  the result before using it.

## License

To be confirmed.
