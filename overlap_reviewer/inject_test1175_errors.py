"""
Gezielte, sparsame Test-Injects in test.1175.xlsx (Default-Testdatei).

Fehlerquellen (bewusst wenige):
1) TEXT_LEAK x3 — ein Wort vom vorherigen Sprecher klebt am nächsten Segment (andere Satzzeichen)
2) NONSENSE x1 — bei zwei sehr nahen Segmenten echter Deutsch-/Kontext-Unsinn
3) SPEAKER_WRONG / falscher MATCHED-TEXT x3 — Match aus kurz davor/danach → SOURCE+REF mit falsch
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

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


def _c(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none") else s


def _copy_match(out: pd.DataFrame, dst: int, src: int) -> None:
    """Übernimmt MATCHED-TEXT + SOURCE + REF vom src-Index auf dst (falsche Zuordnung)."""
    out.at[dst, "SOURCE"] = out.at[src, "SOURCE"]
    out.at[dst, "MATCHED-TEXT"] = out.at[src, "MATCHED-TEXT"]
    out.at[dst, "REF-IN"] = out.at[src, "REF-IN"]
    out.at[dst, "REF-OUT"] = out.at[src, "REF-OUT"]


def inject(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    # --- 1) TEXT_LEAK x3: letztes Wort des vorherigen Sprechers + anderes Satzzeichen ---
    # STEDE "...hast." → IZZY bekommt "hast – …"
    out.at[4, "DIALOGUE"] = "hast – Ich hab dich nie gezwungen, ihn zu verlassen."

    # BUTTONS "...Mann?" → STEDE bekommt "Mann! …"
    out.at[31, "DIALOGUE"] = "Mann! Er hat mich angefurzt."

    # STEDE "...du." → OLUWANDE bekommt "du? …"
    out.at[56, "DIALOGUE"] = "du? Das ist der Schwede."

    # --- 2) NONSENSE x1: sehr nahe Segmente (Wo ist er? / Wo ist Ed?) ---
    # Kontext: Suche nach Ed — "Wo ist das Sofa?" ergibt keinen Sinn
    out.at[7, "DIALOGUE"] = "Wo ist das Sofa?"

    # --- 3) Falscher MATCHED-TEXT (kurz davor/danach) → SOURCE+REF falsch ---
    # STEDE "Ed!" bekommt BLACKBEARD-"Stede!"-Match von Zeile davor
    _copy_match(out, dst=10, src=9)

    # ROACH "Halt die Klappe!" bekommt BLACK-PETE-Match von der nächsten Zeile
    _copy_match(out, dst=32, src=33)

    # OLUWANDE "Das ist der Schwede." bekommt SCHWEDE-Match der nächsten Zeile
    # (DIALOGUE hat schon Leak; Match/SOURCE zusätzlich falsch)
    _copy_match(out, dst=56, src=57)

    return out


def main() -> None:
    base = Path(__file__).resolve().parent
    # Immer von sauberer Basis starten
    clean = base / "output" / "test.1175.relevant_100.xlsx"
    if not clean.exists():
        clean = base / "testdata" / "test.1175.xlsx"
    df = pd.read_excel(clean)
    df = df[[c for c in KEEP if c in df.columns]].iloc[:100].copy()

    injected = inject(df)

    for out in (
        base / "testdata" / "test.1175.xlsx",
        base / "testdata" / "test.1175.injected.xlsx",
        base / "output" / "test.1175.injected.xlsx",
    ):
        out.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(out, engine="openpyxl") as w:
            injected.to_excel(w, sheet_name="Transkription", index=False)
        print(f"wrote {out} rows={len(injected)}")

    print(
        "injects: LEAK @4,31,56 | NONSENSE @7 (nahe TC) | "
        "WRONG_MATCH/SOURCE @10<-9, @32<-33, @56<-57"
    )


if __name__ == "__main__":
    main()
