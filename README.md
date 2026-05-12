## RunPod Excel Dialogue-Korrektur (Ollama oder LM Studio)

Dieses Mini-Setup liest eine Excel mit zwei Spalten ein:
- `Dialogue`
- `Matched Text`

und schreibt eine neue Excel mit:
- `Corrected Dialogue` (nur sehr sichere Korrekturen)
- `Corrections` (JSON-Liste der Änderungen)

Wichtig: Wenn `Dialogue` und `Matched Text` offensichtlich nicht zusammenpassen, wird **nichts geändert**.
Zusätzlich werden Eigennamen/Begriffe bevorzugt in der Schreibweise aus `Matched Text` korrigiert (nur bei hoher Sicherheit).

### 1) Installation (RunPod / Linux)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2A) Variante: Ollama auf der GPU (RunPod)

Auf RunPod ist es am einfachsten, ein Pod-Template zu nutzen, das Ollama bereits mitbringt.  
Falls du Ollama selbst installieren willst:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve
```

In einem zweiten Terminal:

```bash
ollama pull qwen3.5:9b
```

Environment:

```bash
export LLM_PROVIDER=ollama
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export LLM_MODEL=qwen3.5:9b
```

### 2B) Variante: LM Studio (OpenAI-compatible)

LM Studio Server (OpenAI-compatible) starten und auf RunPod erreichbar machen (typisch `:1234`).

```bash
export LLM_PROVIDER=openai_compat
export OPENAI_BASE_URL=http://127.0.0.1:1234/v1
export LLM_MODEL=local-model
```

### 3) Ausführen

```bash
python correct_excel.py --input "/path/to/input.xlsx"
```

Optional:

```bash
python correct_excel.py \
  --input "/path/to/input.xlsx" \
  --dialogue-col "Dialogue" \
  --matched-col "Matched Text" \
  --related-filter \
  --min-token-sim 0.12 \
  --workers 1 \
  --num-ctx 8192 \
  --num-predict 1024 \
  --decision-col "Decision" \
  --llm-item-col "LLM Item" \
  --min-confidence medium \
  --log-every 25
```

Ohne `--related-filter` werden **alle** Zeilen an den LLM geschickt (Standard). Mit `--related-filter` werden offenbar nicht passende Zeilen vorher übersprungen (`Decision`: `unrelated`); `--min-token-sim` wirkt nur damit. Zusätzlich kann mit `--related-filter` eine Referenz-Überlappungsprüfung greifen, **wenn** `--postcheck` aktiv ist.

**Post-Check (`safe_to_apply`):** Standard **aus** — LLM-Ausgabe wird bei passender Confidence direkt übernommen. Mit **`--postcheck`** werden heuristische Sperren (u. a. gegen Synonyme, Worteinfügungen) wieder angewendet; `Decision` kann dann `postcheck:…` sein.

