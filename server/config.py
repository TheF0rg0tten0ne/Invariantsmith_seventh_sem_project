"""
Central configuration for Invariantsmith.

Kept as plain constants (not env-driven magic) so the whole system is
readable at a glance. Override via environment variables if you like.
"""
import os
from pathlib import Path

# --- Paths -------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = Path(os.environ.get("INVARIANTSMITH_MODELS_DIR", ROOT_DIR / "models"))
THEMES_DIR = Path(os.environ.get("INVARIANTSMITH_THEMES_DIR", ROOT_DIR / "themes"))
LOGS_DIR = Path(os.environ.get("INVARIANTSMITH_LOGS_DIR", ROOT_DIR / "logs"))
DB_PATH = Path(os.environ.get("INVARIANTSMITH_DB_PATH", LOGS_DIR / "invariantsmith.sqlite3"))

# --- Model ---------------------------------------------------------------
# Three possible files can live in MODELS_DIR, each with its own distinct
# name so they can never collide or silently shadow one another:
#   qwen2.5-coder-1.5b-instruct.Q8_0.gguf  -- stock, un-fine-tuned base
#                                              (scripts/download_model.sh)
#   qwen2.5-coder-1.5b-fix.Q8_0.gguf        -- fine-tuned fix-suggestion adapter
#   qwen2.5-coder-1.5b-convert.Q8_0.gguf    -- fine-tuned conversion adapter
# (data_pipeline/train_lora.py writes the latter two directly under these
# names after training -- see its GGUF-export step.)
#
# Resolution order for each: explicit env var, if set > fine-tuned file,
# if present in MODELS_DIR > stock base file. This means training a model
# and dropping it in models/ is enough by itself -- no env var, no editing
# this file, no restart-time flags. Nothing here touches the filesystem at
# import time beyond a plain .exists() check.
_STOCK_MODEL_FILENAME = "qwen2.5-coder-1.5b-instruct.Q8_0.gguf"
_FIX_MODEL_FILENAME = "qwen2.5-coder-1.5b-fix.Q8_0.gguf"
_CONVERT_MODEL_FILENAME = "qwen2.5-coder-1.5b-convert.Q8_0.gguf"

MODEL_FILENAME = os.environ.get("INVARIANTSMITH_MODEL_FILE")
if not MODEL_FILENAME:
    MODEL_FILENAME = (
        _FIX_MODEL_FILENAME if (MODELS_DIR / _FIX_MODEL_FILENAME).exists()
        else _STOCK_MODEL_FILENAME
    )
MODEL_PATH = MODELS_DIR / MODEL_FILENAME

# suggest_fix()/explain_error() and convert_code() are trained as SEPARATE
# LoRA adapters (different system prompt, different output schema -- see
# data_pipeline/README.md #5), so they can be served from two different
# GGUF files. If no dedicated conversion model has been trained/dropped
# in, this falls back to whatever MODEL_FILENAME resolved to above (the
# fine-tuned fix model, or the stock base) -- exactly the old
# single-model behavior, so nothing breaks if you've only got one file.
CONVERT_MODEL_FILENAME = os.environ.get("INVARIANTSMITH_CONVERT_MODEL_FILE")
if not CONVERT_MODEL_FILENAME:
    CONVERT_MODEL_FILENAME = (
        _CONVERT_MODEL_FILENAME if (MODELS_DIR / _CONVERT_MODEL_FILENAME).exists()
        else MODEL_FILENAME  # no dedicated convert model found -- share whatever fix resolved to
    )
CONVERT_MODEL_PATH = MODELS_DIR / CONVERT_MODEL_FILENAME

