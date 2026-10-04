"""
Build training_chat_convert.jsonl from hand-authored source/target pairs
under manual_examples_convert/<slug>/.

This is the conversion-task counterpart to build_manual_dataset.py (which
only covers the fix-suggestion task) -- until now there was no training
data at all for fixer.convert_code(), even though it's a separate model
behavior with its own system prompt and output schema.

Layout per example dir:
    manual_examples_convert/
      001_sum_list_py_to_c/
        source.py       # the ORIGINAL program (any of .py/.c/.java)
        target.c         # a correct, idiomatic hand-written conversion
        meta.json         # {"notes": "...", "filename": "buffer" (optional)}

Language is inferred from source.<ext> / target.<ext> -- no separate
"language" field needed, since (unlike the fix task) there's no
ambiguity: the extension IS the language here, and source/target must be
two *different* languages by construction.

Usage:
    python build_conversion_dataset.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import error_detector, languages  # noqa: E402
from server.fixer import CONVERT_SYSTEM_PROMPT  # noqa: E402

EXAMPLES_DIR = Path(__file__).parent / "manual_examples_convert"
OUT_CHAT_PATH = Path(__file__).parent / "training_chat_convert.jsonl"

_EXT_TO_LANG = {languages.LANGUAGES[lid].extensions[0].lstrip("."): lid
                for lid in languages.LANGUAGE_ORDER}


def _find_lang_file(example_dir: Path, stem: str) -> tuple[str, Path] | None:
    """Find source.<ext> or target.<ext> and resolve its language from
    the extension."""
    for ext, lid in _EXT_TO_LANG.items():
        p = example_dir / f"{stem}.{ext}"
        if p.exists():
            return lid, p
    return None


def process_example(example_dir: Path) -> tuple[dict | None, list[str]]:
    problems: list[str] = []

    meta_path = example_dir / "meta.json"
    if not meta_path.exists():
        return None, ["missing meta.json"]
    meta = json.loads(meta_path.read_text())

    src = _find_lang_file(example_dir, "source")
    tgt = _find_lang_file(example_dir, "target")
    if src is None:
        problems.append(f"no source.<ext> found (expected one of {sorted(_EXT_TO_LANG)})")
    if tgt is None:
        problems.append(f"no target.<ext> found (expected one of {sorted(_EXT_TO_LANG)})")
    if problems:
        return None, problems

    src_lang, src_path = src
    tgt_lang, tgt_path = tgt
    if src_lang == tgt_lang:
        return None, [f"source and target are both '{src_lang}' -- nothing to convert, "
                       f"that's a fix-task example, not a conversion-task one"]

    source_code = src_path.read_text()
    target_code = tgt_path.read_text()
    notes = meta.get("notes", "").strip()
    filename = meta.get("filename", "buffer")

    if not notes:
        problems.append("meta.json: 'notes' is empty")

    # The target must actually be clean in its own language -- training
    # the model on a "correct" conversion that doesn't even compile would
    # be worse than no training data at all.
    tgt_errors = error_detector.analyze(target_code, filename, tgt_lang)
    syntax_err = next((e for e in tgt_errors if e.severity == "syntax"), None)
    if syntax_err is not None:
        problems.append(
            f"{tgt_path.name}: has a detected syntax issue in {tgt_lang} "
            f"({syntax_err.message}) -- fix target.{tgt_path.suffix.lstrip('.')} first"
        )
        return None, problems

    # The source should also be clean, for the same reason error_detector
    # is required to be silent on broken.py's *other* lines in the fix
    # pipeline: we don't want the model implicitly learning to "fix while
    # converting" here, that's a different, unrequested behavior.
    src_errors = error_detector.analyze(source_code, filename, src_lang)
    src_syntax_err = next((e for e in src_errors if e.severity == "syntax"), None)
    if src_syntax_err is not None:
        problems.append(
            f"{src_path.name}: has a detected syntax issue in {src_lang} "
            f"({src_syntax_err.message}) -- fix source.{src_path.suffix.lstrip('.')} first"
        )
        return None, problems

    if problems:
        return None, problems

    src_label = languages.LANGUAGES[src_lang].label
    tgt_label = languages.LANGUAGES[tgt_lang].label
    src_fence = languages.LANGUAGES[src_lang].fence

    user_prompt = (
        f"Source language: {src_label}\n"
        f"Target language: {tgt_label}\n\n"
        f"Source code:\n```{src_fence}\n{source_code}\n```\n"
    )
    chat_record = {
        "messages": [
            {"role": "system", "content": CONVERT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": json.dumps({
                "converted_code": target_code, "notes": notes,
            })},
        ]
    }
    record = {
        "source_language": src_lang, "target_language": tgt_lang,
        "filename": filename, "notes": notes,
    }
    return {"record": record, "chat": chat_record}, []


def main():
    if not EXAMPLES_DIR.exists():
        print(f"No {EXAMPLES_DIR} directory found -- nothing to build.")
        return

    accepted, rejected = 0, 0
    chat_lines = []
    data_lines = []
    for example_dir in sorted(p for p in EXAMPLES_DIR.iterdir() if p.is_dir()):
        result, problems = process_example(example_dir)
        if result is None:
            print(f"[REJECTED] {example_dir.name}")
            for p in problems:
                print(f"    - {p}")
            rejected += 1
            continue
        print(f"[OK]       {example_dir.name}")
        data_lines.append(json.dumps(result["record"]))
        chat_lines.append(json.dumps(result["chat"]))
        accepted += 1

    print(f"\n{accepted} accepted, {rejected} rejected out of {accepted + rejected} total.")
    if rejected:
        print("Fix the rejected examples above and re-run -- nothing partial gets written for them.")

    out_data_path = Path(__file__).parent / "training_data_convert.jsonl"
    out_data_path.write_text("\n".join(data_lines) + ("\n" if data_lines else ""))
    OUT_CHAT_PATH.write_text("\n".join(chat_lines) + ("\n" if chat_lines else ""))
    print(f"Wrote {out_data_path}")
    print(f"Wrote {OUT_CHAT_PATH}  (feed this directly to axolotl/unsloth/llama-factory, "
          f"as a SEPARATE fine-tune from training_chat.jsonl -- convert and fix are "
          f"different tasks with different system prompts and output schemas; mixing "
          f"them into one LoRA risks the model blurring the two behaviors)")


if __name__ == "__main__":
    main()
