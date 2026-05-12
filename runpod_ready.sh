#!/usr/bin/env bash
set -euo pipefail

# RunPod quickstart for: Ollama @ 127.0.0.1:11434 with Qwen 3.5 9B
#
# Usage:
#   bash runpod_ready.sh "/workspace/input.xlsx"
#
# Optional:
#   LLM_MODEL=qwen3.5:9b bash runpod_ready.sh "/workspace/input.xlsx"

INPUT_XLSX="${1:-}"
if [[ -z "${INPUT_XLSX}" ]]; then
  echo "ERROR: please pass input xlsx path."
  echo "Example: bash runpod_ready.sh \"/workspace/input.xlsx\""
  exit 2
fi

python -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

export LLM_PROVIDER="${LLM_PROVIDER:-ollama}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
export LLM_MODEL="${LLM_MODEL:-qwen3.5:9b}"

echo "Pulling model: ${LLM_MODEL}"
ollama pull "${LLM_MODEL}"

echo "Running correction..."
python correct_excel.py --input "${INPUT_XLSX}"

