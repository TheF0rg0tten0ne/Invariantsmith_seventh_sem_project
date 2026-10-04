# Data Pipeline

Mines real-world (broken code, fix) pairs from GitHub commit history to
fine-tune the fixer model.

## 0. Manual authoring (no GitHub mining, do this first / in parallel)

If you don't have `mine_fix_pairs.py` running yet, author examples by hand
under `manual_examples/<slug>/`:

```
manual_examples/
  001_undefined_name/
    broken.py     # code with exactly one flaggable error
    fixed.py      # the corrected code -- keep it a single, minimal hunk
    meta.json     # {"rationale": "...", "confidence": 0.0-1.0,
                  #  "language": "python",           (optional, see below)
                  #  "filename": "buffer.py",       (optional)
                  #  "target_error_index": 0}       (optional, if broken.py
                  #                                   trips >1 detected error)
```

**Multi-language (Python / C / Java):** name the source files
`broken.<ext>` / `fixed.<ext>` for the language you're targeting (`.py`,
`.c`, `.java`). The builder infers the language from that extension
automatically; set `meta.json`'s `"language"` key explicitly only if you
need to disambiguate. There's no separate C/Java doc -- same rules, same
`build_manual_dataset.py` run, just a different extension per example dir.

C/Java examples are bounded by `error_detector`'s C/Java coverage: with
`gcc`/`javac` on `PATH` you get real compiler diagnostics (rich, close to
Python's pyflakes coverage); without them, detection falls back to a
narrow heuristic pass (brace/paren balance + a handful of structural
checks: missing `main`, missing `#include`, missing `class`). An example
whose `broken.<ext>` doesn't trip *something* the detector can see gets
rejected outright, so **run this on a machine with gcc and javac
installed** if you want C/Java coverage anywhere close to Python's, not
just the heuristic subset.

Then:

```bash
python data_pipeline/build_manual_dataset.py
```

This does **not** trust anything you typed by hand. For every example it:
1. Runs `error_detector.analyze()` on `broken.py` to get the real
   `error_type`/`error_message` (never hand-write these -- they must match
   what the server actually detects at inference time, byte for byte).
2. Re-runs the server's own `fixer._verify_fix()` directly against
   `fixed.py`'s content -- the exact same check a real model's full-file
   output goes through in production. If your `fixed.py` wouldn't actually
   verify at inference time, the example is **rejected**, not silently
   included.
3. Separately computes a diff with `diff_utils.make_diff(broken, fixed)`
   for the human-readable `training_data.jsonl` -- this is for your own
   review only, NOT what the model is trained to output (see note below).

Output: `training_data.jsonl` (this README's schema) and
`training_chat.jsonl` (system/user/assistant messages, ready to feed
straight into axolotl/unsloth/llama-factory).

Aim for one error class per example, and vary error types deliberately
(undefined name, missing import, wrong indentation, off-by-one, missing
colon, bad type comparison, etc.) rather than many variations of the same
bug -- the model needs breadth more than depth at this dataset size. Once
C/Java examples are in the mix, also vary *across* languages deliberately
rather than front-loading Python and bolting C/Java on at the end --
lopsided volume is exactly how you get a model that's still secretly
Python-first regardless of what the detector correctly identifies.

## 1. Mine raw pairs (once you're ready to scale past hand-authoring)

```bash
export GITHUB_TOKEN=ghp_xxx   # strongly recommended, avoids rate limits
python mine_fix_pairs.py --all-patterns --max-results 200 --out training_data.jsonl
```

Each line of `training_data.jsonl` looks like:

```json
{
  "repo": "someorg/somerepo",
  "sha": "abc123",
  "filename": "utils/parser.py",
  "commit_message": "fix flake8: remove unused import",
  "diff": "@@ -1,4 +1,3 @@\n-import os\n import sys\n...",
  "rationale": "fix flake8: remove unused import"
}
```

## 2. Clean + label

Raw commit messages are noisy rationales. Before fine-tuning:
- Filter out commits that touch >1 file or >1 hunk (keeps examples focused,
  matches the "minimal diff" behavior we want at inference time)
- Re-run `pyflakes`/`ast.parse` on the *before* state of each file to
  recover the actual `error_type` / `error_message`, so training input
  matches exactly what `fixer.py` sends at inference time
- Optionally rewrite `rationale` with a stronger model into 1-2 clean
  sentences (cheap one-time cost, improves training signal a lot)

## 3. Fine-tune

Recommended: LoRA fine-tune on top of Qwen2.5-Coder-1.5B-Instruct (full
fine-tune isn't necessary at this size and LoRA keeps iteration fast).

**Important, and different from earlier versions of this doc:** the model
outputs the ENTIRE corrected file, not a diff. Earlier versions of this
pipeline trained on diff output directly; eval showed the model reliably
understood WHAT to fix but not precise diff hunk-header/line-count
bookkeeping, producing diffs that mis-applied or corrupted unrelated
lines even when the underlying fix was conceptually correct. The server
now computes the diff itself with `difflib` (see `diff_utils.make_diff`)
from the model's full-file output, which can't get line arithmetic wrong.
This also means less training data is needed, not more — "write correct
code" is a simpler target than "write correct code AND track exact diff
syntax."

Target format — this must match `fixer._system_prompt(language)` and the
JSON output contract in `fixer.py`:

```
input:  system prompt + "Error type: ... / Error message: ... / Code: ..."
output: {"fixed_code": "<entire corrected file>", "rationale": "...", "confidence": ...}
```

Any standard LoRA fine-tuning stack works here (axolotl, unsloth,
llama-factory). After training, merge the adapter and quantize to GGUF
Q8_0 with `llama.cpp`'s `convert_hf_to_gguf.py` + `quantize`, then drop the
resulting file into `models/` and point `MODEL_FILENAME` in
`server/config.py` at it.

## 4. Close the loop with production logs

`server/db.py::export_training_pairs()` pulls real accepted/rejected fixes
from actual usage (the SQLite log). Mix these in on your next fine-tune —
this is your flywheel: the model improves specifically on the errors your
users actually hit and the fixes they actually accept.

## 5. The conversion task (a SEPARATE fine-tune)

Everything above trains the *fix-suggestion* behavior
(`fixer.suggest_fix()`). `fixer.convert_code()` is a different model
behavior with its own system prompt (`CONVERT_SYSTEM_PROMPT`) and its own
output schema, so it gets its own dataset and its own LoRA.

Author examples under `manual_examples_convert/<slug>/`:

```
manual_examples_convert/
  sum_of_list_python_to_c/
    source.py     # the original program, correct and clean
    target.c       # a correct, idiomatic hand-written conversion
    meta.json      # {"notes": "...", "filename": "buffer" (optional)}
```

Language is inferred from the `source.<ext>` / `target.<ext>` extensions —
there's no `"language"` key here, because the two must be *different*
languages by construction (a same-language pair is a fix-task example, not
a conversion one, and gets rejected as such).

```bash
python data_pipeline/build_conversion_dataset.py
```

Both `source` and `target` are checked for syntax errors in their
respective languages, and **both must be clean**. The target must compile
for the obvious reason. The source must too, so the model doesn't
implicitly learn to "fix while converting" — that's a different,
unrequested behavior, and blending it in here is how you end up with a
converter that silently rewrites logic it thinks is buggy.

Output: `training_data_convert.jsonl` (human-readable) and
`training_chat_convert.jsonl` (the trainable one).

Target format — must match `fixer.CONVERT_SYSTEM_PROMPT` and
`_parse_convert_output()`:

```
input:  CONVERT_SYSTEM_PROMPT + "Source language: ... / Target language: ... / Source code: ..."
output: {"converted_code": "<entire program in the target language>", "notes": "..."}
```

**Train this as a separate adapter, not mixed into the fix-task data.**
Two tasks with different system prompts and different JSON schemas in one
LoRA risks the model blurring them — emitting `fixed_code` when asked to
convert, or vice versa.

Aim for coverage across all 6 directed pairs (python↔c, python↔java,
c↔java) rather than just the pair you happen to care about; the model
needs to learn "read language A, emit language B" as a general
capability, and one-directional data teaches it a one-directional habit.

### Regenerating the bulk examples

`generate_c_examples.py`, `generate_java_examples.py`, and
`generate_conversion_examples.py` are one-shot dev tools that emit the
templated bulk of the C/Java/conversion examples (60/45/48 respectively)
across a fixed set of verified error classes and canonical programs. Each
one verifies every example against `error_detector.analyze()` at
generation time, so a bad template fails loudly there instead of showing
up as a `[REJECTED]` line later. Re-run them to regenerate or extend the
batches; they overwrite their own output dirs and leave hand-authored
examples alone.

Note that these give *templated* variation across a fixed set of error
classes — genuine breadth, but not the organic diversity of real-world
code. Closing the remaining gap to Python's volume and variety is a
mining job (`mine_fix_pairs.py --language c|java --all-patterns`), not
something worth hand-authoring further.
