"""
Assembles training_data.jsonl (README schema) and training_chat.jsonl
(ready-to-feed LoRA chat format) from hand-authored examples under
manual_examples/<slug>/{broken.py, fixed.py, meta.json}.

Why a builder instead of hand-writing the assistant target directly: the
model outputs a full corrected file, not a diff, so there's no diff syntax
to get wrong here -- but this script still recomputes the diff itself
(for the human-readable training_data.jsonl / for display) and re-runs the
server's own error_detector + _verify_fix on fixed.py directly, exactly as
production verifies a model's full-file output. If your fixed.py wouldn't
actually verify at inference time, the example is rejected here rather
than silently poisoning the dataset.

Usage:
    python data_pipeline/build_manual_dataset.py
    python data_pipeline/build_manual_dataset.py --examples-dir path/to/dir

Each example directory needs:
    broken.py    -- code containing exactly one flaggable error
    fixed.py     -- the corrected code (minimal change -- one hunk)
    meta.json    -- {"rationale": str, "confidence": float,
                      "filename": str (optional, default "buffer.py"),
                      "target_error_index": int (optional, default 0 --
                          which detected error in broken.py this example
                          is fixing, if analyze() finds more than one)}
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import error_detector, languages  # noqa: E402
from server.diff_utils import make_diff  # noqa: E402
from server.fixer import _system_prompt, _verify_fix  # noqa: E402

# meta.json's optional "language" key, and the broken.<ext>/fixed.<ext>
# filenames this builder looks for. Absent an explicit "language", we
# infer it from whichever broken.<ext> file is actually present, and fall
# back to Python for old example dirs that predate multi-language support
# (broken.py with no meta.json "language" key at all).
_LANG_EXTENSIONS = {lid: languages.LANGUAGES[lid].extensions[0].lstrip(".")
                     for lid in languages.LANGUAGE_ORDER}


def build_user_prompt(code: str, error_type: str, error_message: str, filename: str, language: str) -> str:
    """Must stay byte-for-byte identical to the prompt fixer.suggest_fix()
    sends at inference time, or the model is trained on a distribution
    shift from what it'll actually see in production."""
    fence = languages.LANGUAGES[language].fence
    return (
        f"Filename: {filename}\n"
        f"Error type: {error_type}\n"
        f"Error message: {error_message}\n\n"
        f"Code:\n```{fence}\n{code}\n```\n"
    )


def _resolve_language_and_paths(example_dir: Path, meta: dict) -> tuple[str, Path, Path] | None:
    """Pick the language for this example dir and its broken/fixed paths.

    Explicit meta.json "language" wins if present and valid. Otherwise,
    infer from whichever broken.<ext> file actually exists in the
    directory -- exactly one should. Returns None (caller records the
    problem) if neither yields something usable.
    """
    declared = meta.get("language")
    if declared is not None:
        if declared not in _LANG_EXTENSIONS:
            return None
        ext = _LANG_EXTENSIONS[declared]
        return declared, example_dir / f"broken.{ext}", example_dir / f"fixed.{ext}"

    present = [(lid, ext) for lid, ext in _LANG_EXTENSIONS.items()
               if (example_dir / f"broken.{ext}").exists()]
    if len(present) == 1:
        lid, ext = present[0]
        return lid, example_dir / f"broken.{ext}", example_dir / f"fixed.{ext}"
    if len(present) > 1:
        return None  # ambiguous -- e.g. both broken.py and broken.c present
    # Nothing matched any known extension -- fall back to the historical
    # Python-only default so pre-existing example dirs keep working.
    return "python", example_dir / "broken.py", example_dir / "fixed.py"


