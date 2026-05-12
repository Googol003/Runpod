SYSTEM_PROMPT = """Du korrigierst eine Zeile **DIALOGUE** anhand der Referenz **MATCHED_TEXT** (gleiche Excel-Zeile).

**Arbeitsweise:** Geh den DIALOGUE **absichtlich gründlich** durch: Wort für Wort gegen die Referenz prüfen, wo ein Bezug erkennbar ist. Übersehe **keine** offensichtlichen Tippfehler, falsche Namensschreibweise oder sinnloses Pseudo-Wort, wenn MATCHED_TEXT an der passenden Stelle ein klares Zielwort nahelegt. `leave_unchanged` nur, wenn wirklich nichts **sicher** zu korrigieren ist oder die Regeln unten es verbieten.

**Erlaubt:** Offensichtliche Schreib- und Tippfehler, klar falsche Grammatik, Eigennamen/Entitäten an die Schreibweise in MATCHED_TEXT anpassen, wenn dieselbe Sache/Person gemeint ist.

**Strikt verboten / in Ruhe lassen (immer `leave_unchanged=true`, kein Satzbau aus der Referenz):**

- **Kein Kontext-Auffüllen:** Wörter, Halbsätze oder der ganze Anfang/Rest aus MATCHED_TEXT, die im **DIALOGUE nicht vorkamen**, **niemals** einfügen oder voranstellen — auch nicht, um die Referenz „vollständig“ nachzubauen.  
  *Beispiel:* DIALOGUE `Bitte.` — MATCHED_TEXT `Gib mir irgendwas Hartes, Olu. Bitte.` → Zeile bleibt `Bitte.` (höchstens minimale Schreibkorrektur an dem einen Wort), **nicht** zu `Gib mir irgendwas Hartes, Olu. Bitte.` erweitern.

- **Andere, aber gültige Formulierung:** Zwei unterschiedliche, jeweils **sinnvolle** deutsche Fassungen desselben Inhalts **nicht** an MATCHED_TEXT angleichen.  
  *Beispiel:* DIALOGUE `Wer Einwände gegen diese Verbindung hat, möge jetzt sprechen oder für immer schweigen.` — MATCHED_TEXT `Wer etwas gegen diese Verbindung vorzubringen hat, möge jetzt sprechen oder für immer schweigen.` → **keine** Korrektur (Synonym-/Satzumbau verboten).

- **Verschiedene Begriffe / andere Wortwahl:** Ein **gültiges** Wort im DIALOGUE **nicht** gegen ein **anderes** gültiges Wort aus MATCHED_TEXT tauschen, nur weil die Referenz anders lautet.  
  *Beispiel:* DIALOGUE `… in einer Umstrukturierungsphase.` — MATCHED_TEXT `… in einer Wiederaufbauphase.` → **Umstrukturierungsphase** bleibt; **nicht** zu Wiederaufbauphase ändern.

(Kurz: Nur echte Schreib-/Hör-/Tippfehler und Namen angleichen — **keine** inhaltliche oder stilistische Umschreibung Richtung Referenz.)

Wenn du unsicher bist, ob eine Änderung nur „Schreibung“ ist oder schon verbotener Umschreibung gleicht → `leave_unchanged=true`.

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

Pflicht: `leave_unchanged=true` ⇒ `corrected_dialogue` = DIALOGUE wortgleich, `corrections=[]`. Keine No-Ops. Kein Auffüllen aus MATCHED_TEXT; kein Synonym- oder Begriffstausch; kein Satzumbau Richtung Referenz (siehe Systemanweisung).

DIALOGUE:
{dialogue}

MATCHED_TEXT:
{matched_text}
"""


BATCH_USER_PROMPT_TEMPLATE = """Wende die **Systemanweisung** auf **alle** nummerierten DIALOGUE-Zeilen an.

**Zuordnung:** Ein gemeinsamer **MATCHED_TEXT** gilt für **alle** nummerierten Zeilen (Excel: gleicher Inhalt in „Matched Text“, Reihenfolge wie in der Datei). Jede Zeile **einzeln** bewerten — dieselben Verbote gelten für jede Zeile (kein Auffüllen, kein Synonym-/Begriffstausch, kein Satzumbau aus der Referenz).

**Vorgehen pro Zeile:** Nur offensichtliche Schreib-/Tippfehler, Grammatik, Namen — **niemals** fehlenden Text aus MATCHED_TEXT einfügen; **niemals** andere gültige Wörter oder Formulierungen nur wegen MATCHED_TEXT ändern (siehe Systemanweisung, Beispiele „Bitte.“, Einwände/vorzubringen, Umstrukturierungsphase/Wiederaufbauphase).

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
- Kein Einfügen von Text aus MATCHED_TEXT, der in dieser DIALOGUE-Zeile fehlt; kein Synonym-/Begriffs-/Satzumbau nur wegen MATCHED_TEXT (vgl. Systemanweisung: kurze vs. lange Referenz, paraphrase, Umstrukturierungsphase vs. Wiederaufbauphase).

MATCHED_TEXT (Referenz):
{matched_text}

DIALOGUE-LISTE (1..N):
{dialogue_list}
"""
