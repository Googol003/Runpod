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
ollama pull gemma4:26b
```

Environment:

```bash
export LLM_PROVIDER=ollama
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export LLM_MODEL=gemma4:26b
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
python correct_excel.py --input "/path/to/input.xlsx" --row-mode single
```

`--row-mode single`: **eine Excel-Zeile = ein LLM-Request** (kein Gruppen-Batch). Oft gründlicher, aber viel langsamer und mehr API-Last. Standard: `--row-mode batch` (alle Zeilen mit gleichem „Matched Text“ in einem Call).

Optional:

```bash
python correct_excel.py \
  --input "/path/to/input.xlsx" \
  --dialogue-col "Dialogue" \
  --matched-col "Matched Text" \
  --workers 1 \
  --num-ctx 8192 \
  --num-predict 1024 \
  --decision-col "Decision" \
  --llm-item-col "LLM Item" \
  --log-every 25 \
  --resource-log progress
```

Alle Zeilen mit gleichem **Matched Text** werden bei **`--row-mode batch`** (Standard) gebündelt an den LLM geschickt; die Ausgabe wird übernommen, solange das Modell nicht `leave_unchanged` setzt (kein technischer Post-Check, kein Related-Filter im Skript). Bei **`--row-mode single`** ist jede Zeile ein eigener Request. Optional: `--resource-log all` für Zeit-/Ressourcenzeilen pro Batch bzw. pro Zeile (single).

**Fortschritt (`[PROGRESS]` / `[DONE]`):** `applied` = Zeilen mit geändertem Text. `unchanged` = Modell hat `leave_unchanged` gesetzt. `errors` = LLM-Fehler, fehlende Batch-Zeile (`llm_missing_item`) oder falsches JSON-Format im Einzelmodus (`llm_bad_shape`).
