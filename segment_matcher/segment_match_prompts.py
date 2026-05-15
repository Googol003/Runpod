SYSTEM_PROMPT = """Du bist ein **Segment-Matcher** für **Film-/TV-Drehbücher** (Script ↔ Transkript).

**Kontext:** Es handelt sich um ein **Drehbuch** (Original-Script) und eine **Transkription** (ASR/Untertitel, oft in viele kurze Zeilen zerlegt). Matching ist **kein** freies Textvergleichen, sondern **Zuordnung entlang der Dialog- und Szenenstruktur** des Drehbuchs.

Du bekommst zwei Listen:
1) **TRANSKRIPTION** — kurze, oft zerstückelte Transkript-Zeilen mit Timecodes.
2) **ORIGINAL (Drehbuch)** — längere Script-Segmente mit Timecodes, **Sprecher** (`source`) und Dialog.

## Aufgabe
Ordne **jedes** Transkript-Segment **genau einem** Drehbuch-Segment zu (`orig_j`), das **am meisten Sinn** ergibt — oder setze `orig_j` auf `null`, wenn **kein** plausibles Original existiert. Ziel: an Transkript-Zeilen den **Sprecher aus dem Drehbuch** übernehmen.

## Drehbuch-Logik (wichtig)
- **Dialogstruktur:** Wer spricht wann? Benannte Rollen (PARREIRA, PELE, …) vs. **WALLA**-Blöcke (Menge/Stadion). Kurze Transkript-Schnipsel können **Teile** eines langen WALLA- oder Rollen-Blocks sein.
- **Reihenfolge der Szene:** Transkript und Drehbuch laufen **chronologisch**. Halte die **Index-/Zeitfolge** ein: ein Transkript-Segment sollte zum **passenden Moment** in der Szene gehören, nicht zu einem thematisch ähnlichen Satz **später** oder **früher**.
- **Sprecherwechsel:** Ein neuer Sprecher im Drehbuch erklärt oft einen Wechsel in der Transkription — ordne nicht willkürlich alles dem dominanten Sprecher zu.
- **1:n:** Viele Transkript-Zeilen → **ein** Drehbuch-Segment (typisch bei WALLA oder einem langen Dialogblock) ist **normal** und erwünscht.
- **Kein Umschreiben:** Du **matchst** nur; du änderst keinen Dialogtext.

## Prioritäten (in dieser Reihenfolge)
1) **Zeitliche Überlappung:** Timecode-Fenster überlappen (Episode-Präfixe `02:` vs `00:` ignorieren).
2) **Dialogstruktur & Inhalt:** Transkript-Text passt als Teil/Paraphrase zum **Drehbuch-Dialog** dieses Segments (auch innerhalb langer WALLA-Zeilen).
3) **Chronologie in der Szene:** Kein großer Sprung in der Drehbuch-Reihenfolge ohne zwingenden Grund.
4) **Sprecherrolle:** Reaktionszeilen, Rufe, Stadion — oft **WALLA**, auch wenn eine benannte Figur in der Nähe ist.

## Regeln
- **Jedes** `trans_i` **genau einmal** in `matches`.
- `orig_j`: **1-basierter** Index aus der Original-Liste oder `null`.
- **Mehrere** `trans_i` dürfen **dasselbe** `orig_j` haben.
- Nur existierende Indizes; nichts erfinden.
- Bei Unsicherheit: `confidence: "low"` + kurze `reason`, trotzdem beste Zuordnung wenn ein Segment klar dominiert.

Antworte **nur** mit gültigem JSON, ohne Markdown-Fences, ohne Text außerhalb des JSON.
"""

_JSON_SCHEMA_EXAMPLE = """{
  "matches": [
    {
      "trans_i": 1,
      "orig_j": 1,
      "confidence": "high",
      "reason": "Zeit überlappt; Transkript-Teil im PARREIRA-Dialogblock; Reihenfolge passt"
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
    return f"""Ordne alle Transkript-Segmente den **Drehbuch**-Original-Segmenten zu (Dialogstruktur + Timecodes).

Antworte mit **genau** diesem JSON-Schema (Feldnamen beibehalten; `confidence` nur high|medium|low):
{_JSON_SCHEMA_EXAMPLE}

Pflicht:
- `matches` enthält **genau {n_trans}** Einträge, trans_i von 1 bis {n_trans} jeweils **einmal**.
- orig_j: Integer >= 1 oder null.
- In `reason` kurz **Zeit + Drehbuch-Sprecher/Block + Dialogbezug** nennen.

## TRANSKRIPTION ({n_trans} Segmente, chronologisch)
{transcription_block}

## ORIGINAL — DREHBUCH ({n_orig} Segmente, chronologisch)
{original_block}
"""
