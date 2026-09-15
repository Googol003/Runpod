"""
Subtile Fehler in test.1175 (erste 100 Zeilen): ASR-Nonsens, Wort-Leaks, Sprechervertauschung.
Keine erfundenen Vollsätze, die „sinnvoll aber nie gesagt“ wären.
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


def inject(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    # --- TEXT_LEAK (Überlappung): kurze Brocken vom anderen Sprecher kleben an ---
    # Stede-Zeile + Anfang von Izzys nächster Zeile (kein neuer Sinn-Satz)
    out.at[3, "DIALOGUE"] = "Dass du uns an die Engländer verkauft hast. Ich hab dich nie"

    # Stede „Wo ist Ed?“ + Brocken aus Izzys Beleidigung
    out.at[7, "DIALOGUE"] = "Wo ist Ed? Du unglaubliche"

    # Stede „Es ist noch da.“ + Brocken aus Buttons/Roach-Überlappung („Schnauze“)
    out.at[34, "DIALOGUE"] = "Es ist noch da. Schnauze"

    # Black Pete-Zeile bekommt Stede-Brocken mit
    out.at[36, "DIALOGUE"] = (
        "Kann nicht schlimmer sein als sein Et-O-Et-Gestöhne die ganze Nacht. Haltet"
    )

    # --- SPEAKER_WRONG: Text bleibt (nahezu) gleich, Rolle falsch ---
    # Izzy-Text, aber als STEDE gelabelt + falscher MATCHED-Hinweis
    out.at[4, "SOURCE"] = "STEDE"
    out.at[4, "MATCHED-TEXT"] = "Wo ist er? .. Wo ist Ed?"

    # Ed! fälschlich BLACKBEARD
    out.at[10, "SOURCE"] = "BLACKBEARD"
    out.at[10, "MATCHED-TEXT"] = "Stede!"

    # Sid! (= ASR für Stede!) fälschlich STEDE / Ed!
    out.at[13, "SOURCE"] = "STEDE"
    out.at[13, "MATCHED-TEXT"] = "Ed!"

    # Ach, Schnauze! → fälschlich ROACH statt BLACK PETE
    out.at[33, "SOURCE"] = "ROACH"
    out.at[33, "MATCHED-TEXT"] = "Halt die Klappe!"

    # --- ASR-NONSENSE: falsch gehört, phonetisch/ähnlich, im Kontext Quatsch ---
    # (Zeile 8 hat schon „Muschi“ statt Kackvogel — belassen/leicht verstärken)
    out.at[8, "DIALOGUE"] = "Du unglaubliche Muschi."

    # Wee John → Oui John (schon ähnlich; etwas kaputter)
    out.at[29, "DIALOGUE"] = "Oui, John!"

    # Wand aus Gestank → kaputte Hörvariante (kein neuer Satz)
    out.at[35, "DIALOGUE"] = "Es ist eine Wand ausgestankt."

    # sauer → Saur (leichter Typo/Nonsens bleibt)
    out.at[16, "DIALOGUE"] = "Du bist nicht Saur?"

    # Ed, oh Ed → Et-O-Et (bereits stark; noch etwas undeutlicher)
    out.at[36, "DIALOGUE"] = (
        "Kann nicht schlimmer sein als sein Et-O-Et-Gestöhne die ganze Nacht. Haltet"
    )

    # Cue-Leak: Ed! und Sid! in einer Zeile (Überlappung der Rufe)
    out.at[12, "DIALOGUE"] = "Ed! Sid!"
    out.at[12, "SOURCE"] = "STEDE"
    out.at[12, "MATCHED-TEXT"] = "Ed!"

    return out


def main() -> None:
    base = Path(__file__).resolve().parent / "output"
    # Saubere 100er-Basis bevorzugen
    src = base / "test.1175.relevant_100.xlsx"
    if not src.exists():
        src = base / "test.1175.relevant.xlsx"
    if not src.exists():
        backup = base / "test.1175.full_backup.xlsx"
        df = pd.read_excel(backup, sheet_name="Transkription")
        df = df[[c for c in KEEP if c in df.columns]].iloc[:100].copy()
    else:
        df = pd.read_excel(src)
        df = df[[c for c in KEEP if c in df.columns]].iloc[:100].copy()

    injected = inject(df)
    # Gleicher MATCHED-TEXT → gleiche REF-Timecodes (auch in der Excel-Datei)
    if "REF-IN" in injected.columns and "REF-OUT" in injected.columns:
        canon: dict[tuple[str, str], tuple[str, str]] = {}

        def _c(v) -> str:
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return ""
            s = str(v).strip()
            return "" if s.lower() in ("nan", "none") else s

        def _nw(s: str) -> str:
            return " ".join(s.split())

        for _, row in injected.iterrows():
            mat = _nw(_c(row.get("MATCHED-TEXT")))
            if not mat:
                continue
            key = (_c(row.get("SOURCE")).upper(), mat)
            tin = _c(row.get("REF-IN")) or _c(row.get("TIMECODE-IN"))
            tout = _c(row.get("REF-OUT")) or _c(row.get("TIMECODE-OUT"))
            if key not in canon:
                canon[key] = (tin, tout)
            else:
                a, b = canon[key]
                canon[key] = (
                    tin if (tin and (not a or tin < a)) else a,
                    tout if (tout and (not b or tout > b)) else b,
                )
        for i, row in injected.iterrows():
            mat = _nw(_c(row.get("MATCHED-TEXT")))
            if not mat:
                continue
            key = (_c(row.get("SOURCE")).upper(), mat)
            if key in canon:
                injected.at[i, "REF-IN"] = canon[key][0]
                injected.at[i, "REF-OUT"] = canon[key][1]

    out = base / "test.1175.injected.xlsx"
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        injected.to_excel(w, sheet_name="Transkription", index=False)
    print(f"wrote {out} rows={len(injected)}")
    print("subtle injects: leaks @3,7,12,34,36 | wrong speaker @4,10,13,33 | asr-nonsense @8,16,29,35")


if __name__ == "__main__":
    main()