def process_example(example_dir: Path) -> tuple[dict | None, list[str]]:
    problems: list[str] = []

    meta_path = example_dir / "meta.json"
    if not meta_path.exists():
        return None, ["missing meta.json"]
    meta = json.loads(meta_path.read_text())

    resolved = _resolve_language_and_paths(example_dir, meta)
    if resolved is None:
        return None, [
            "could not determine language: meta.json 'language' is invalid/ambiguous, "
            f"or multiple broken.<ext> files present (expected one of "
            f"{sorted(_LANG_EXTENSIONS)})"
        ]
    language, broken_path, fixed_path = resolved

    for p in (broken_path, fixed_path):
        if not p.exists():
            problems.append(f"missing {p.name}")
    if problems:
        return None, problems

    broken = broken_path.read_text()
    fixed = fixed_path.read_text()

    filename = meta.get("filename", languages.LANGUAGES[language].default_filename)
    target_idx = meta.get("target_error_index", 0)
    rationale = meta.get("rationale", "").strip()
    confidence = meta.get("confidence")

    if not rationale:
        problems.append("meta.json: 'rationale' is empty")
    if confidence is None or not (0.0 <= float(confidence) <= 1.0):
        problems.append("meta.json: 'confidence' missing or out of [0.0, 1.0]")

    # 1. broken.<ext> must actually trigger a detectable error -- otherwise
    #    there's nothing for the model to have learned to fix. Note this is
    #    only as strong as error_detector's C/Java coverage: without gcc/javac
    #    on PATH it falls back to a narrow heuristic pass (brace/paren
    #    balance + a few structural checks), so C/Java example authors are
    #    implicitly bounded by whatever's actually installed on this machine.
    errors_before = error_detector.analyze(broken, filename, language)
    if not errors_before:
        problems.append(f"{broken_path.name}: error_detector found nothing wrong with it "
                         f"(for {language}, check whether gcc/javac are on PATH -- "
                         f"the heuristic fallback catches far less)")
        return None, problems
    if target_idx >= len(errors_before):
        problems.append(
            f"meta.json: target_error_index={target_idx} but only "
            f"{len(errors_before)} error(s) detected in {broken_path.name}"
        )
        return None, problems
    target_error = errors_before[target_idx]

    if len(errors_before) > 1 and "target_error_index" not in meta:
        problems.append(
            f"{broken_path.name} has {len(errors_before)} errors detected but "
            f"meta.json doesn't set target_error_index -- defaulting to 0 "
            f"({target_error.error_type}: {target_error.message!r}), but "
            f"confirm that's the one fixed.{_LANG_EXTENSIONS[language]} actually addresses"
        )

    # 2. Recompute the diff ourselves -- never trust a hand-typed one.
    diff = make_diff(broken, fixed, filename=filename)
    if not diff.strip():
        problems.append(f"{broken_path.name} and {fixed_path.name} are identical -- no diff to learn from")
        return None, problems

    # 3. Run the EXACT verification path the server runs on a real model
    #    output. If this diff wouldn't verify in production, don't train
    #    the model to think it should.
    ceiling, verified, note = _verify_fix(
        broken, fixed, target_error.error_type, target_error.message, filename, language
    )
    if not verified:
        problems.append(f"would NOT verify at inference time: {note}")
        return None, problems

    if problems:  # non-fatal warnings collected above (e.g. multi-error note)
        return None, problems

    record = {
        "language": language,
        "filename": filename,
        "error_type": target_error.error_type,
        "error_message": target_error.message,
        "diff": diff,
        "rationale": rationale,
        "confidence": float(confidence),
    }

    chat_record = {
        "messages": [
            {"role": "system", "content": _system_prompt(language)},
            {"role": "user", "content": build_user_prompt(
                broken, target_error.error_type, target_error.message, filename, language
            )},
            {"role": "assistant", "content": json.dumps({
                "fixed_code": fixed, "rationale": rationale, "confidence": float(confidence),
            })},
        ]
    }
    return {"record": record, "chat": chat_record}, []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--examples-dir", default=str(Path(__file__).parent / "manual_examples"))
    parser.add_argument("--out-dir", default=str(Path(__file__).parent))
    args = parser.parse_args()

    examples_dir = Path(args.examples_dir)
    out_dir = Path(args.out_dir)
    example_dirs = sorted(p for p in examples_dir.iterdir() if p.is_dir())

    if not example_dirs:
        print(f"No example directories found under {examples_dir}")
        return

    accepted, rejected = [], []
    for d in example_dirs:
        result, problems = process_example(d)
        if result is None:
            rejected.append((d.name, problems))
            print(f"[REJECTED] {d.name}")
            for p in problems:
                print(f"    - {p}")
        else:
            accepted.append((d.name, result))
            print(f"[OK]       {d.name}")

    records_path = out_dir / "training_data.jsonl"
    chat_path = out_dir / "training_chat.jsonl"
    with records_path.open("w") as f_rec, chat_path.open("w") as f_chat:
        for _, result in accepted:
            f_rec.write(json.dumps(result["record"]) + "\n")
            f_chat.write(json.dumps(result["chat"]) + "\n")

    print(f"\n{len(accepted)} accepted, {len(rejected)} rejected out of {len(example_dirs)} total.")
    if accepted:
        print(f"Wrote {records_path}")
        print(f"Wrote {chat_path}  (feed this directly to axolotl/unsloth/llama-factory)")
    if rejected:
        print("\nFix the rejected examples above and re-run -- nothing partial gets written for them.")


if __name__ == "__main__":
    main()
