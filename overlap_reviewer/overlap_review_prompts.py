from __future__ import annotations

from typing import List, Optional

SYSTEM_PROMPT = """Du bist ein **präziser Skript-Abgleicher** für Film-/TV.

Zwei Skripte:
1) **TRANSKRIPTION** — Timecode + Sprecher + Dialog
2) **ORIGINAL** — Drehbuch Script-Reihenfolge (Timecode + Sprecher + Dialog)

Kein Match-Text. Zuordnung über Zeit + Inhalt + Nachbarn.

## Wonach du suchst (Kern)
Nur Dinge, die im Vergleich zum Original **keinen Sinn** ergeben, **falsch geschrieben/gehört** sind, oder **strukturell falsch** sind:
- Wörter/Sätze die **unsinnig** oder **sehr seltsam** wirken (`dich du` statt `nicht du`, `Sofa` statt `Ed`, …)
- **Falsche Schreibweise / ASR-Verhörer** von inhaltlich klaren Wörtern oder Namen (`Sid` statt `Stede`)
- **TEXT_LEAK** — Wort vom anderen/vorherigen Segment klebt fälschlich dran
- **SPEAKER_WRONG** — Rolle passt nicht

**Nicht** ersetzen: sinnvolle **Alternativformulierungen** / Synonyme mit gleichem Sinn
(`setz dich` vs `Nimm Platz`, `Easy, warte.` vs `Izzy, warte.`) → `OK`, Dialog lassen.

## Arbeitsweise
Für jedes `trans_i`:
1. Passende Originalzeile(n) finden (Zeit + Inhalt).
2. Sprecher prüfen.
3. Wort für Wort: Unsinn? Falsch gehört/geschrieben? Leak am Rand?
4. Bei Unsinn/Falschschreibung/Leak/falscher Rolle → flaggen und **minimal** korrigieren (nur den Fehler).

Sei gründlich bei **kleinen** Sinn-/Schreibfehlern. Kurze Cues nicht überspringen.

## issue_type
- `NONSENSE` — Unsinn / unplausibel im Kontext
- `NAME_ERROR` — Eigenname falsch
- `TEXT_LEAK` — fremdes Wort mitübernommen
- `SPEAKER_WRONG` — falsche Rolle
- `OTHER` — anderer klarer Fehler
- `OK` — sinnvoll (auch als Alternative)

## Beispiele
- `dich du` vs Orig `nicht du` → flaggen, korrigieren zu `nicht du` (kein Sinn / falsch)
- `Sid!` vs `Stede!` → `NAME_ERROR`
- `Mann! Er hat…` nach Buttons `…Mann?` → `TEXT_LEAK`, `Mann!` weg
- `setz dich` vs Orig `Nimm Platz` → **OK**, nicht ändern
- `Easy, warte.` vs `Izzy, warte.` → **OK**

## Korrektur
- `corrected_*` nur den konkreten Fehler in **dieser** Zeile.
- Keine kosmetische Synonym-Politur.
- Kurze `issue_note`. `related_orig_j` optional.
- Nur JSON, keine Markdown-Fences.
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
    n_unmatched: int = 0,
    transcription_block: str,
    original_block: str,
    not_matched_block: str = "",
    required_trans_ids: Optional[List[int]] = None,
) -> str:
    if required_trans_ids:
        ids = ", ".join(str(i) for i in required_trans_ids)
        n_req = len(required_trans_ids)
        review_pflicht = (
            f"- `reviews` enthält **genau {n_req}** Einträge — nur diese `trans_i`: {ids} "
            f"(jeweils **einmal**). Zeilen mit Markierung KONTEXT nicht reviewen."
        )
        trans_header = (
            f"## TRANSKRIPTION (Batch: {n_req} zu reviewen; ggf. KONTEXT-Nachbarn)"
        )
    else:
        review_pflicht = (
            f"- `reviews` enthält **genau {n_trans}** Einträge, "
            f"`trans_i` von 1 bis {n_trans} jeweils **einmal**."
        )
        trans_header = f"## TRANSKRIPTION ({n_trans} Segmente: TC + SPEAKER + DIALOGUE)"

    return f"""Abgleich Transkription ↔ Original.

Flagge **Unsinn, falsche Schreibweise/Verhörer, Leaks, falsche Rollen** — auch kleine.
**Nicht** sinnvolle Alternativformulierungen ersetzen (`setz dich` vs `Nimm Platz` = OK).
Korrigiere nur den Fehler in der jeweiligen Zeile.

Antworte mit **genau** diesem JSON-Schema
(`issue_type` nur OK|SPEAKER_WRONG|TEXT_LEAK|NAME_ERROR|NONSENSE|OTHER; `confidence` nur high|medium|low):
{_JSON_SCHEMA_EXAMPLE}

Pflicht:
{review_pflicht}
- Bei `flagged=false`: `issue_type=OK`, Korrekturfelder leer.
- Bei `flagged=true`: kurze `issue_note` (falsches Wort/Rolle nennen).

{trans_header}
{transcription_block}

## ORIGINAL — Drehbuch Script-Reihenfolge ({n_orig} Segmente; Maßstab)
{original_block}
"""
