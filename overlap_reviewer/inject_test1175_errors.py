"""
Gezielte, sparsame Test-Injects in test.1175.xlsx.

Fehlerquellen:
1) TEXT_LEAK x3 — Wort vom vorherigen Sprecher klebt am nächsten Segment
2) NONSENSE x1 — nahe Segmente, Kontext-Unsinn
3) SPEAKER_WRONG x3 — MATCHED-TEXT/SOURCE/REF aus Nachbarzeile
4) MUSCHI-Split — nur erstes Segment „Du unglaubliche.“, „Muschi“ weg (kein Doppel-Anfang)

Fehlerzeilen: Spalte INJECTED-ERROR + rote Zellenfüllung.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill

KEEP = [
    "TIMECODE-IN",
    "TIMECODE-OUT",
    "DIALOGUE",
    "SOURCE",
    "MATCHED-TEXT",
    "REF-IN",
    "REF-OUT",
    "NOT_MATCHED",
]

RED = PatternFill(start_color="FFCCCC", end_color="FFCCCC", fill_type="solid")


def _c(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none") else s


def _copy_match(out: pd.DataFrame, dst: int, src: int) -> None:
    out.at[dst, "SOURCE"] = out.at[src, "SOURCE"]
    out.at[dst, "MATCHED-TEXT"] = out.at[src, "MATCHED-TEXT"]
    out.at[dst, "REF-IN"] = out.at[src, "REF-IN"]
    out.at[dst, "REF-OUT"] = out.at[src, "REF-OUT"]


def inject(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[int, str]]:
    out = df.copy()
    notes: dict[int, str] = {}

    # --- TEXT_LEAK x3 ---
    out.at[4, "DIALOGUE"] = "hast – Ich hab dich nie gezwungen, ihn zu verlassen."
    notes[4] = (
        "TEXT_LEAK: Wort „hast“ vom vorherigen STEDE-Segment klebt am IZZY-Satz "
        "(mit anderem Satzzeichen „–“)."
    )

    out.at[31, "DIALOGUE"] = "Mann! Er hat mich angefurzt."
    notes[31] = (
        "TEXT_LEAK: Wort „Mann“ vom vorherigen BUTTONS-Segment klebt am STEDE-Satz "
        "(Satzzeichen „!“ statt „?“)."
    )

    out.at[56, "DIALOGUE"] = "du? Das ist der Schwede."
    notes[56] = (
        "TEXT_LEAK: Wort „du“ vom vorherigen STEDE-Segment klebt am OLUWANDE-Satz "
        "(„?“); zusätzlich SPEAKER_WRONG (siehe Match)."
    )

    # --- NONSENSE x1 (sehr nahe an „Wo ist er?“) ---
    out.at[7, "DIALOGUE"] = "Wo ist das Sofa?"
    notes[7] = (
        "NONSENSE: Sehr nahe am vorherigen Segment „Wo ist er?“ — "
        "„Wo ist das Sofa?“ ergibt im Kontext (Suche nach Ed) keinen Sinn."
    )

    # --- SPEAKER_WRONG / falscher MATCHED-TEXT x3 ---
    _copy_match(out, dst=10, src=9)
    notes[10] = (
        "SPEAKER_WRONG: Dialog „Ed!“ behält, aber MATCHED-TEXT/SOURCE/REF "
        "fälschlich von vorherigem BLACKBEARD-„Stede!“-Segment übernommen."
    )

    _copy_match(out, dst=32, src=33)
    notes[32] = (
        "SPEAKER_WRONG: Dialog „Halt die Klappe!“ (war ROACH), aber MATCHED-TEXT/"
        "SOURCE/REF fälschlich vom nächsten BLACK-PETE-Segment übernommen."
    )

    _copy_match(out, dst=56, src=57)
    notes[56] = (
        notes[56]
        + " SPEAKER_WRONG: MATCHED-TEXT/SOURCE/REF fälschlich vom nächsten "
        "SCHWEDE-Segment („Ich bin der Schwede.“) übernommen."
    )

    # --- „Du unglaubliche“ nur einmal: Muschi vom selben Segment weg ---
    # Nicht: „Du unglaubliche“ + danach nochmal „Du unglaubliche Muschi“.
    # Sondern: nur „Du unglaubliche.“ belassen, „Muschi“ entfernen.
    out.at[8, "DIALOGUE"] = "Du unglaubliche."
    notes[8] = (
        "ASR/SPLIT: Nur „Du unglaubliche.“ belassen — „Muschi“ entfernt "
        "(kein doppelter Anfang „Du unglaubliche … Muschi“). Match bleibt Kackvogel-Zeile."
    )

    out["INJECTED-ERROR"] = ""
    for i, note in notes.items():
        out.at[i, "INJECTED-ERROR"] = note

    return out, notes


def _paint_red(path: Path, error_rows: set[int]) -> None:
    """0-basierte DataFrame-Indizes → Excel-Zeilen (Header=1, Daten ab 2)."""
    wb = load_workbook(path)
    ws = wb.active
    for df_i in error_rows:
        excel_row = df_i + 2
        for col in range(1, ws.max_column + 1):
            ws.cell(excel_row, col).fill = RED
    wb.save(path)


def main() -> None:
    base = Path(__file__).resolve().parent
    clean = base / "output" / "test.1175.relevant_100.xlsx"
    if not clean.exists():
        raise SystemExit(f"Clean base missing: {clean}")
    df = pd.read_excel(clean)
    df = df[[c for c in KEEP if c in df.columns]].iloc[:100].copy()

    injected, notes = inject(df)
    error_rows = set(notes.keys())

    outs = (
        base / "testdata" / "test.1175.xlsx",
        base / "testdata" / "test.1175.injected.xlsx",
        base / "output" / "test.1175.injected.xlsx",
    )
    for out in outs:
        out.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(out, engine="openpyxl") as w:
            injected.to_excel(w, sheet_name="Transkription", index=False)
        _paint_red(out, error_rows)
        print(f"wrote {out} rows={len(injected)} red_rows={sorted(error_rows)}")

    print("--- INJECTED-ERROR ---")
    for i in sorted(notes):
        print(f"  [{i}] {notes[i]}")


if __name__ == "__main__":
    main()
