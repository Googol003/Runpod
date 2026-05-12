SYSTEM_PROMPT = """Du korrigierst eine Zeile **DIALOGUE** anhand der Referenz **MATCHED_TEXT** (gleiche Excel-Zeile). Arbeite **präzise**: nur das, was unten erlaubt ist — **keine** freien Worttausche und **kein** Auffüllen.

---

## 1) Eigennamen und Entitäten (höchste Priorität)

- **Personen-, Orts-, Marken- und Figurennamen:** Wenn MATCHED_TEXT dieselbe Person/Sache **eindeutig** mit **anderer Schreibung** führt (gleicher Kontext, gleiche Rolle im Satz, phonetische Nähe) → Schreibweise **exakt wie in MATCHED_TEXT**.
- **Sehr genau suchen:** auch in kurzen Zeilen, auch wenn sonst wenig Wortüberlappung — Namen nicht übersehen.
- **Nicht** als „Eigenname“ behandeln: normale **Sachwörter** und **Umschreibungen** (z. B. Kollektivbezeichnungen). **Kein** Tausch von einem **sinnvollen** Alltagswort gegen ein **anderes** sinnvolles Wort aus der Referenz — auch nicht mit der Begründung „Entität“ oder „Anpassung an MATCHED_TEXT“.

---

## 2) Erlaubt (nur diese Kategorie)

- **Offensichtliche** Tipp-, Schreib- und Hörfehler (inkl. klarer ASR-Müll / Pseudo-Wort), wenn **dasselbe Wort** gemeint ist und MATCHED_TEXT das **eindeutig** nahelegt.
- **Klar falsche Grammatik**, wenn eindeutig und ohne Wortwahl zu ändern.

---

## 3) Strikt verboten — Kontext, Auffüllen, Worttausch

**Kein Kontext-Auffüllen:** Kein Wort, kein Satzteil und kein Präfix/Suffix aus MATCHED_TEXT, das im **DIALOGUE nicht vorkommt**, darf eingefügt oder angehängt werden — **auch kein „einzelnes Random-Wort“** aus der Referenz.

**Kein Worttausch / keine Umformulierung:** Jedes Wort im DIALOGUE, das **bereits ein normales, sinnvolles deutsches Wort** ist (kein offensichtlicher Tippfehler, kein Name), bleibt — **niemals** durch ein **anderes** gültiges Wort aus MATCHED_TEXT ersetzen, nur weil die Referenz anders lautet.

**Explizit verbotenes Muster (NIEMALS so begründen):**
- `Mannschaft` → `Team` mit reason wie „Eigenname/Entität an MATCHED_TEXT“ — **falsch**. Das sind **zwei verschiedene normale Begriffe** / Umschreibungen, **kein** Schreibfehler eines Namens. **Keine** Korrektur.

Weitere Beispiele (alle **keine** Korrektur / `leave_unchanged=true`):
- DIALOGUE `Bitte.` — MATCHED_TEXT `Gib mir irgendwas Hartes, Olu. Bitte.` → **nicht** auffüllen.
- DIALOGUE `Wer Einwände gegen diese Verbindung hat, …` — MATCHED_TEXT `Wer etwas gegen diese Verbindung vorzubringen hat, …` → **kein** Satzumbau.
- DIALOGUE `… Umstrukturierungsphase.` — MATCHED_TEXT `… Wiederaufbauphase.` → **kein** Begriffstausch.

---

## 4) Pflicht-Selbsttest **vor jeder** geplanten Ersetzung (`from` → `to`)

Stell dir für **`from`** die Frage: „Ist das ein **offensichtlicher Schreib-/Hör-/Tippfehler** oder ein **Eigenname**, den MATCHED_TEXT **dieselbe Entität** schreibt?“  
- **Nein** (es ist einfach ein **anderes**, aber gültiges Wort / eine andere Formulierung) → **diese Ersetzung weglassen**; wenn danach nichts Erlaubtes übrig bleibt → ganze Zeile `leave_unchanged=true`.

Wenn du bei **irgendeiner** geplanten Änderung zweifelst → `leave_unchanged=true` für die Zeile.

---

**JSON:** `leave_unchanged=true` ⇒ `corrected_dialogue` wortgleich zum DIALOGUE, `corrections=[]`. Sonst `corrected_dialogue` korrigiert, `corrections` nur mit Einträgen, die den Selbsttest und alle Verbote passieren. Keine No-Ops.

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

Pflicht: `leave_unchanged=true` ⇒ `corrected_dialogue` = DIALOGUE wortgleich, `corrections=[]`. Keine No-Ops. **Vor jedem** `corrections`-Eintrag: Selbsttest (Systemanweisung Abschnitt 4) — `from` muss Tippfehler/Hörfehler oder **echter** Eigenname sein; **kein** sinnvolles Wort gegen anderes sinnvolles Wort (z. B. **niemals** Mannschaft→Team). Kein Auffüllen aus MATCHED_TEXT.

DIALOGUE:
{dialogue}

MATCHED_TEXT:
{matched_text}
"""


BATCH_USER_PROMPT_TEMPLATE = """Wende die **Systemanweisung** auf **alle** nummerierten DIALOGUE-Zeilen an.

**Vorgehen pro Zeile:** Zuerst **Eigennamen** in MATCHED_TEXT identifizieren und in der DIALOGUE-Zeile dieselbe Entität suchen → Schreibweise angleichen. Dann nur **offensichtliche** Schreib-/Hörfehler. **Vor jeder** Ersetzung Selbsttest (Abschnitt 4 der Systemanweisung). **Niemals** Kontext auffüllen; **niemals** Mannschaft↔Team o. Ä.; bei Zweifel `leave_unchanged=true`.

**Zuordnung:** Ein gemeinsamer **MATCHED_TEXT** gilt für **alle** nummerierten Zeilen (Excel: gleicher Inhalt in „Matched Text“, Reihenfolge wie in der Datei). Jede Zeile **einzeln** bewerten.

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
- Kein Einfügen von Text aus MATCHED_TEXT, der in dieser DIALOGUE-Zeile fehlt; kein Synonym-/Begriffs-/Satzumbau; **kein** Tausch sinnvoller Alltagswörter (z. B. Mannschaft/Team). Jede Korrektur muss den Selbsttest (Abschnitt 4) bestehen; sonst weglassen bzw. Zeile `leave_unchanged=true`.

MATCHED_TEXT (Referenz):
{matched_text}

DIALOGUE-LISTE (1..N):
{dialogue_list}
"""
