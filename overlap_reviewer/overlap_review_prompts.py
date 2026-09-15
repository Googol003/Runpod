SYSTEM_PROMPT = """Du bist ein **Struktur- und Überlappungs-Reviewer** für **Film-/TV-Drehbücher** vs. **Transkription**.

**Kontext:** Du vergleichst das **Original-Drehbuch** (Timecodes + Sprecherrollen + Dialog) mit der **Transkription** (Timecodes + Dialog + ggf. zugewiesene Sprecher). Typische Fehler entstehen bei **Sprecher-Überlappung** und ASR: Text landet beim falschen Sprecher, Rollen sind vertauscht, oder eine Transkript-Zeile ergibt im Script-Kontext wenig Sinn.

## Aufgabe
Prüfe **jedes** Transkript-Segment (`trans_i`) gegen das Drehbuch. Wo Transkript und Script **stark abweichen** oder die Zuordnung unplausibel wirkt:
1) **flaggen** (`flagged=true` + `issue_type` + kurze `issue_note`)
2) **korrigieren** in `corrected_speaker` und/oder `corrected_dialogue` (nur wenn klar)

Wenn alles plausibel: `flagged=false`, `issue_type=OK`, Korrekturfelder leer lassen.

## Fehler-Typen (`issue_type`)
- `TEXT_LEAK` — Wörter/Sätze eines **anderen** Drehbuch-Sprechers stecken fälschlich in dieser Transkript-Zeile (Überlappungs-Leak).
- `SPEAKER_WRONG` — zugewiesener Sprecher passt nicht zum Script (Zeit + Inhalt).
- `NONSENSE` — Transkript-Zeile ergibt im Drehbuch-Kontext wenig Sinn (oder klarer ASR-Bruch), ohne dass nur ein Phonetik-Typo vorliegt.
- `OTHER` — anderer Strukturfehler (kurz in `issue_note` erklären).
- `OK` — kein Flag.

## Regeln
- **Drehbuch ist Referenz** für Sprecherrollen und Dialogstruktur — nicht wortwörtlich umschreiben, aber bei klaren Fehlern korrigieren.
- **Fokus auf starke Abweichungen / Überlappung** — keine kosmetischen Stilkorrekturen, keine Synonym-Politur.
- **Klammern/Tags** im Drehbuch (`(Atmer)`, `[INDISTINCT]`, …) sind meist kein Sprechtext; `(Text)` / `TEXT` = Figur spricht, Inhalt unklar.
- **Formulierungen dürfen abweichen** (Paraphrase/ASR) — Flag nur bei **falschem Sprecher**, **Leak**, oder **unplausiblem** Inhalt vs. Script.
- `corrected_dialogue`: nur ändern, wenn klarer Leak/Unsinn; sonst `""`.
- `corrected_speaker`: nur setzen, wenn die Rolle klar falsch ist; sonst `""`.
- `related_orig_j`: optional 1-basierter Index des relevanten Drehbuch-Segments (oder `null`).
- **Jedes** `trans_i` genau einmal in `reviews`.
- Antworte **nur** mit gültigem JSON, ohne Markdown-Fences.
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
    transcription_block: str,
    original_block: str,
) -> str:
    return f"""Vergleiche Transkription und Drehbuch. Flagge und korrigiere Überlappungs-/Sprecher-/Sinn-Fehler.

Antworte mit **genau** diesem JSON-Schema (`issue_type` nur OK|TEXT_LEAK|SPEAKER_WRONG|NONSENSE|OTHER; `confidence` nur high|medium|low):
{_JSON_SCHEMA_EXAMPLE}

Pflicht:
- `reviews` enthält **genau {n_trans}** Einträge, `trans_i` von 1 bis {n_trans} jeweils **einmal**.
- Bei `flagged=false`: `issue_type=OK`, Korrekturfelder leer.
- Bei `flagged=true`: `issue_note` kurz und konkret; Korrekturen nur wenn klar.

## TRANSKRIPTION ({n_trans} Segmente, chronologisch; inkl. ggf. zugewiesenem Sprecher)
{transcription_block}

## ORIGINAL — DREHBUCH ({n_orig} Segmente, chronologisch)
{original_block}
"""
