"""
LoRA fine-tune Qwen2.5-Coder-1.5B-Instruct on data_pipeline/training_chat.jsonl,
then export straight to GGUF for drop-in use by server/fixer.py.

Requires a CUDA GPU (a free Colab T4 is enough for the 1.5B base model).
Run `python data_pipeline/build_manual_dataset.py` first to generate
training_chat.jsonl -- this script will refuse to run without it.

Install (once):
    pip install unsloth trl peft accelerate bitsandbytes datasets

Run (fix-suggestion adapter):
    python data_pipeline/train_lora.py

Run (conversion adapter -- SEPARATE model, see data_pipeline/README.md #5):
    python data_pipeline/train_lora.py --data data_pipeline/training_chat_convert.jsonl
"""
import argparse
import os
import json
import shutil
from pathlib import Path

# On Colab, everything on the local disk is wiped when the runtime
# disconnects/recycles -- both the pip installs AND the base model download
# happen fresh every session. If you're iterating more than once, mount
# Drive and point HF's cache there so you don't re-download the base model
# every time:
#
#   from google.colab import drive
#   drive.mount('/content/drive')
#   os.environ["HF_HOME"] = "/content/drive/MyDrive/hf_cache"
#
# Also save OUT_DIR to Drive before the session ends -- a disconnect
# mid-training loses everything not already copied out.

_HERE = Path(__file__).parent

# The fix task and the conversion task are SEPARATE adapters -- different
# system prompts, different output schemas. Training them into one LoRA
# risks the model emitting "fixed_code" when asked to convert (or vice
# versa), so each gets its own --data/--out pair. Defaults preserve the
# original fix-task behavior for anyone running this with no arguments.
_parser = argparse.ArgumentParser(description=__doc__)
_parser.add_argument("--data", type=Path, default=_HERE / "training_chat.jsonl",
                      help="Chat-format JSONL to train on. Use training_chat_convert.jsonl "
                           "for the conversion adapter.")
_parser.add_argument("--out", type=Path, default=None,
                      help="Output dir. Defaults to lora_out/ for the fix task and "
                           "lora_out_convert/ when --data points at the convert dataset.")
_parser.add_argument("--base-model", default=None,
                      help="Override BASE_MODEL (see the size/speed tradeoff notes below).")
_parser.add_argument("--epochs", type=float, default=3.0,
                      help="num_train_epochs (default 3).")
_args = _parser.parse_args()

DATA_PATH = _args.data
if _args.out is not None:
    OUT_DIR = _args.out
else:
    OUT_DIR = _HERE / ("lora_out_convert" if "convert" in DATA_PATH.name else "lora_out")

# Model size vs. serving speed tradeoff -- pick ONE:
#   "unsloth/Qwen2.5-Coder-1.5B-Instruct"  fastest to train + fastest CPU
#                                           inference at serving time, but
#                                           weakest instruction-following
#   "unsloth/Qwen2.5-Coder-3B-Instruct"    meaningful quality jump, still
#                                           reasonable on CPU with Q4/Q5
#                                           quant -- good default if you're
#                                           unsure
#   "unsloth/Qwen2.5-Coder-7B-Instruct"    noticeably better fixes, but
#                                           expect 3-5x slower generation
#                                           per suggestion on your CPU at
#                                           home vs. 1.5B. Fine on a free
#                                           Colab GPU to TRAIN, the cost is
#                                           at SERVING time on your machine.
# Free Colab T4 (16GB) fits LoRA training on any of these in 4-bit. If you
# hit CUDA OOM on the 7B, drop per_device_train_batch_size to 1 below.
#
# --- 1.5B LoRA ceiling reached, 2026-08 -- read before touching this file ---
# Two rounds of iteration on the 1.5B base plateaued and gave a fairly clean
# signal to stop, rather than an ambiguous one:
#
#   Round 1 (128 -> 150 examples, added echo-guard + multi-declaration
#   training data targeting specific eval failures): fixed 6 of the targeted
#   failures on the training set, but regressed 2 previously-passing
#   examples, and the held-out generalization set (generalization_examples/)
#   didn't move AT ALL -- same 3 failures (g06, g11, g13), byte-identical
#   raw model output before and after.
#
#   Round 2 (150 -> 159 examples, added training data landing directly on
#   g06/g11/g13's exact shapes, PLUS lr 2e-4 -> 1.5e-4 with cosine schedule
#   + warmup_ratio=0.1 to reduce the round-1 regression noise): the held-out
#   set was STILL byte-identical on all 3 -- direct training coverage
#   produced zero transfer, even to structurally-adjacent inputs (2 of the
#   9 new examples failed on their OWN training set with the same failure
#   signature as the held-out case they were built to fix: a colon fix that
#   drops a dependent helper function, an assert-tuple fix that only
#   generalized to 2-3 elements but not 4). Regression count on the
#   original 150 also got WORSE (8 -> 12 failures) despite the gentler
#   schedule.
#
# Conclusion: this isn't a data-coverage gap or a learning-rate/warmup
# problem -- both were tried directly against the exact failing shapes and
# both came back flat or negative. It's the 1.5B LoRA's ceiling for
# one-shot, full-file, must-not-touch-unrelated-code correctness. Decision
# was to stop pushing this model/config and put further effort into
# error_detector.py coverage and the client UI instead of more rounds here.
#
# _verify_fix() means this ceiling is safe to sit at: every eval run above
# already showed that failures fail CLOSED (no suggestion offered), never
# open (wrong code silently applied) -- so stopping here doesn't trade away
# correctness, just leaves some fixable-in-principle cases unfixed.
#
# If you do want to push past this later, the 3B swap above is the
# documented next lever -- but treat it as a real commitment (different
# Colab tier, longer runs), not a quick retry, since two cheaper levers
# were already tried here and both came back negative.
BASE_MODEL = _args.base_model or "unsloth/Qwen2.5-Coder-1.5B-Instruct"

