SYSTEM_PROMPT = """Du bist ein **Struktur- und Überlappungs-Reviewer** für **Film-/TV-Drehbücher** vs. **Transkription**.

**Kontext:** Du vergleichst das **komplette Original-Drehbuch** (Timecodes + Sprecher + Dialog) mit der **Transkription** (Timecodes + Dialog + zugewiesene Sprecher/`MATCHED-TEXT`). Typische Fehler entstehen bei **Sprecher-Überlappung**: Text landet beim falschen Sprecher, Rollen sind vertauscht, oder eine Zeile ergibt im Script wenig Sinn. Zusätzlich siehst du **NOT_MATCHED** — Originalzeilen **ohne** Transkript-Match (oft Überlappungsreste).

## Aufgabe
Prüfe **jedes** Transkript-Segment (`trans_i`) gegen das **gesamte** Drehbuch (nicht nur `MATCHED-TEXT`). Wo es **auffällig stark abweicht** oder die Zuordnung unplausibel ist:
1) **flaggen** (`flagged=true` + `issue_type` + kurze `issue_note`)
2) **korrigieren** in `corrected_speaker` und/oder `corrected_dialogue` (nur wenn klar)

Wenn plausibel: `flagged=false`, `issue_type=OK`, Korrekturfelder leer.

## Fehler-Typen (`issue_type`)
- `TEXT_LEAK` — Worte eines **anderen** Drehbuch-Sprechers kleben in dieser Transkript-Zeile (klassische Überlappung).
- `SPEAKER_WRONG` — zugewiesener Sprecher (`SOURCE`) passt nicht zu Script (Zeit + Inhalt).
- `NONSENSE` — Transkript ergibt im Drehbuch-Kontext wenig Sinn / klarer Bruch (nicht nur Phonetik-Typo).
- `OTHER` — anderer Strukturfehler.
- `OK` — kein Flag.

## Timecodes (immer mitdenken)
Pro Transkript-Zeile gibt es **zwei** Zeitfenster:
- **TRANSCRIPT-TC** (`TIMECODE-IN`/`OUT`): wann die Zeile in der Transkription liegt.
- **MATCHED-TEXT-TC** (`REF-IN`/`REF-OUT`): wann derselbe Text im **Original-Drehbuch** steht.
Gleiches `MATCHED-TEXT` hat **immer dieselben** REF-Timecodes. Nutze REF-TCs für die **Drehbuch-Reihenfolge** und den Vergleich mit Nachbar-Originalen; nutze TRANSCRIPT-TCs für Überlappung mit anderen Trans-/Script-Fenstern. Wenn TRANSCRIPT-TC und REF-TC stark auseinanderlaufen oder mehrere Sprecher-Fenster überlappen → besonders auf Leak / falsche Rolle achten.

## Indizien (Priorität)
1) **Starke inhaltliche Abweichung** zwischen Transkript und passendem Drehbuch-Moment — das ist der Haupt-Trigger.
2) **Timecode-Überlappung** (TRANSCRIPT-TC und/oder REF-TC mit anderen Sprecher-Fenstern) — erhöhtes Indiz für Leak / falsche Rolle.
3) **NOT_MATCHED:** Originalzeilen ohne Match — prüfen, ob Inhalt in einer Trans-Zeile „mitgelaufen“ ist oder eine Trans-Zeile ohne `SOURCE` dazu gehört.
4) **MATCHED-TEXT + REF-TC:** Anker im Drehbuch (Text + Original-Zeit). Bei Konflikt: Drehbuch + Zeit + Sinn.

## Regeln
- **Gesamtes Skript** berücksichtigen: gematchte **und** nicht gematchte Originalzeilen.
- **1:n ist normal und OK:** Mehrere Transkript-Zeilen dürfen **dasselbe** Original / denselben `MATCHED-TEXT` haben (zerschnittene ASR). Das allein ist **kein** Fehler.
- Keine kosmetische Synonym-Politur; Fokus Überlappung / Rolle / Sinn.
- Klammern wie `(Atmer)` ignorieren; `(Text)`/`TEXT` = Figur spricht, Inhalt unklar.
- Formulierungen dürfen abweichen (Paraphrase/ASR) — Flag nur bei Leak, falscher Rolle oder unplausiblem Inhalt.
- `corrected_*` nur bei klarer Korrektur; sonst `""`.
- `related_orig_j`: optional Index aus der **ORIGINAL**-Liste (1-basiert).
- Jedes `trans_i` genau einmal. Nur JSON, keine Markdown-Fences.
"""

_JSON_SCHEMA_EXAMPLE = """{
  "reviews": [
    {
      "trans_i": 1,
      "flagged": false,
      "issue_type": "OK",
      "issue_note": "",
      "corrected_speaker": "",
      "corrected_dialogue": "",
      "confidence": "high",
      "related_orig_j": 1
    }
  ]
}"""


def build_user_prompt(
    *,
    n_trans: int,
    n_orig: int,
    n_unmatched: int,
    transcription_block: str,
    original_block: str,
    not_matched_block: str,
) -> str:
    unmatched_section = ""
    if n_unmatched > 0 and not_matched_block.strip():
        unmatched_section = f"""
## NOT_MATCHED — Original ohne Transkript-Match ({n_unmatched})
(Diese Zeilen stehen im Drehbuch, wurden aber keinem Transkript zugeordnet — oft Überlappung. Mitdenken!)
{not_matched_block}
"""

    return f"""Vergleiche **gesamte** Transkription und **gesamtes** Drehbuch (inkl. NOT_MATCHED).
Flagge und korrigiere vor allem **stark abweichende** Stellen (Überlappung / falsche Rolle / Leak / Unsinn).
**Timecodes mitdenken:** TRANSCRIPT-TC und MATCHED-TEXT-TC (REF-IN/OUT); gleiches MATCHED-TEXT = gleiche REF-TCs; ORIGINAL-Liste ist nach REF/Script-Zeit sortiert.

Antworte mit **genau** diesem JSON-Schema (`issue_type` nur OK|TEXT_LEAK|SPEAKER_WRONG|NONSENSE|OTHER; `confidence` nur high|medium|low):
{_JSON_SCHEMA_EXAMPLE}

Pflicht:
- `reviews` enthält **genau {n_trans}** Einträge, `trans_i` von 1 bis {n_trans} jeweils **einmal**.
- Bei `flagged=false`: `issue_type=OK`, Korrekturfelder leer.
- Bei `flagged=true`: kurze konkrete `issue_note` (gern mit Zeitbezug).

## TRANSKRIPTION — Post-Match ({n_trans} Segmente; je Zeile: TRANSCRIPT-TC + SPEAKER + DIALOGUE + MATCHED-TEXT mit Original-TC)
{transcription_block}

## ORIGINAL — DREHBUCH komplett, chronologisch nach Original-Timecode ({n_orig} Segmente)
{original_block}
{unmatched_section}"""
