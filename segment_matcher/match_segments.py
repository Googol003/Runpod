#!/usr/bin/env python3
"""
LLM: Transkript-Segmente → Drehbuch-Segmente matchen; Sprecher in Excel übernehmen.

Test (Standard): segment_matcher.chaos_parreira_wm_case.build_case()
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

_CORRECTOR_ROOT = Path(__file__).resolve().parents[1]
_SEGMENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_CORRECTOR_ROOT))
sys.path.insert(0, str(_SEGMENT_DIR))

from llm_clients import LLMError, OllamaClient, build_client_from_env, parse_json_response  # noqa: E402
from segment_match_prompts import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from chaos_parreira_wm_case import build_case  # noqa: E402


def _tc_norm(tc: str) -> str:
    s = (tc or "").strip()
    if len(s) >= 3 and s[2] == ":" and s[:2].isdigit():
        return "00" + s[2:]
    return s


def _format_segment_block(
    rows: List[Tuple[int, str, str, str, str]],
    *,
    include_speaker: bool,
) -> str:
    lines: List[str] = []
    for idx, tc_in, tc_out, speaker, dialogue in rows:
        if include_speaker:
            lines.append(
                f"{idx}. [{_tc_norm(tc_in)} – {_tc_norm(tc_out)}] "
                f"SPEAKER={speaker!r} | {dialogue}"
            )
        else:
            lines.append(f"{idx}. [{_tc_norm(tc_in)} – {_tc_norm(tc_out)}] {dialogue}")
    return "\n".join(lines)


def _load_chaos_case() -> Tuple[pd.DataFrame, pd.DataFrame, Optional[List[Tuple[str, str]]]]:
    case = build_case()
    expected = case.expected_sequence if case.expected_sequence else None
    return case.transcription.copy(), case.original.copy(), expected


def _build_lists(
    transcription: pd.DataFrame,
    original: pd.DataFrame,
) -> Tuple[List[Tuple[int, str, str, str, str]], List[Tuple[int, str, str, str, str]]]:
    trans_rows: List[Tuple[int, str, str, str, str]] = []
    for _, row in transcription.iterrows():
        trans_rows.append(
            (
                len(trans_rows) + 1,
                str(row.get("TIMECODE-IN", row.get("timecode_in", ""))),
                str(row.get("TIMECODE-OUT", row.get("timecode_out", ""))),
                "",
                str(row.get("DIALOGUE", row.get("dialogue", ""))),
            )
        )

    orig_rows: List[Tuple[int, str, str, str, str]] = []
    for _, row in original.iterrows():
        orig_rows.append(
            (
                len(orig_rows) + 1,
                str(row.get("timecode_in", row.get("TIMECODE-IN", ""))),
                str(row.get("timecode_out", row.get("TIMECODE-OUT", ""))),
                str(row.get("source", row.get("SPEAKER", ""))),
                str(row.get("dialogue", row.get("DIALOGUE", ""))),
            )
        )
    return trans_rows, orig_rows


def _call_llm(
    client: Any,
    user_prompt: str,
    *,
    num_ctx: int,
    num_predict: int,
    temperature: float,
) -> str:
    kwargs: Dict[str, Any] = {}
    if isinstance(client, OllamaClient):
        kwargs["options"] = {"num_ctx": num_ctx, "num_predict": num_predict}
    return client.chat(SYSTEM_PROMPT, user_prompt, temperature=temperature, **kwargs)


def _parse_matches(data: Dict[str, Any], n_trans: int, n_orig: int) -> Dict[int, Dict[str, Any]]:
    raw = data.get("matches")
    if not isinstance(raw, list):
        raise ValueError("JSON ohne 'matches'-Liste")

    by_trans: Dict[int, Dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            ti = int(item.get("trans_i"))
        except (TypeError, ValueError):
            continue
        oj = item.get("orig_j")
        if oj is not None:
            try:
                oj = int(oj)
                if oj < 1 or oj > n_orig:
                    oj = None
            except (TypeError, ValueError):
                oj = None
        by_trans[ti] = {
            "orig_j": oj,
            "confidence": str(item.get("confidence", "")).strip(),
            "reason": str(item.get("reason", "")).strip(),
        }

    if len(by_trans) != n_trans:
        missing = [i for i in range(1, n_trans + 1) if i not in by_trans]
        raise ValueError(
            f"matches: erwartet {n_trans} trans_i, bekam {len(by_trans)}; fehlend={missing[:10]}"
        )
    return by_trans


def _matches_to_dataframe(
    trans_rows: List[Tuple[int, str, str, str, str]],
    orig_rows: List[Tuple[int, str, str, str, str]],
    by_trans: Dict[int, Dict[str, Any]],
    expected: Optional[List[Tuple[str, str]]],
) -> pd.DataFrame:
    orig_by_idx = {r[0]: r for r in orig_rows}
    out_rows: List[Dict[str, Any]] = []

    for ti, tc_in, tc_out, _, dialogue in trans_rows:
        m = by_trans.get(ti, {})
        oj = m.get("orig_j")
        if oj and oj in orig_by_idx:
            _, o_in, o_out, speaker, o_dialogue = orig_by_idx[oj]
        else:
            o_in = o_out = speaker = o_dialogue = ""
            oj = None

        row: Dict[str, Any] = {
            "Trans #": ti,
            "TIMECODE-IN": tc_in,
            "TIMECODE-OUT": tc_out,
            "Transcript Dialogue": dialogue,
            "Matched Orig #": oj if oj is not None else "",
            "Orig TIMECODE-IN": o_in,
            "Orig TIMECODE-OUT": o_out,
            "Matched Speaker": speaker,
            "Matched Original Dialogue": o_dialogue,
            "Match Confidence": m.get("confidence", ""),
            "Match Reason": m.get("reason", ""),
        }
        if expected and 1 <= ti <= len(expected):
            exp_sp, exp_txt = expected[ti - 1]
            row["Expected Speaker"] = exp_sp
            row["Expected Original Dialogue"] = exp_txt
            row["Speaker OK"] = (
                normalize_ws(speaker).upper() == normalize_ws(exp_sp).upper()
                if speaker and exp_sp
                else ""
            )
        out_rows.append(row)

    return pd.DataFrame(out_rows)


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def main() -> int:
    p = argparse.ArgumentParser(description="LLM: Transkript → Drehbuch matchen (Sprecher übernehmen).")
    p.add_argument(
        "--output",
        "-o",
        default=str(_SEGMENT_DIR / "output" / "chaos_parreira_wm_match.xlsx"),
        help="Ausgabe-Excel",
    )
    p.add_argument("--temperature", type=float, default=0.05)
    p.add_argument("--num-ctx", type=int, default=16384)
    p.add_argument("--num-predict", type=int, default=8192)
    p.add_argument("--dry-run", action="store_true", help="Nur Prompt bauen, kein LLM.")
    p.add_argument("--save-prompt", type=str, default="", help="User-Prompt in Datei speichern.")
    args = p.parse_args()

    transcription, original, expected = _load_chaos_case()
    trans_rows, orig_rows = _build_lists(transcription, original)
    n_trans, n_orig = len(trans_rows), len(orig_rows)

    trans_block = _format_segment_block(trans_rows, include_speaker=False)
    orig_block = _format_segment_block(orig_rows, include_speaker=True)
    user_prompt = build_user_prompt(
        n_trans=n_trans,
        n_orig=n_orig,
        transcription_block=trans_block,
        original_block=orig_block,
    )

    if args.save_prompt:
        Path(args.save_prompt).write_text(user_prompt, encoding="utf-8")
        print(f"[OK] Prompt gespeichert: {args.save_prompt}")

    if args.dry_run:
        print(f"[DRY-RUN] trans={n_trans} orig={n_orig} chars={len(user_prompt)}")
        print(user_prompt[:2000] + ("\n…" if len(user_prompt) > 2000 else ""))
        return 0

    client = build_client_from_env()
    model = getattr(client, "model", "?")
    print(f"[START] model={model} trans={n_trans} orig={n_orig}")

    t0 = time.time()
    raw = ""
    dump = _SEGMENT_DIR / "output" / "chaos_parreira_wm_match_raw.txt"
    try:
        raw = _call_llm(
            client,
            user_prompt,
            num_ctx=args.num_ctx,
            num_predict=args.num_predict,
            temperature=args.temperature,
        )
        data = parse_json_response(raw)
        by_trans = _parse_matches(data, n_trans, n_orig)
    except (LLMError, json.JSONDecodeError, ValueError) as e:
        if raw:
            dump.parent.mkdir(parents=True, exist_ok=True)
            dump.write_text(raw, encoding="utf-8")
        print(f"[ERROR] {e}")
        if raw:
            print(f"[ERROR] Rohe Antwort: {dump}")
        return 1

    df_out = _matches_to_dataframe(trans_rows, orig_rows, by_trans, expected)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_excel(out_path, index=False)

    matched = sum(1 for r in by_trans.values() if r.get("orig_j"))
    if expected and "Speaker OK" in df_out.columns:
        ok = int((df_out["Speaker OK"] == True).sum())  # noqa: E712
        print(f"[DONE] {out_path} rows={len(df_out)} matched={matched} speaker_ok={ok}/{len(df_out)}")
    else:
        print(f"[DONE] {out_path} rows={len(df_out)} matched={matched}")
    print(f"[DONE] elapsed={time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