if not DATA_PATH.exists():
    raise SystemExit(
        f"{DATA_PATH} not found. Run `python data_pipeline/"
        f"{'build_conversion_dataset.py' if 'convert' in DATA_PATH.name else 'build_manual_dataset.py'}` "
        f"first -- this script trains on its output, never on the example dirs directly."
    )

n_examples = sum(1 for _ in open(DATA_PATH))
if n_examples == 0:
    raise SystemExit(
        f"{DATA_PATH} has zero examples -- every example was rejected by "
        f"build_manual_dataset.py. Scroll up to its [REJECTED] output for why. "
        f"Nothing to train on until at least one example is accepted."
    )
if n_examples < 20:
    print(f"WARNING: only {n_examples} training examples. This will run, but a "
          f"LoRA trained on this few examples is a pipeline smoke test, not a "
          f"model you should expect real behavior change from. Keep authoring "
          f"examples under manual_examples/ and re-run build_manual_dataset.py "
          f"before treating the result as production-ready.")

from unsloth import FastLanguageModel
from datasets import load_dataset
from trl import SFTTrainer, SFTConfig

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=BASE_MODEL,
    max_seq_length=2048,
    load_in_4bit=True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r=32,
    lora_alpha=32,
    lora_dropout=0.0,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                     "gate_proj", "up_proj", "down_proj"],
    bias="none",
    use_gradient_checkpointing="unsloth",
)

dataset = load_dataset("json", data_files=str(DATA_PATH), split="train")


def format_example(example):
    text = tokenizer.apply_chat_template(
        example["messages"], tokenize=False, add_generation_prompt=False
    )
    return {"text": text}


dataset = dataset.map(format_example)

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=2048,
    args=SFTConfig(
        output_dir=str(OUT_DIR),
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        num_train_epochs=_args.epochs,  # small dataset -> more epochs; watch for overfitting
        learning_rate=1.5e-4,        # was 2e-4 -- see the "1.5B LoRA ceiling
                                      # reached" note above BASE_MODEL for why,
                                      # and why this didn't end up being the fix
        lr_scheduler_type="cosine",
        warmup_ratio=0.1,
        logging_steps=1,
        save_strategy="epoch",
        report_to="none",
    ),
)

trainer.train()

# Merge LoRA into the base weights and export straight to GGUF.
merged_dir = OUT_DIR / "merged"
model.save_pretrained_merged(str(merged_dir), tokenizer, save_method="merged_16bit")

gguf_dir = OUT_DIR / "gguf"
# q8_0 for the 1.5B (small enough that quality loss from quantizing further
# isn't worth it). If you trained 7B, use q4_k_m or q5_k_m instead -- q8_0
# at 7B is ~7.5GB and will be painfully slow on CPU; q4_k_m is ~4.5GB and
# a much more reasonable serving-time tradeoff.
quant_method = "q8_0" if "1.5B" in BASE_MODEL else "q4_k_m"
model.save_pretrained_gguf(str(gguf_dir), tokenizer, quantization_method=quant_method)

# unsloth writes the actual .gguf into "<gguf_dir>_gguf/", not inside
# gguf_dir itself -- search for it rather than assuming the exact path,
# since that's an internal unsloth naming quirk that could change.
candidates = sorted(OUT_DIR.glob("**/*.gguf"), key=lambda p: p.stat().st_mtime, reverse=True)
if not candidates:
    print(f"\nWARNING: save_pretrained_gguf() ran but no .gguf file was found under {OUT_DIR}. "
          f"Check the output above for a llama.cpp build failure (missing cmake/build-essential "
          f"is the usual cause on a fresh Colab runtime) and, if needed, quantize the merged "
          f"model already sitting in {merged_dir}/ by hand.")
else:
    produced = candidates[0]  # most recently written, in case an older run left a stray .gguf here
    # Task-specific filename -- deliberately NOT the same name unsloth/the
    # stock download use for the untouched base model. Training two
    # separately-fine-tuned adapters that both export as
    # "qwen2.5-coder-1.5b-instruct.Q8_0.gguf" is exactly how you silently
    # overwrite one fine-tune with another, or can't tell either apart
    # from the un-fine-tuned base.
    task = "convert" if "convert" in DATA_PATH.name else "fix"
    final_name = f"qwen2.5-coder-1.5b-{task}.Q8_0.gguf"
    models_dir = _HERE.parent / "models"
    models_dir.mkdir(exist_ok=True)
    final_path = models_dir / final_name
    shutil.copy2(produced, final_path)
    print(f"\nDone. Copied {produced} -> {final_path}")
    if task == "fix":
        print("This matches server/config.py's default MODEL_FILENAME -- "
              "no env var needed, just restart the server.")
    else:
        print(f"config.py auto-detects '{final_name}' in models/ for the conversion task -- "
              f"no INVARIANTSMITH_CONVERT_MODEL_FILE env var needed, just restart the server.")
