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

## 3) Strikt verboten — Kontext, Auffüllen, Kürzen, Worttausch, Anrede

**Kein Kontext-Auffüllen:** Kein Wort, kein Satzteil und kein Präfix/Suffix aus MATCHED_TEXT, das im **DIALOGUE nicht vorkommt**, darf eingefügt oder angehängt werden — **auch kein „einzelnes Random-Wort“** aus der Referenz. **NIEMALS** den DIALOGUE durch Anhängen von Referenztext zu einer „vollständigen“ Referenz-Äußerung erweitern.

**Kein Kürzen / kein „Aufräumen“ Richtung Referenz:** Wenn der DIALOGUE **mehr oder andere** (gültige) Wörter enthält als MATCHED_TEXT, bleiben sie — **kein** Streichen, **kein** Ersetzen des ganzen Satzes durch die kürzere Referenzform, **keine** „Korrektur unvollständiger Formulierung“ durch MATCHED_TEXT.

**Kein Worttausch / keine Umformulierung:** Jedes Wort im DIALOGUE, das **bereits ein normales, sinnvolles deutsches Wort** ist (kein offensichtlicher Tippfehler, kein Name), bleibt — **niemals** durch ein **anderes** gültiges Wort aus MATCHED_TEXT ersetzen, nur weil die Referenz anders lautet.

**Keine Anrede- oder Grammatik-Umstellung** an MATCHED_TEXT: **Niemals** `Du`↔`Sie`, `hast`↔`haben`, Plural/Singular usw. „angleichen“ — das ist **kein** Rechtschreibfix, sondern **Satzumbau**.

**Beleidigungs- und Stilvarianten:** Zwei **jeweils gültige** Varianten (z. B. `scheiß` / `verfluchte` im gleichen Muster „… Teufel“) **nicht** gegeneinander tauschen — **kein** Adjektivtausch mit Begründung „korrekte Bezeichnung laut Referenz“.

**Explizit verbotenes Muster (NIEMALS so begründen):**
- `Mannschaft` → `Team` mit reason wie „Eigenname/Entität an MATCHED_TEXT“ — **falsch**. Das sind **zwei verschiedene normale Begriffe**, **kein** Schreibfehler eines Namens.

---

### Konkrete Verbotsfälle (exakt diese Logik verbieten — `leave_unchanged=true`)

1. **Auffüllen:** DIALOGUE `Bitte.` — MATCHED_TEXT `Gib mir irgendwas Hartes, Olu. Bitte.`  
   **Verboten:** `from`=`Bitte.` → `to`=`Gib mir irgendwas Hartes, Olu. Bitte.` (oder ähnlich) mit reason wie „Ergänzung aus Referenz / unvollständige Formulierung“. **Nur** `Bitte.` stehen lassen.

2. **Beleidigungsvariante:** DIALOGUE `Ich bin der scheiß Teufel.` — MATCHED_TEXT `… Ich bin der verfluchte Teufel.`  
   **Verboten:** `scheiß` → `verfluchte` (oder umgekehrt) — beides sind **idiomatisch mögliche** Varianten, **kein** Rechtschreibfix.

3. **Anrede an Referenz:** DIALOGUE z. B. `Du hast …` — MATCHED_TEXT mit `Sie haben …`  
   **Verboten:** `Du`→`Sie`, `hast`→`haben` (oder mehrere solche Paare) wegen „Anpassung an MATCHED_TEXT“.

4. **Kürzen auf Referenz:** DIALOGUE `Los, ist okay.` — MATCHED_TEXT `Los!`  
   **Verboten:** ganzer Satz → `Los!` oder Streichen von `ist okay` mit reason wie „Zusatzwörter unnötig / Referenz nahelegt Los!“. Der DIALOGUE bleibt inhaltlich wie gesprochen.

Weitere Beispiele (ebenfalls **keine** Korrektur):
- DIALOGUE `Wer Einwände gegen diese Verbindung hat, …` — MATCHED_TEXT `Wer etwas gegen … vorzubringen hat, …` → **kein** Satzumbau.
- DIALOGUE `… Umstrukturierungsphase.` — MATCHED_TEXT `… Wiederaufbauphase.` → **kein** Begriffstausch.

**Wenn eine Korrektur wie eines der obigen Fälle aussähe → keine `corrections`, `leave_unchanged=true`.**

## 4) Pflicht-Selbsttest **vor jeder** geplanten Ersetzung (`from` → `to`)

Stell dir für **`from`** die Frage: „Ist das ein **offensichtlicher Schreib-/Hör-/Tippfehler** oder ein **Eigenname**, den MATCHED_TEXT **dieselbe Entität** schreibt?“  
- **Nein** (es ist einfach ein **anderes**, aber gültiges Wort / eine andere Formulierung) → **diese Ersetzung weglassen**; wenn danach nichts Erlaubtes übrig bleibt → ganze Zeile `leave_unchanged=true`.

Wenn du bei **irgendeiner** geplanten Änderung zweifelst → `leave_unchanged=true` für die Zeile.

Gleicht die geplante Korrektur einem der **Konkreten Verbotsfälle** in Abschnitt 3 (Auffüllen, Beleidigungsvariante, Du/Sie, Kürzen auf Referenz, …) → **sofort** `leave_unchanged=true`, **keine** `corrections`.

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

Pflicht: `leave_unchanged=true` ⇒ `corrected_dialogue` = DIALOGUE wortgleich, `corrections=[]`. Keine No-Ops. **Vor jedem** `corrections`-Eintrag: Selbsttest (Abschnitt 4). **Verboten u. a.:** Auffüllen (z. B. nur `Bitte.` → ganzer Referenzsatz); scheiß/verflucht tauschen; Du/Sie oder Verb an Referenz; DIALOGUE kürzen (`Los, ist okay.` → `Los!`); Mannschaft→Team. Siehe Systemanweisung Abschnitt 3, Konkrete Verbotsfälle.

DIALOGUE:
{dialogue}

MATCHED_TEXT:
{matched_text}
"""


BATCH_USER_PROMPT_TEMPLATE = """Wende die **Systemanweisung** auf **alle** nummerierten DIALOGUE-Zeilen an.

**Vorgehen pro Zeile:** Zuerst **Eigennamen** (nur echte Namen). Dann nur **offensichtliche** Schreib-/Hörfehler. Selbsttest Abschnitt 4. **Niemals:** Kontext auffüllen; kürzen/streichen Richtung Referenz; Du/Sie; Beleidigungsvarianten tauschen; Mannschaft/Team; die in der Systemanweisung Abschnitt 3 genannten **Konkreten Verbotsfälle** (Bitte.; scheiß/verflucht; Los ist okay.; …).

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
- Kein Einfügen aus MATCHED_TEXT; kein Kürzen/Streichen gültiger DIALOGUE-Wörter nur wegen Referenz; kein Du/Sie/Verb-Tausch; keine Beleidigungsvarianten (scheiß/verflucht); kein Mannschaft/Team; keine Korrektur, die den **Konkreten Verbotsfällen** in Abschnitt 3 der Systemanweisung entspricht. Selbsttest Abschnitt 4; sonst `leave_unchanged=true`.

MATCHED_TEXT (Referenz):
{matched_text}

DIALOGUE-LISTE (1..N):
{dialogue_list}
"""
