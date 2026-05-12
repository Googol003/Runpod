from __future__ import annotations

import argparse
import json
import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from llm_clients import build_client_from_env, parse_json_response, LLMError
from prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def token_similarity(a: str, b: str) -> float:
    """
    Sehr einfache, schnelle Heuristik: Jaccard auf Wort-Tokens.
    """
    a = normalize_ws(a).lower()
    b = normalize_ws(b).lower()
    if not a or not b:
        return 0.0
    a_tokens = set(re.findall(r"\w+", a))
    b_tokens = set(re.findall(r"\w+", b))
    if not a_tokens or not b_tokens:
        return 0.0
    inter = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    return inter / union if union else 0.0


def char_similarity(a: str, b: str) -> float:
    a = normalize_ws(a)
    b = normalize_ws(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def safe_to_apply(original: str, corrected: str, matched_text: str) -> Tuple[bool, str]:
    """
    Strenge Post-Checks, damit wirklich nur "sichere" Änderungen durchkommen.
    """
    o = normalize_ws(original)
    c = normalize_ws(corrected)

    if c == o:
        return True, "no_change"

    # Nicht zu stark umschreiben
    if char_similarity(o, c) < 0.85:
        return False, "too_different_from_original"

    # Wortanzahl darf sich maximal um 1 ändern (z.B. "haste" -> "hast du")
    ow = o.split()
    cw = c.split()
    if abs(len(ow) - len(cw)) > 1:
        return False, "word_count_change_too_large"

    # Wenn matched_text offensichtlich nicht passt, lieber nichts tun
    ts = token_similarity(o, matched_text)
    if ts < 0.12:
        return False, "dialogue_matched_text_unrelated"

    return True, "ok"


def stringify(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return str(val)


def find_column(df: pd.DataFrame, wanted: str) -> str:
    def norm(x: str) -> str:
        return re.sub(r"\s+", " ", x.strip().lower().replace("_", " ").replace("-", " "))

    w = norm(wanted)
    for col in df.columns:
        if norm(str(col)) == w:
            return str(col)
    raise KeyError(f"Spalte nicht gefunden: {wanted}. Verfügbar: {list(df.columns)}")


def main() -> int:
    p = argparse.ArgumentParser(description="Vorsichtige Dialogue-Korrektur per LLM (RunPod-tauglich).")
    p.add_argument("--input", required=True, help="Pfad zur Input-Excel (.xlsx)")
    p.add_argument("--output", default="", help="Pfad zur Output-Excel (.xlsx). Default: <input>_corrected.xlsx")
    p.add_argument("--dialogue-col", default="Dialogue", help="Spaltenname für Dialogue")
    p.add_argument("--matched-col", default="Matched Text", help="Spaltenname für Matched Text")
    p.add_argument("--corrected-col", default="Corrected Dialogue", help="Neue Spalte: korrigierter Dialogue")
    p.add_argument("--corrections-col", default="Corrections", help="Neue Spalte: Liste der Korrekturen (JSON)")
    p.add_argument("--min-token-sim", type=float, default=0.12, help="Früher Skip, wenn Dialogue/Matched zu unähnlich")
    p.add_argument("--max-rows", type=int, default=0, help="Optional: max Zeilen (0=alle)")
    args = p.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        raise SystemExit(f"Input nicht gefunden: {in_path}")

    out_path = Path(args.output) if args.output else in_path.with_name(f"{in_path.stem}_corrected.xlsx")

    df = pd.read_excel(in_path)
    dialogue_col = find_column(df, args.dialogue_col)
    matched_col = find_column(df, args.matched_col)

    client = build_client_from_env()
    # optional warmup (nur für ollama client sinnvoll, aber schadet nicht)
    if hasattr(client, "warmup"):
        client.warmup()

    corrected_values: List[str] = []
    corrections_values: List[str] = []

    total = len(df) if args.max_rows <= 0 else min(len(df), args.max_rows)

    for i in range(total):
        dialogue = stringify(df.at[i, dialogue_col])
        matched = stringify(df.at[i, matched_col])

        # Früher Skip, wenn offensichtlich unrelated
        if token_similarity(dialogue, matched) < args.min_token_sim:
            corrected_values.append(dialogue)
            corrections_values.append("[]")
            continue

        user_prompt = USER_PROMPT_TEMPLATE.format(dialogue=dialogue, matched_text=matched)

        try:
            raw = client.chat(SYSTEM_PROMPT, user_prompt, temperature=0.05)
            data = parse_json_response(raw)
        except (LLMError, json.JSONDecodeError, ValueError) as e:
            # Fail-safe: nichts ändern
            corrected_values.append(dialogue)
            corrections_values.append("[]")
            continue

        leave_unchanged = bool(data.get("leave_unchanged", True))
        confidence = str(data.get("confidence", "low")).lower().strip()
        corrected = stringify(data.get("corrected_dialogue", dialogue))
        corrections = data.get("corrections", [])

        if leave_unchanged or confidence != "high":
            corrected_values.append(dialogue)
            corrections_values.append("[]")
            continue

        ok, reason = safe_to_apply(dialogue, corrected, matched)
        if not ok:
            corrected_values.append(dialogue)
            corrections_values.append("[]")
            continue

        # Nur dann anwenden
        corrected_values.append(corrected)
        try:
            # Korrekturen als JSON-String speichern (Excel-freundlich)
            corrections_values.append(json.dumps(corrections, ensure_ascii=False))
        except Exception:
            corrections_values.append("[]")

    # Restliche Zeilen (falls max_rows) unverändert übernehmen
    for i in range(total, len(df)):
        dialogue = stringify(df.at[i, dialogue_col])
        corrected_values.append(dialogue)
        corrections_values.append("[]")

    df_out = df.copy()
    df_out[args.corrected_col] = corrected_values
    df_out[args.corrections_col] = corrections_values
    df_out.to_excel(out_path, index=False)

    print(f"OK: geschrieben -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

