"""Regression case: chaotisches WM-Drehbuch vs. zerstückeltes Transkript (Parreira-Szene)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import pandas as pd


@dataclass(frozen=True)
class ChaosCase:
    transcription: pd.DataFrame
    original: pd.DataFrame
    expected_sequence: List[Tuple[str, str]]


def build_case() -> ChaosCase:
    trans_rows = [
        ("00:06:51:05", "00:06:52:05", "Kommt schon, Jungs!"),
        ("00:06:56:04", "00:06:57:13", "Ich will euch alle bei dieser WM fliegen sehen!"),
        ("00:06:58:00", "00:06:58:04", "Okay!"),
        ("00:06:58:06", "00:06:59:04", "Und noch mehr!"),
        ("00:06:59:09", "00:06:59:11", "Los!"),
        ("00:06:59:12", "00:06:59:18", "Los!"),
        ("00:07:00:02", "00:07:00:16", "Wie viel noch?"),
        ("00:07:00:21", "00:07:01:10", "Ich kann nicht mehr!"),
        ("00:07:01:10", "00:07:02:02", "Los, weiter!"),
        ("00:07:02:06", "00:07:03:06", "Ich kann nicht mehr!"),
        ("00:07:03:18", "00:07:04:09", "Kommt schon!"),
        ("00:07:04:16", "00:07:05:09", "Nicht aufhören!"),
        ("00:07:07:20", "00:07:08:18", "Hallo, Pili!"),
        ("00:07:09:12", "00:07:10:17", "Hallo, hallo, hallo!"),
        ("00:07:10:20", "00:07:11:11", "Hey, schneller!"),
        ("00:07:11:12", "00:07:12:03", "Kommt schon!"),
        ("00:07:12:04", "00:07:12:21", "Nicht aufgeben!"),
        ("00:07:12:21", "00:07:13:12", "Ja, Bewegung!"),
        ("00:07:13:13", "00:07:14:14", "Los, los, los!"),
        ("00:07:15:14", "00:07:16:13", "Jetzt stellt euch nicht so an!"),
        ("00:07:19:22", "00:07:20:16", "Ich sterbe gleich."),
        ("00:07:22:01", "00:07:22:09", "Gut so."),
        ("00:07:22:10", "00:07:23:02", "Weiter, weiter, weiter!"),
        ("00:07:25:02", "00:07:25:18", "Achtung!"),
        ("00:07:26:05", "00:07:26:23", "Achtung!"),
        ("00:07:28:03", "00:07:29:18", "Weiter, weiter, weiter, weiter!"),
        ("00:07:29:20", "00:07:30:10", "Das tut gut."),
        ("00:07:30:20", "00:07:31:08", "Sehr schön."),
        ("00:07:31:12", "00:07:32:04", "Haben wir verdient."),
        ("00:07:32:08", "00:07:33:09", "Das kann häufiger so sein."),
        ("00:07:33:14", "00:07:33:15", "Ja."),
        ("00:07:34:05", "00:07:34:19", "Zum Wohl."),
    ]
    transcription_df = pd.DataFrame(trans_rows, columns=["TIMECODE-IN", "TIMECODE-OUT", "DIALOGUE"])

    orig_rows = [
        ("02:06:50:16", "02:06:53:05", "PARREIRA", "Kommt schon, Jungs! ... Ich will euch alle bei dieser WM fliegen sehen."),
        ("02:06:52:21", "02:06:59:10", "WALLA 20MW", "NEU: [INDISTINCT] (IT?) Weiter so. Brasilien. Ihr werdet Weltmeister. etc."),
        ("02:06:55:22", "02:06:59:10", "WALLA 5M", "TEXT"),
        ("02:06:58:04", "02:06:59:06", "FONTANA", "(Atmer/Laute)"),
        ("02:06:59:06", "02:06:59:22", "MARIO AMERICO", "NEU: Los!"),
        ("02:06:59:22", "02:07:01:10", "BRAZILIAN PLAYER 6", "NEU: [INDISTINCT] Wieviel noch?"),
        ("02:07:01:12", "02:07:04:18", "TOSTAO", "NEU: [REACTION] (Laute)"),
        ("02:07:02:14", "02:07:05:01", "WALLA 5M", "NEU: [INDISTINCT] Weiter. Nicht aufhören. Kämpft. Na los. etc."),
        ("02:07:05:15", "02:07:07:05", "LOCAL BOY 1", "NEU: Hallo, Pelé!"),
        ("02:07:06:14", "02:07:09:04", "PELE", "NEU: hallo, hallo, hallo. [Lacher]"),
        ("02:07:08:21", "02:07:09:21", "GRAPHICS INSERTS", "WILLKOMMEN"),
        ("02:07:09:04", "02:07:15:07", "WALLA 5M", "NEU: [INDISTINCT] Schneller. Kommt schon. Nicht aufgeben. Das sieht gut aus. Ja, klasse. Bewegung. etc."),
        ("02:07:15:06", "02:07:19:23", "GERSON", "TEXT Ich sterbe gleich."),
        ("02:07:15:07", "02:07:20:15", "WALLA 5M", "TEXT"),
        ("02:07:19:14", "02:07:21:05", "BRAZILIAN PLAYER 6", "NEU: Gut so."),
        ("02:07:20:13", "02:07:23:10", "GERSON", "NEU: [REACTION]"),
        ("02:07:21:03", "02:07:23:14", "WALLA 10M", "NEU: [INDISTINCT] Durchhalten. Kämpfen. Ich kann nicht mehr. Weiter, weiter. etc."),
        ("02:07:23:17", "02:07:28:08", "WALLA 10M", "TEXT"),
        ("02:07:24:14", "02:07:28:15", "ZAGALLO", "NEU: Achtung, Achtung! Weiter, weiter, weiter!"),
        ("02:07:25:14", "02:07:27:12", "MARIO AMERICO", "Komm schon, Gérson."),
        ("02:07:28:06", "02:07:29:19", "PAULO CEZAR", "NEU: [Lachen]"),
        ("02:07:29:12", "02:07:33:18", "WALLA 5M", "NEU: [INDISTINCT] Das tut gut. Sehr schön. Haben wir verdient. Das kann häufiger sein. etc."),
        ("02:07:34:00", "02:07:37:05", "PELE", "NEU: Cheers!"),
    ]
    original_df = pd.DataFrame(orig_rows, columns=["timecode_in", "timecode_out", "source", "dialogue"])

    expected_sequence: List[Tuple[str, str]] = [
        ("PARREIRA", "Kommt schon, Jungs! ... Ich will euch alle bei dieser WM fliegen sehen."),
        ("PARREIRA", "Kommt schon, Jungs! ... Ich will euch alle bei dieser WM fliegen sehen."),
        ("WALLA 20MW", "NEU: [INDISTINCT] (IT?) Weiter so. Brasilien. Ihr werdet Weltmeister. etc."),
        ("WALLA 5M", "TEXT"),
        ("MARIO AMERICO", "NEU: Los!"),
        ("MARIO AMERICO", "NEU: Los!"),
        ("BRAZILIAN PLAYER 6", "NEU: [INDISTINCT] Wieviel noch?"),
        ("WALLA 10M", "NEU: [INDISTINCT] Durchhalten. Kämpfen. Ich kann nicht mehr. Weiter, weiter. etc."),
        ("WALLA 10M", "NEU: [INDISTINCT] Durchhalten. Kämpfen. Ich kann nicht mehr. Weiter, weiter. etc."),
        ("WALLA 10M", "NEU: [INDISTINCT] Durchhalten. Kämpfen. Ich kann nicht mehr. Weiter, weiter. etc."),
        ("WALLA 5M", "NEU: [INDISTINCT] Schneller. Kommt schon. Nicht aufgeben. Das sieht gut aus. Ja, klasse. Bewegung. etc."),
        ("WALLA 5M", "NEU: [INDISTINCT] Schneller. Kommt schon. Nicht aufgeben. Das sieht gut aus. Ja, klasse. Bewegung. etc."),
        ("LOCAL BOY 1", "NEU: Hallo, Pelé!"),
        ("PELE", "NEU: hallo, hallo, hallo. [Lacher]"),
        ("WALLA 5M", "NEU: [INDISTINCT] Schneller. Kommt schon. Nicht aufgeben. Das sieht gut aus. Ja, klasse. Bewegung. etc."),
        ("WALLA 5M", "NEU: [INDISTINCT] Schneller. Kommt schon. Nicht aufgeben. Das sieht gut aus. Ja, klasse. Bewegung. etc."),
        ("WALLA 5M", "NEU: [INDISTINCT] Weiter. Nicht aufhören. Kämpft. Na los. etc."),
        ("WALLA 5M", "NEU: [INDISTINCT] Schneller. Kommt schon. Nicht aufgeben. Das sieht gut aus. Ja, klasse. Bewegung. etc."),
        ("WALLA 5M", "NEU: [INDISTINCT] Schneller. Kommt schon. Nicht aufgeben. Das sieht gut aus. Ja, klasse. Bewegung. etc."),
        ("WALLA 5M", "NEU: [INDISTINCT] Schneller. Kommt schon. Nicht aufgeben. Das sieht gut aus. Ja, klasse. Bewegung. etc."),
        ("GERSON", "TEXT Ich sterbe gleich."),
        ("BRAZILIAN PLAYER 6", "NEU: Gut so."),
        ("WALLA 10M", "NEU: [INDISTINCT] Durchhalten. Kämpfen. Ich kann nicht mehr. Weiter, weiter. etc."),
        ("ZAGALLO", "NEU: Achtung, Achtung! Weiter, weiter, weiter!"),
        ("ZAGALLO", "NEU: Achtung, Achtung! Weiter, weiter, weiter!"),
        ("ZAGALLO", "NEU: Achtung, Achtung! Weiter, weiter, weiter!"),
        ("WALLA 5M", "NEU: [INDISTINCT] Das tut gut. Sehr schön. Haben wir verdient. Das kann häufiger sein. etc."),
        ("WALLA 5M", "NEU: [INDISTINCT] Das tut gut. Sehr schön. Haben wir verdient. Das kann häufiger sein. etc."),
        ("WALLA 5M", "NEU: [INDISTINCT] Das tut gut. Sehr schön. Haben wir verdient. Das kann häufiger sein. etc."),
        ("WALLA 5M", "NEU: [INDISTINCT] Das tut gut. Sehr schön. Haben wir verdient. Das kann häufiger sein. etc."),
        ("WALLA 5M", "NEU: [INDISTINCT] Schneller. Kommt schon. Nicht aufgeben. Das sieht gut aus. Ja, klasse. Bewegung. etc."),
        ("PELE", "NEU: Cheers!"),
    ]

    return ChaosCase(
        transcription=transcription_df,
        original=original_df,
        expected_sequence=expected_sequence,
    )
