#!/usr/bin/env bash
# Fetch the Qwen2.5-Coder-1.5B-Instruct Q8_0 GGUF (~1.65GB) into models/.
#
# Run this on your own machine (not inside a network-restricted sandbox) --
# it needs access to huggingface.co.
#
# Swap REPO/FILE below if you later fine-tune your own checkpoint and want
# to pull that instead.

set -euo pipefail

REPO="Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF"
FILE="qwen2.5-coder-1.5b-instruct-q8_0.gguf"   # the real filename in this HF repo
# ...but unsloth's own GGUF export (data_pipeline/train_lora.py) names its
# output "qwen2.5-coder-1.5b-instruct.Q8_0.gguf" (dot, capital Q) -- and
# that's the convention server/config.py's MODEL_FILENAME default expects.
# Renaming locally after download means both this script and a from-scratch
# fine-tune land on the exact same filename, with no manual renaming and
# no env var required either way.
LOCAL_NAME="qwen2.5-coder-1.5b-instruct.Q8_0.gguf"
OUT_DIR="$(dirname "$0")/../models"

mkdir -p "$OUT_DIR"

echo "Downloading ${FILE} from ${REPO} ..."
URL="https://huggingface.co/${REPO}/resolve/main/${FILE}"

if command -v huggingface-cli >/dev/null 2>&1; then
    huggingface-cli download "$REPO" "$FILE" --local-dir "$OUT_DIR" --local-dir-use-symlinks False
else
    curl -L -o "${OUT_DIR}/${FILE}" "$URL"
fi

if [ "$FILE" != "$LOCAL_NAME" ]; then
    mv "${OUT_DIR}/${FILE}" "${OUT_DIR}/${LOCAL_NAME}"
fi

echo "Done. Model at ${OUT_DIR}/${LOCAL_NAME}"
echo "Expected size: ~1.65 GB (verify with: ls -lh ${OUT_DIR}/${LOCAL_NAME})"
