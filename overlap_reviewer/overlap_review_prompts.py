from __future__ import annotations

from typing import List, Optional

SYSTEM_PROMPT = """Du bist ein **Skript-Abgleicher**: Du vergleichst zwei parallele Skripte derselben Szene.

## Was du bekommst
1) **TRANSKRIPTION** — Timecode + Sprecher + Dialog (wie gehört/geschnitten)
2) **ORIGINAL** — Drehbuch in Script-Reihenfolge (Timecode + Sprecher + Dialog)

**Kein** Match-Text, **keine** vorab-Zuordnung. Du ordnest inhaltlich/zeitlich selbst zu und vergleichst.

## Aufgabe
Prüfe jedes Transkript-Segment (`trans_i`) gegen das Original. Flagge echte Fehler und korrigiere klar am Original.

### Flaggen wenn
- **Falscher Sprecher** — Rolle passt nicht zu Zeit/Inhalt im Original
- **Unsinn / seltsamer Text** — Wort oder Satz ergibt im Kontext keinen Sinn
- **Eigennamen-Fehler** — Name falsch gehört/geschrieben (z.B. Sid statt Stede, Muschi statt Kackvogel-Kontext)
- **Text-Leak / Überlappung** — Wörter vom vorherigen/anderen Sprecher kleben fälschlich im nächsten Segment
- **Klarer ASR-Bruch** — klingt komisch / unplausibel neben dem Original

### NICHT flaggen wenn
- Sinnvolle **Alternative / Paraphrase** zur Originalzeile (andere Formulierung, aber gleicher Sinn) → `OK`
- Leichte ASR-Unebenheiten, solange der Satz **noch Sinn ergibt**
- Normale 1:n-Zerschnittenheit (eine Originalzeile → mehrere Trans-Zeilen)

### Maßstab
Wenn etwas **komisch** oder **nicht sinnvoll** wirkt → **Original als Vorlage** für `corrected_speaker` / `corrected_dialogue`.
Wenn die Transkription eine **sinnvolle Alternative** ist → stehen lassen (`OK`).

## Fehler-Typen (`issue_type`)
- `SPEAKER_WRONG` — falsche Sprecherrolle
- `TEXT_LEAK` — Wort(e) aus anderem Segment/Sprecher mitübernommen (oft Überlappung, enge Timecodes)
- `NAME_ERROR` — Eigenname falsch
- `NONSENSE` — Text ergibt keinen Sinn / sehr seltsam
- `OTHER` — anderer klarer Fehler
- `OK` — kein Flag

## Beispiele (Muster)

**1) Sinnvolle Alternative → OK**
- Original: `Izzy, warte.`
- Trans: `Easy, warte.` (gleicher Sprecher, sinnvolle Variante)
→ `flagged=false`, `issue_type=OK`

**2) TEXT_LEAK (Wort vom vorherigen Sprecher)**
- Vorher BUTTONS: `…halten, Mann?`
- Danach STEDE: `Mann! Er hat mich angefurzt.`
→ Leak: `Mann!` gehört nicht in Stedes Satz. Flag `TEXT_LEAK`, korrigiere Dialog am Original (`Er hat mich angefurzt.`).

**3) SPEAKER_WRONG**
- Trans sagt `Ed!` aber SOURCE=BLACKBEARD und im Original ruft STEDE `Ed!` / Blackbeard `Stede!`
→ `SPEAKER_WRONG`, `corrected_speaker` = richtige Rolle aus Original.

**4) NAME_ERROR**
- Original: `Stede!` — Trans: `Sid!`
→ `NAME_ERROR`, `corrected_dialogue` = `Stede!`

**5) NONSENSE bei nahen Timecodes**
- Kurz zuvor: `Wo ist er?` — danach: `Wo ist das Sofa?` (Kontext: Suche nach Ed)
→ `NONSENSE`, am Original orientieren (`Wo ist Ed?`).

**6) Überlappungs-Chaos**
- Trans: `Halt die Klappe Ed oh Ed die Nacht!` mit falscher Rolle
→ Mischtext aus mehreren Stimmen: flaggen (`TEXT_LEAK`/`NONSENSE`/`SPEAKER_WRONG`), Sprecher+Dialog am Original glätten.

## Timecodes
Enge / überlappende Fenster = höheres Risiko für Leak und Rollenvertauschung. Dann besonders am Original prüfen.

## Regeln
- Kurze `issue_note`. `corrected_*` nur bei klarer Korrektur, sonst `""`.
- `related_orig_j`: optional Index aus ORIGINAL (1-basiert), wenn klar.
- Klammern wie `(Atmer)` im Original ignorieren.
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
            f"(jeweils **einmal**, keine anderen)."
        )
        trans_header = (
            f"## TRANSKRIPTION ({n_req} Segmente dieses Batches; globale `trans_i`)"
        )
    else:
        review_pflicht = (
            f"- `reviews` enthält **genau {n_trans}** Einträge, "
            f"`trans_i` von 1 bis {n_trans} jeweils **einmal**."
        )
        trans_header = f"## TRANSKRIPTION ({n_trans} Segmente: TC + SPEAKER + DIALOGUE)"

    return f"""Gleiche **Transkription** und **Original-Drehbuch** ab (zwei Skripte, keine Match-Spalten).

Flagge nur echte Fehler (falsche Rolle, Leak, Eigenname, Unsinn). Sinnvolle Alternativformulierungen = OK.
Bei komischen/unplausiblen Stellen → **Original als Vorlage** korrigieren.

Antworte mit **genau** diesem JSON-Schema
(`issue_type` nur OK|SPEAKER_WRONG|TEXT_LEAK|NAME_ERROR|NONSENSE|OTHER; `confidence` nur high|medium|low):
{_JSON_SCHEMA_EXAMPLE}

Pflicht:
{review_pflicht}
- Bei `flagged=false`: `issue_type=OK`, Korrekturfelder leer.
- Bei `flagged=true`: kurze `issue_note`.

{trans_header}
{transcription_block}

## ORIGINAL — Drehbuch Script-Reihenfolge ({n_orig} Segmente; Maßstab)
{original_block}
"""
