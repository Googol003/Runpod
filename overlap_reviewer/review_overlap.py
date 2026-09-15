#!/usr/bin/env python3
"""
LLM: Transkript vs. Drehbuch — Überlappungs-/Sprecher-/Sinn-Review.

Flaggt typische Fehler (TEXT_LEAK, SPEAKER_WRONG, NONSENSE) und schreibt Korrekturen
in Excel-Spalten. Test: segment_matcher.chaos_parreira_wm_case (Sprecher aus expected).
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
_REVIEW_DIR = Path(__file__).resolve().parent
_MATCHER_DIR = _CORRECTOR_ROOT / "segment_matcher"
sys.path.insert(0, str(_CORRECTOR_ROOT))
sys.path.insert(0, str(_MATCHER_DIR))
sys.path.insert(0, str(_REVIEW_DIR))

from llm_clients import LLMError, OllamaClient, build_client_from_env, parse_json_response  # noqa: E402
from overlap_review_prompts import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from chaos_parreira_wm_case import build_case  # noqa: E402

ISSUE_TYPES = frozenset({"OK", "TEXT_LEAK", "SPEAKER_WRONG", "NONSENSE", "OTHER"})


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


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
            sp = speaker if speaker else "(kein Sprecher)"
            lines.append(
                f"{idx}. [{_tc_norm(tc_in)} – {_tc_norm(tc_out)}] "
                f"SPEAKER={sp!r} | {dialogue}"
            )
        else:
            lines.append(f"{idx}. [{_tc_norm(tc_in)} – {_tc_norm(tc_out)}] {dialogue}")
    return "\n".join(lines)


def _load_chaos_case() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Transkription mit Sprecher aus expected_sequence (simuliert Post-Match-Zustand).
    Original = Drehbuch.
    """
    case = build_case()
    trans = case.transcription.copy()
    expected = case.expected_sequence or []
    speakers: List[str] = []
    for i in range(len(trans)):
        if i < len(expected):
            speakers.append(str(expected[i][0]))
        else:
            speakers.append("")
    trans["SPEAKER"] = speakers
    return trans, case.original.copy()


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
                str(row.get("SPEAKER", row.get("source", row.get("Matched Speaker", "")))),
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