# llama.cpp runtime settings — tuned for a small CPU box.
#
# n_ctx has to hold: system prompt + the ENTIRE input file (suggest_fix and
# convert_code both send the whole file, not a snippet) + the model's ENTIRE
# rewritten file in its response, since this design always emits a full
# corrected/converted file rather than a diff. That's roughly 2x the input
# file's token count, plus JSON/prompt overhead. 4096 only has room for
# genuinely small files (~150-200 lines) before prompt+completion together
# blow the window -- which silently produces either truncated/garbage output
# or a hang that looks like a timeout, exactly at that size. Qwen2.5-Coder-1.5B
# natively supports up to 32768 tokens, so there's plenty of headroom to grow
# into; 8192 is a safe default for a CPU box (KV cache cost for a 1.5B model
# at this size is a few hundred MB, not a real constraint). Bump further via
# the env var if you regularly work on very large files.
LLAMA_CTX_SIZE = int(os.environ.get("INVARIANTSMITH_CTX_SIZE", 8192))
LLAMA_THREADS = os.cpu_count() or 4
LLAMA_N_GPU_LAYERS = int(os.environ.get("INVARIANTSMITH_GPU_LAYERS", 0))  # 0 = CPU only
LLAMA_TEMPERATURE = 0.2   # low temp: we want deterministic, minimal diffs

# max_tokens and the request timeout used to be flat constants sized for a
# small file. fixer.py now computes both PER REQUEST from the actual
# tokenized prompt length (see _dynamic_budget() in fixer.py): a small file
# still gets a fast, tight budget; a large one gets proportionally more
# output headroom and more wall-clock time instead of being truncated or
# timing out. The constants below are just the floor/ceiling/rate inputs to
# that calculation, not the budget itself.
LLAMA_MAX_TOKENS = 768          # floor: minimum output budget regardless of input size
LLAMA_MAX_TOKENS_CEILING = 6000 # ceiling: never ask for more than this in one completion
SUGGEST_FIX_TIMEOUT_S = 20      # floor: minimum timeout regardless of input size

# Cross-language conversion emits a full second program, not a diff --
# needs materially more headroom than a minimal fix + rationale.
CONVERT_MAX_TOKENS = 1200          # floor
CONVERT_MAX_TOKENS_CEILING = 6000  # ceiling
CONVERT_TIMEOUT_S = 45             # floor

# Conservative CPU throughput estimate (tokens/sec, combined prefill+decode)
# used to convert a prompt+output token budget into a wall-clock timeout.
# Deliberately pessimistic -- it's fine if real hardware is faster than
# this (the request just finishes early); it's not fine if it's slower
# than assumed (the request gets killed before the model could finish).
# Lower this if you're on genuinely slow/old CPU hardware and still see
# timeouts on large files after upgrading from a fixed budget.
LLAMA_EST_TOKENS_PER_SEC = float(os.environ.get("INVARIANTSMITH_EST_TOKENS_PER_SEC", 12.0))
# Fixed per-request overhead (model call setup, JSON parsing, etc.) added
# on top of the size-proportional estimate above.
LLAMA_TIMEOUT_OVERHEAD_S = 3.0
# Absolute ceiling on the computed timeout so a huge file degrades to a
# clear "too large" error instead of an effectively unbounded wait.
LLAMA_TIMEOUT_CEILING_S = 240.0

# Chunked-fix thresholds (see chunker.py). Above this many lines, and only
# when the caller gave us a reported error line to scope around,
# suggest_fix() sends the model a small chunk of the file (the function/
# struct/block containing the error, padded to a workable minimum size)
# instead of the whole file, then splices the model's fix back into the
# original. This is an ACCURACY fix, not just a latency one: a small model
# reasoning over a whole large file is where it starts hallucinating fixes
# for the wrong part of the code, even when it's perfectly capable of
# fixing the same class of bug in a small, focused snippet. Small files
# never chunk -- there's no accuracy problem to solve there, and full-file
# mode gives the model a little more surrounding context for free.
CHUNK_FILE_LINE_THRESHOLD = 60
CHUNK_MIN_SCOPE_LINES = 12
CHUNK_MAX_SCOPE_LINES = 80

# --- Fix engine behavior -------------------------------------------------
# Below this confidence, a fix is suggest-only (never auto-applied).
AUTO_APPLY_THRESHOLD = float(os.environ.get("INVARIANTSMITH_AUTO_APPLY_THRESHOLD", 0.85))

# Debounce window for live re-analysis while typing (ms). Client-side value,
# kept here so client + server agree on the contract.
LIVE_ANALYSIS_DEBOUNCE_MS = 250

# --- Server ---------------------------------------------------------------
HOST = "127.0.0.1"   # local only, by design — no web UI, no external exposure
PORT = 8731

# --- Themes ---------------------------------------------------------------
DEFAULT_THEME = "dark"

for d in (MODELS_DIR, THEMES_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)
