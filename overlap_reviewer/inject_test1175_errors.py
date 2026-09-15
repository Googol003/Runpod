"""
Erzeugt aus test.1175.relevant.xlsx eine Version mit simulierten Überlappungs-/Rollen-/Nonsens-Fehlern.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

KEEP = ["TIMECODE-IN", "TIMECODE-OUT", "DIALOGUE", "SOURCE", "MATCHED-TEXT", "NOT_MATCHED"]


def inject(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    # Index = Positionsindex 0..n-1

    # 1) TEXT_LEAK: Stede-Zeile bekommt Izzy-Anfang angehängt (Überlappung)
    # Zeile 3: "Dass du uns an die Engländer verkauft hast."
    i = 3
    out.at[i, "DIALOGUE"] = (
        "Dass du uns an die Engländer verkauft hast. Ich hab dich nie gezwungen."
    )

    # 2) SPEAKER_WRONG: Izzy-Text, aber SOURCE=STEDE + falscher MATCHED-TEXT
    i = 4
    out.at[i, "SOURCE"] = "STEDE"
    out.at[i, "MATCHED-TEXT"] = "Wo ist er? .. Wo ist Ed?"

    # 3) TEXT_LEAK + Überlappung: Stede-Frage und Izzy-Beleidigung in einer Zeile
    i = 7
    out.at[i, "DIALOGUE"] = "Wo ist Ed? Du unglaubliche Muschi."
    out.at[i, "SOURCE"] = "STEDE"
    out.at[i, "MATCHED-TEXT"] = "Wo ist er? .. Wo ist Ed?"

    # 4) SPEAKER_WRONG im Ruf-Block: Ed! fälschlich BLACKBEARD
    i = 10
    out.at[i, "SOURCE"] = "BLACKBEARD"
    out.at[i, "MATCHED-TEXT"] = "Stede!"

    # 5) SPEAKER_WRONG: Sid! → sollte BLACKBEARD/Stede bleiben, hier STEDE + Ed!
    i = 13
    out.at[i, "SOURCE"] = "STEDE"
    out.at[i, "MATCHED-TEXT"] = "Ed!"
    out.at[i, "DIALOGUE"] = "Sid! Ed!"

    # 6) NONSENSE: klare Abweichung zum MATCHED-TEXT / Kontext
    i = 35
    out.at[i, "DIALOGUE"] = "Die Pizza ist kalt und der Mond ist aus Käse."
    # SOURCE/MATCHED lassen (Absicht: Text ergibt keinen Sinn zum Script)

    # 7) TEXT_LEAK bei Buttons/Roach-Bereich: Schnauze klebt an Stede
    i = 34
    out.at[i, "DIALOGUE"] = "Es ist noch da. Schnauze, Mann!"
    out.at[i, "SOURCE"] = "STEDE"

    # 8) Leere SOURCE (orphan) bei einer Cue-Zeile
    i = 12
    out.at[i, "SOURCE"] = ""
    out.at[i, "MATCHED-TEXT"] = ""

    return out


def main() -> None:
    src = Path(__file__).resolve().parent / "output" / "test.1175.relevant.xlsx"
    if not src.exists():
        # Fallback: full backup stripped
        backup = Path(__file__).resolve().parent / "output" / "test.1175.full_backup.xlsx"
        if not backup.exists():
            raise SystemExit(f"Keine Quell-Excel: {src}")
        df = pd.read_excel(backup, sheet_name="Transkription")
        df = df[[c for c in KEEP if c in df.columns]]
    else:
        df = pd.read_excel(src)
        df = df[[c for c in KEEP if c in df.columns]]

    injected = inject(df)
    out = Path(__file__).resolve().parent / "output" / "test.1175.injected.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        injected.to_excel(w, sheet_name="Transkription", index=False)
    print(f"wrote {out} rows={len(injected)}")
    print("Injected row indices (0-based): 3,4,7,10,12,13,34,35")


if __name__ == "__main__":
    main()
