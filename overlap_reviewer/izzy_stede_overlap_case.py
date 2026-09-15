"""
Overlap-Review Testcase: Izzy / Stede / Blackbeard — starke Sprecherüberlappung.

Simuliert Post-Matcher-Zustand:
- Transkript-Zeilen mit zugewiesenem SOURCE + MATCHED-TEXT (teilweise falsch)
- Volles Original-Drehbuch
- NOT_MATCHED: Originalzeilen ohne Transkript-Match (typisch bei Überlappung)

Eingebaute Fehlerquellen (soll der Reviewer flaggen):
1) TEXT_LEAK — Worte des anderen Sprechers in der Transkript-Zeile
2) SPEAKER_WRONG — falsche Rolle nach Match
3) NONSENSE / starke Abweichung — Transkript passt nicht zum Script-Moment
4) Unmatched Original — Script-Zeile ohne Trans-Match (muss trotzdem sichtbar sein)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import pandas as pd


@dataclass(frozen=True)
class OverlapCase:
    """Post-Match Transkript + volles Original + unmatched Originalzeilen."""

    transcription: pd.DataFrame
    """Spalten: TIMECODE-IN, TIMECODE-OUT, DIALOGUE, SOURCE, MATCHED-TEXT"""

    original: pd.DataFrame
    """Spalten: timecode_in, timecode_out, source, dialogue — komplettes Drehbuch"""

    not_matched: pd.DataFrame
    """Spalten: timecode_in, timecode_out, source, dialogue — Original ohne Match"""


def build_case() -> OverlapCase:
    # --- Volles Original (Drehbuch), inkl. doppelter Cue-Zeilen wie im echten Izzy/Stede-Satz ---
    orig_rows = [
        ("00:00:27:01", "00:00:30:02", "STEDE", "Izzy, warte. Ich hab's dir nie zurückgezahlt."),
        ("00:00:30:02", "00:00:33:21", "IZZY", "Was hast du mir nie zurückgezahlt?"),
        ("00:00:33:12", "00:00:35:12", "STEDE", "Dass du uns an die Engländer verkauft hast."),
        ("00:00:40:21", "00:00:44:18", "IZZY", "Ich hab dich nie gezwungen, ihn zu verlassen. Das hast du von allein getan."),
        ("00:00:54:18", "00:00:59:22", "STEDE", "Wo ist er? Wo ist Ed?"),
        ("00:01:00:24", "00:01:11:14", "IZZY", "Du unglaublicher Kackvogel."),
        # Überlappungs-Block: Rufe Stede!/Ed! — Zeitfenster überlappen sich
        ("00:01:11:14", "00:01:14:00", "BLACKBEARD", "Stede!"),
        ("00:01:14:00", "00:01:16:10", "STEDE", "Ed!"),
        ("00:01:17:11", "00:01:19:09", "BLACKBEARD", "Stede!"),
        ("00:01:19:09", "00:01:23:13", "STEDE", "Ed!"),
        ("00:01:27:21", "00:01:37:01", "BLACKBEARD", "Stede! Stede!"),
        # Diese STEDE-Ed!-Zeile bleibt oft unmatched (kein Transkript-Cue in diesem Fenster)
        ("00:01:42:13", "00:01:49:06", "STEDE", "Ed!"),
        ("00:01:49:06", "00:01:51:15", "BLACKBEARD", "Ich wusste, du würdest mich finden."),
        ("00:01:51:14", "00:01:53:11", "STEDE", "Du bist nicht sauer?"),
        ("00:01:53:11", "00:01:55:19", "BLACKBEARD", "Liebster, ich hab es gewusst."),
        # Zusätzliches Überlappungs-Original: Izzy spricht noch, während Stede schon fragt (kein Trans-Match)
        ("00:00:54:10", "00:00:56:00", "IZZY", "(Text)"),
    ]
    original = pd.DataFrame(orig_rows, columns=["timecode_in", "timecode_out", "source", "dialogue"])

    # --- Transkript nach „Matching“: SOURCE + MATCHED-TEXT gesetzt, aber mit echten Fehlern ---
    # Format: tc_in, tc_out, dialogue, source, matched_text
    trans_rows = [
        # OK
        (
            "00:00:15:15",
            "00:00:28:06",
            "Izzy, warte.",
            "STEDE",
            "Izzy, warte. Ich hab's dir nie zurückgezahlt.",
        ),
        # OK
        (
            "00:00:28:21",
            "00:00:30:02",
            "Ich hab's dir nie zurückgezahlt.",
            "STEDE",
            "Izzy, warte. Ich hab's dir nie zurückgezahlt.",
        ),
        # OK
        (
            "00:00:30:05",
            "00:00:31:19",
            "Was hast du mir nie zurückgezahlt?",
            "IZZY",
            "Was hast du mir nie zurückgezahlt?",
        ),
        # TEXT_LEAK: Stede-Antwort + Anfang von Izzys nächster Zeile klebt am Transkript (Überlappung)
        (
            "00:00:33:18",
            "00:00:35:12",
            "Dass du uns an die Engländer verkauft hast. Ich hab dich nie gezwungen.",
            "STEDE",
            "Dass du uns an die Engländer verkauft hast.",
        ),
        # SPEAKER_WRONG: Text ist Izzy, aber Match hat STEDE gesetzt; Zeit überlappt mit Izzy-Block
        (
            "00:00:40:16",
            "00:00:42:10",
            "Ich hab dich nie gezwungen, ihn zu verlassen.",
            "STEDE",
            "Wo ist er? Wo ist Ed?",
        ),
        # OK (Rest von Izzy)
        (
            "00:00:43:04",
            "00:00:44:14",
            "Das hast du von allein getan.",
            "IZZY",
            "Ich hab dich nie gezwungen, ihn zu verlassen. Das hast du von allein getan.",
        ),
        # OK
        (
            "00:00:54:20",
            "00:00:55:17",
            "Wo ist er?",
            "STEDE",
            "Wo ist er? Wo ist Ed?",
        ),
        # TEXT_LEAK + Überlappung: Stede-Frage + Izzy-Beleidigung in einer Trans-Zeile
        (
            "00:00:56:08",
            "00:01:06:12",
            "Wo ist Ed? Du unglaubliche Muschi.",
            "STEDE",
            "Wo ist er? Wo ist Ed?",
        ),
        # NONSENSE / ASR vs Script: „Muschi“ statt „Kackvogel“ — und SPEAKER könnte noch Izzy sein (hier OK-Rolle)
        (
            "00:01:01:06",
            "00:01:06:12",
            "Du unglaubliche Muschi.",
            "IZZY",
            "Du unglaublicher Kackvogel.",
        ),
        # SPEAKER_WRONG: „Sid!“ = ASR für „Stede!“ → gehört BLACKBEARD, Match sagt fälschlich STEDE
        (
            "00:01:08:11",
            "00:01:11:17",
            "Sid!",
            "STEDE",
            "Ed!",
        ),
        # OK
        (
            "00:01:15:16",
            "00:01:16:00",
            "Ed!",
            "STEDE",
            "Ed!",
        ),
        # TEXT_LEAK in Überlappungsfenster: Blackbeard-Ruf + Stede-Antwort in einer Zeile
        (
            "00:01:17:17",
            "00:01:21:07",
            "Sid! Ed!",
            "BLACKBEARD",
            "Stede!",
        ),
        # SPEAKER_WRONG: Sid! → sollte BLACKBEARD / Stede! sein, hat STEDE
        (
            "00:01:28:05",
            "00:01:29:09",
            "Sid!",
            "STEDE",
            "Ed!",
        ),
        # OK-ish: zweites Sid → Blackbeard Stede!
        (
            "00:01:35:18",
            "00:01:36:24",
            "Sid!",
            "BLACKBEARD",
            "Stede! Stede!",
        ),
        # OK
        (
            "00:01:49:08",
            "00:01:50:20",
            "Ich wusste, du würdest mich finden.",
            "BLACKBEARD",
            "Ich wusste, du würdest mich finden.",
        ),
        # leichter ASR-Typo bleibt dem Word-Corrector; hier Rolle OK
        (
            "00:01:52:04",
            "00:01:53:04",
            "Du bist nicht Saur?",
            "STEDE",
            "Du bist nicht sauer?",
        ),
        # OK
        (
            "00:01:54:01",
            "00:01:55:10",
            "Liebster, ich hab es gewusst.",
            "BLACKBEARD",
            "Liebster, ich hab es gewusst.",
        ),
        # Unmatched Trans-Zeile (leerer SOURCE) — Überlappungsfetzen ohne Match
        (
            "00:01:42:20",
            "00:01:43:10",
            "Ed!",
            "",
            "",
        ),
    ]
    transcription = pd.DataFrame(
        trans_rows,
        columns=["TIMECODE-IN", "TIMECODE-OUT", "DIALOGUE", "SOURCE", "MATCHED-TEXT"],
    )

    # Originalzeilen, die im simulierten Match „übrig“ blieben
    not_matched_rows = [
        ("00:01:42:13", "00:01:49:06", "STEDE", "Ed!"),
        ("00:00:54:10", "00:00:56:00", "IZZY", "(Text)"),
        # Doppel-Cue aus Script, der nicht nochmal gematcht wurde
        ("00:01:27:21", "00:01:37:01", "BLACKBEARD", "Stede! Stede!"),
    ]
    not_matched = pd.DataFrame(
        not_matched_rows,
        columns=["timecode_in", "timecode_out", "source", "dialogue"],
    )

    return OverlapCase(
        transcription=transcription,
        original=original,
        not_matched=not_matched,
    )
