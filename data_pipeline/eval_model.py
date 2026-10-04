"""
Sanity-check the currently-configured model (server/config.MODEL_FILENAME)
against every case under manual_examples/ -- the exact same bug shapes it
was (presumably) trained on.

This is NOT a measure of general capability. Passing 11/11 here only tells
you the LoRA actually took for these specific patterns, not that it
generalizes to bugs it's never seen. Useful as a fast "did the fine-tune
even work at all" check before you invest time writing 50 more examples.

Usage:
    python data_pipeline/eval_model.py
    python data_pipeline/eval_model.py --examples-dir data_pipeline/generalization_examples

Pass --examples-dir to point at a held-out set (bug shapes NOT in
manual_examples/) instead of the training data -- that's the real test;
see generalization_examples/README.md.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import config, error_detector, fixer  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--examples-dir", default=str(Path(__file__).parent / "manual_examples"))
    args = parser.parse_args()
    examples_dir = Path(args.examples_dir)

    print(f"Model: {config.MODEL_FILENAME}")
    print(f"Examples: {examples_dir}\n")

    example_dirs = sorted(p for p in examples_dir.iterdir() if p.is_dir())
    passed, failed = 0, 0

    for d in example_dirs:
        broken = (d / "broken.py").read_text()
        meta = json.loads((d / "meta.json").read_text())
        target_idx = meta.get("target_error_index", 0)

        errors = error_detector.analyze(broken, meta.get("filename", "buffer.py"))
        if target_idx >= len(errors):
            print(f"[SKIP] {d.name}: target error no longer detected")
            continue
        target_error = errors[target_idx]

        result = fixer.suggest_fix(
            broken, target_error.error_type, target_error.message,
            filename=meta.get("filename", "buffer.py"),
        )

        status = "PASS" if result.verified else "FAIL"
        if result.verified:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] {d.name}  (confidence={result.confidence:.2f})")
        if not result.verified:
            print(f"        rationale: {result.rationale[:150]}")
            print(f"        raw model output:\n{result.raw_model_output.strip()[:400]}")

    print(f"\n{passed}/{passed + failed} verified.")
    if passed == 0:
        print("Zero passes on the exact examples it trained on usually means the "
              "LoRA didn't actually merge in, or the chat template used at inference "
              "doesn't match what train_lora.py trained against. Worth checking "
              "before writing more training data.")


if __name__ == "__main__":
    main()
