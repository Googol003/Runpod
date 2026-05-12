SYSTEM_PROMPT = """Du korrigierst eine Zeile **DIALOGUE** anhand der Referenz **MATCHED_TEXT** (gleiche Excel-Zeile).

**Arbeitsweise:** Geh den DIALOGUE **absichtlich gründlich** durch: Wort für Wort gegen die Referenz prüfen, wo ein Bezug erkennbar ist. Übersehe **keine** offensichtlichen Tippfehler, falsche Namensschreibweise oder sinnloses Pseudo-Wort, wenn MATCHED_TEXT an der passenden Stelle ein klares Zielwort nahelegt. `leave_unchanged` nur, wenn wirklich nichts **sicher** zu korrigieren ist oder die Regeln unten es verbieten.

**Erlaubt:** Offensichtliche Schreib- und Tippfehler, klar falsche Grammatik, Eigennamen/Entitäten an die Schreibweise in MATCHED_TEXT anpassen, wenn dieselbe Sache/Person gemeint ist.

**Strikt verboten:**
- **Keine Synonyme** und kein Tausch gegen **andere Wörter**, die im Satz **ebenfalls Sinn ergeben** würden — nur weil MATCHED_TEXT anders formuliert ist.
- **Kein Auffüllen:** Fehlende Wörter, Zusätze oder Satzteile aus MATCHED_TEXT **niemals** in den DIALOGUE einfügen, wenn sie dort nicht vorkamen (kein Kontext aus der Referenz nachbauen).

Wenn du unsicher bist oder eine Änderung eine andere sinnvolle Formulierung wäre → `leave_unchanged=true`.

**JSON:** `leave_unchanged=true` ⇒ `corrected_dialogue` wortgleich zum DIALOGUE, `corrections=[]`. Sonst `corrected_dialogue` korrigiert, `corrections` mit sinnvollen `from`/`to`/`reason`. Keine No-Ops.

Antworte nur mit gültigem JSON, ohne Markdown-Fences, ohne Text außerhalb des JSON.
"""


USER_PROMPT_TEMPLATE = """Wende die **Systemanweisung** an: ein DIALOGUE, ein MATCHED_TEXT — gleiche Zuordnung wie in der Excel-Zeile.

Antworte mit genau diesem JSON-Schema (kein anderer Text):
{{
  "leave_unchanged": true|false,
  "corrected_dialogue": "string",
  "corrections": [
    {{"from":"string","to":"string","reason":"string"}}
  ]
}}

Pflicht: `leave_unchanged=true` ⇒ `corrected_dialogue` = DIALOGUE wortgleich, `corrections=[]`. Keine No-Ops. Kein Synonymtausch; kein Nachliefern fehlender Wörter aus der Referenz.

DIALOGUE:
{dialogue}

MATCHED_TEXT:
{matched_text}
"""


BATCH_USER_PROMPT_TEMPLATE = """Wende die **Systemanweisung** auf **alle** nummerierten DIALOGUE-Zeilen an.

**Zuordnung:** Ein gemeinsamer **MATCHED_TEXT** gilt für **alle** nummerierten Zeilen (Excel: gleicher Inhalt in „Matched Text“, Reihenfolge wie in der Datei).

**Vorgehen pro Zeile:** Nur offensichtliche Fehler und Namen wie in der Systemanweisung — keine Synonyme, kein Auffüllen aus der Referenz.

Antworte **nur** mit gültigem JSON in genau diesem Schema:
{{
  "items": [
    {{
      "i": 1,
      "leave_unchanged": true|false,
      "corrected_dialogue": "string",
      "corrections": [{{"from":"string","to":"string","reason":"string"}}]
    }}
  ]
}}

Pflicht:
- Exakt **N** Einträge in `items`, für `i=1..N` (Reihenfolge wie die DIALOGUE-Liste).
- `leave_unchanged=true` ⇒ `corrected_dialogue` identisch zur jeweiligen DIALOGUE-Zeile, `corrections=[]`.
- Keine Korrekturen mit `from==to`.
- Keine Synonym-/Formulierungstausche nur wegen MATCHED_TEXT; kein Einfügen fehlender Wörter zur „Vollständigkeits-Reparatur“ der Referenz.

MATCHED_TEXT (Referenz):
{matched_text}

DIALOGUE-LISTE (1..N):
{dialogue_list}
"""
