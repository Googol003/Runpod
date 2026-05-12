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

# Immer im Repo-Verzeichnis arbeiten (auch bei: bash /pfad/runpod_ready.sh …)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"
ts() { date +"%Y-%m-%d %H:%M:%S"; }
log() { echo "[$(ts)] $*"; }

log "cwd=${SCRIPT_DIR}"
if [[ ! -f "${INPUT_XLSX}" ]]; then
  echo "ERROR: Input-Datei nicht gefunden: ${INPUT_XLSX}"
  exit 2
fi
if [[ ! -f "requirements.txt" ]] || [[ ! -f "correct_excel.py" ]]; then
  echo "ERROR: requirements.txt oder correct_excel.py fehlt in ${SCRIPT_DIR}"
  exit 2
fi

if [[ -d ".venv" ]]; then
  log "Reusing existing venv: .venv"
else
  log "Creating venv: .venv"
  python -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

log "Python: $(python --version 2>/dev/null || true)"

# Install deps only if requirements changed (fast repeat runs)
REQ_HASH_FILE=".deps.sha256"
NEW_HASH="$(python - <<'PY'
import hashlib
from pathlib import Path
p = Path("requirements.txt")
h = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""
print(h)
PY
)"
OLD_HASH=""
if [[ -f "${REQ_HASH_FILE}" ]]; then
  OLD_HASH="$(cat "${REQ_HASH_FILE}" || true)"
fi
if [[ "${NEW_HASH}" != "${OLD_HASH}" ]]; then
  log "Installing/updating dependencies (requirements.txt changed)"
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  echo "${NEW_HASH}" > "${REQ_HASH_FILE}"
else
  log "Dependencies unchanged; skipping pip install"
fi

export LLM_PROVIDER="${LLM_PROVIDER:-ollama}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
export LLM_MODEL="${LLM_MODEL:-qwen3.5:9b}"

log "LLM_PROVIDER=${LLM_PROVIDER}"
log "OLLAMA_BASE_URL=${OLLAMA_BASE_URL}"
log "LLM_MODEL=${LLM_MODEL}"

log "Checking Ollama server..."
if ! curl -fsS --max-time 15 --connect-timeout 5 "${OLLAMA_BASE_URL}/api/tags" >/dev/null; then
  log "ERROR: could not reach Ollama at ${OLLAMA_BASE_URL}"
  log "Start it in another terminal with: ollama serve"
  exit 3
fi

log "Ensuring model is available (pull only if missing): ${LLM_MODEL}"
if ollama list 2>/dev/null | awk '{print $1}' | grep -qx "${LLM_MODEL}"; then
  log "Model already present: ${LLM_MODEL}"
else
  log "Pulling model: ${LLM_MODEL}"
  ollama pull "${LLM_MODEL}"
fi

log "Running correction..."
python correct_excel.py --input "${INPUT_XLSX}"

log "Done."