def _parse_reviews(data: Dict[str, Any], n_trans: int, n_orig: int) -> Dict[int, Dict[str, Any]]:
    raw = data.get("reviews")
    if not isinstance(raw, list):
        raise ValueError("JSON ohne 'reviews'-Liste")

    by_trans: Dict[int, Dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            ti = int(item.get("trans_i"))
        except (TypeError, ValueError):
            continue

        issue = str(item.get("issue_type", "OK")).strip().upper()
        if issue not in ISSUE_TYPES:
            issue = "OTHER"

        oj = item.get("related_orig_j")
        if oj is not None:
            try:
                oj = int(oj)
                if oj < 1 or oj > n_orig:
                    oj = None
            except (TypeError, ValueError):
                oj = None

        flagged = bool(item.get("flagged", False))
        if issue == "OK":
            flagged = False

        by_trans[ti] = {
            "flagged": flagged,
            "issue_type": issue if flagged or issue == "OK" else issue,
            "issue_note": str(item.get("issue_note", "")).strip(),
            "corrected_speaker": str(item.get("corrected_speaker", "")).strip(),
            "corrected_dialogue": str(item.get("corrected_dialogue", "")).strip(),
            "confidence": str(item.get("confidence", "")).strip(),
            "related_orig_j": oj,
        }

    if len(by_trans) != n_trans:
        missing = [i for i in range(1, n_trans + 1) if i not in by_trans]
        raise ValueError(
            f"reviews: erwartet {n_trans} trans_i, bekam {len(by_trans)}; fehlend={missing[:10]}"
        )
    return by_trans


def _reviews_to_dataframe(
    trans_rows: List[Tuple[int, str, str, str, str]],
    orig_rows: List[Tuple[int, str, str, str, str]],
    by_trans: Dict[int, Dict[str, Any]],
) -> pd.DataFrame:
    orig_by_idx = {r[0]: r for r in orig_rows}
    out_rows: List[Dict[str, Any]] = []

    for ti, tc_in, tc_out, speaker, dialogue in trans_rows:
        r = by_trans.get(ti, {})
        oj = r.get("related_orig_j")
        if oj and oj in orig_by_idx:
            _, o_in, o_out, o_speaker, o_dialogue = orig_by_idx[oj]
        else:
            o_in = o_out = o_speaker = o_dialogue = ""

        flagged = bool(r.get("flagged"))
        corr_sp = r.get("corrected_speaker", "") or ""
        corr_dlg = r.get("corrected_dialogue", "") or ""

        out_rows.append(
            {
                "Trans #": ti,
                "TIMECODE-IN": tc_in,
                "TIMECODE-OUT": tc_out,
                "Transcript Speaker": speaker,
                "Transcript Dialogue": dialogue,
                "Flagged": "yes" if flagged else "no",
                "Issue Type": r.get("issue_type", "OK"),
                "Issue Note": r.get("issue_note", ""),
                "Corrected Speaker": corr_sp if flagged else "",
                "Corrected Dialogue": corr_dlg if flagged else "",
                "Review Confidence": r.get("confidence", ""),
                "Related Orig #": oj if oj is not None else "",
                "Related Orig Speaker": o_speaker,
                "Related Orig Dialogue": o_dialogue,
                "Related Orig TIMECODE-IN": o_in,
                "Related Orig TIMECODE-OUT": o_out,
            }
        )

    return pd.DataFrame(out_rows)


def main() -> int:
    p = argparse.ArgumentParser(
        description="LLM: Transkript vs. Drehbuch — Überlappung/Sprecher/Sinn reviewen."
    )
    p.add_argument(
        "--output",
        "-o",
        default=str(_REVIEW_DIR / "output" / "chaos_parreira_wm_overlap_review.xlsx"),
        help="Ausgabe-Excel",
    )
    p.add_argument("--temperature", type=float, default=0.05)
    p.add_argument("--num-ctx", type=int, default=16384)
    p.add_argument("--num-predict", type=int, default=8192)
    p.add_argument("--dry-run", action="store_true", help="Nur Prompt bauen, kein LLM.")
    p.add_argument("--save-prompt", type=str, default="", help="User-Prompt in Datei speichern.")
    args = p.parse_args()

    transcription, original = _load_chaos_case()
    trans_rows, orig_rows = _build_lists(transcription, original)
    n_trans, n_orig = len(trans_rows), len(orig_rows)

    trans_block = _format_segment_block(trans_rows, include_speaker=True)
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
    dump = _REVIEW_DIR / "output" / "chaos_parreira_wm_overlap_review_raw.txt"
    try:
        raw = _call_llm(
            client,
            user_prompt,
            num_ctx=args.num_ctx,
            num_predict=args.num_predict,
            temperature=args.temperature,
        )
        data = parse_json_response(raw)
        by_trans = _parse_reviews(data, n_trans, n_orig)
    except (LLMError, json.JSONDecodeError, ValueError) as e:
        if raw:
            dump.parent.mkdir(parents=True, exist_ok=True)
            dump.write_text(raw, encoding="utf-8")
        print(f"[ERROR] {e}")
        if raw:
            print(f"[ERROR] Rohe Antwort: {dump}")
        return 1

    df_out = _reviews_to_dataframe(trans_rows, orig_rows, by_trans)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_excel(out_path, index=False)

    n_flagged = int((df_out["Flagged"] == "yes").sum())
    print(f"[DONE] {out_path} rows={len(df_out)} flagged={n_flagged}")
    print(f"[DONE] elapsed={time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
