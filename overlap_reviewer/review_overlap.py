#!/usr/bin/env python3
"""
LLM: Transkript vs. Drehbuch — Überlappungs-/Sprecher-/Sinn-Review.

Input: Post-Match-Transkription (SOURCE + MATCHED-TEXT) + komplettes Original + NOT_MATCHED.
Default-Test: izzy_stede_overlap_case (starke Leaks / falsche Rollen / Unmatched).
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
sys.path.insert(0, str(_CORRECTOR_ROOT))
sys.path.insert(0, str(_REVIEW_DIR))

from llm_clients import LLMError, OllamaClient, build_client_from_env, parse_json_response  # noqa: E402
from overlap_review_prompts import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from izzy_stede_overlap_case import build_case  # noqa: E402

ISSUE_TYPES = frozenset({"OK", "TEXT_LEAK", "SPEAKER_WRONG", "NONSENSE", "OTHER"})
_NOT_MATCHED_RE = re.compile(
    r"Original:\s*(\d{2}:\d{2}:\d{2}:\d{2})\s*[–\-]\s*(\d{2}:\d{2}:\d{2}:\d{2})\s*\|\s*([^:]+):\s*(.+?)(?:\s*\|\s*Platzierung|$)",
    re.IGNORECASE | re.DOTALL,
)


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _cell(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if s.lower() in ("nan", "none"):
        return ""
    return s


def load_sm2_excel(path: Path) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    SM2-Ergebnis-Excel (Spalten: TIMECODE-IN/OUT, DIALOGUE, SOURCE, MATCHED-TEXT, NOT_MATCHED).
    Baut Original-Liste aus eindeutigen MATCHED-TEXT+SOURCE plus geparsten NOT_MATCHED-Zeilen.
    """
    df = pd.read_excel(path)
    # erste Sheet falls multi
    if not isinstance(df, pd.DataFrame):
        df = pd.read_excel(path, sheet_name=0)

    need = ["TIMECODE-IN", "TIMECODE-OUT", "DIALOGUE", "SOURCE", "MATCHED-TEXT", "NOT_MATCHED"]
    for c in need:
        if c not in df.columns:
            raise ValueError(f"Spalte fehlt in {path}: {c}")

    transcription = df[need].copy()

    # Original aus Matches (1:n erlaubt → dedupe)
    orig_rows: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for _, row in transcription.iterrows():
        src = _cell(row.get("SOURCE"))
        mat = _cell(row.get("MATCHED-TEXT"))
        if not src or not mat:
            continue
        key = (src.upper(), normalize_ws(mat))
        if key in seen:
            continue
        seen.add(key)
        orig_rows.append(
            {
                "timecode_in": _cell(row.get("TIMECODE-IN")),
                "timecode_out": _cell(row.get("TIMECODE-OUT")),
                "source": src,
                "dialogue": mat,
            }
        )

    unmatched_rows: List[Dict[str, str]] = []
    for _, row in transcription.iterrows():
        nm = _cell(row.get("NOT_MATCHED"))
        if not nm:
            continue
        m = _NOT_MATCHED_RE.search(nm.replace("\n", " "))
        if m:
            tin, tout, speaker, dialogue = m.group(1), m.group(2), m.group(3).strip(), m.group(4).strip()
            dialogue = dialogue.split("|")[0].strip()
            key = (speaker.upper(), normalize_ws(dialogue))
            entry = {
                "timecode_in": tin,
                "timecode_out": tout,
                "source": speaker,
                "dialogue": dialogue,
            }
            unmatched_rows.append(entry)
            if key not in seen:
                seen.add(key)
                orig_rows.append(entry)
        else:
            unmatched_rows.append(
                {
                    "timecode_in": _cell(row.get("TIMECODE-IN")),
                    "timecode_out": _cell(row.get("TIMECODE-OUT")),
                    "source": "?",
                    "dialogue": nm[:200],
                }
            )

    original = pd.DataFrame(orig_rows) if orig_rows else pd.DataFrame(
        columns=["timecode_in", "timecode_out", "source", "dialogue"]
    )
    not_matched = pd.DataFrame(unmatched_rows) if unmatched_rows else pd.DataFrame(
        columns=["timecode_in", "timecode_out", "source", "dialogue"]
    )
    return transcription, original, not_matched


def _tc_norm(tc: str) -> str:
    s = (tc or "").strip()
    if len(s) >= 3 and s[2] == ":" and s[:2].isdigit():
        return "00" + s[2:]
    return s


def _format_trans_block(rows: List[Tuple[int, str, str, str, str, str]]) -> str:
    """idx, tc_in, tc_out, speaker, dialogue, matched_text"""
    lines: List[str] = []
    for idx, tc_in, tc_out, speaker, dialogue, matched in rows:
        sp = speaker if speaker else "(kein Sprecher / unmatched)"
        mt = matched if matched else "(kein MATCHED-TEXT)"
        lines.append(
            f"{idx}. [{_tc_norm(tc_in)} – {_tc_norm(tc_out)}] "
            f"SPEAKER={sp!r} | DIALOGUE={dialogue!r} | MATCHED-TEXT={mt!r}"
        )
    return "\n".join(lines)


def _format_orig_block(rows: List[Tuple[int, str, str, str, str]]) -> str:
    lines: List[str] = []
    for idx, tc_in, tc_out, speaker, dialogue in rows:
        lines.append(
            f"{idx}. [{_tc_norm(tc_in)} – {_tc_norm(tc_out)}] "
            f"SPEAKER={speaker!r} | {dialogue}"
        )
    return "\n".join(lines)


def _build_lists(
    transcription: pd.DataFrame,
    original: pd.DataFrame,
    not_matched: pd.DataFrame,
) -> Tuple[
    List[Tuple[int, str, str, str, str, str]],
    List[Tuple[int, str, str, str, str]],
    List[Tuple[int, str, str, str, str]],
]:
    trans_rows: List[Tuple[int, str, str, str, str, str]] = []
    for _, row in transcription.iterrows():
        trans_rows.append(
            (
                len(trans_rows) + 1,
                str(row.get("TIMECODE-IN", row.get("timecode_in", ""))),
                str(row.get("TIMECODE-OUT", row.get("timecode_out", ""))),
                str(row.get("SOURCE", row.get("SPEAKER", ""))),
                str(row.get("DIALOGUE", row.get("dialogue", ""))),
                str(row.get("MATCHED-TEXT", row.get("Matched Text", ""))),
            )
        )

    orig_rows: List[Tuple[int, str, str, str, str]] = []
    for _, row in original.iterrows():
        orig_rows.append(
            (
                len(orig_rows) + 1,
                str(row.get("timecode_in", row.get("TIMECODE-IN", ""))),
                str(row.get("timecode_out", row.get("TIMECODE-OUT", ""))),
                str(row.get("source", row.get("SOURCE", row.get("SPEAKER", "")))),
                str(row.get("dialogue", row.get("DIALOGUE", ""))),
            )
        )

    unmatched_rows: List[Tuple[int, str, str, str, str]] = []
    for _, row in not_matched.iterrows():
        unmatched_rows.append(
            (
                len(unmatched_rows) + 1,
                str(row.get("timecode_in", row.get("TIMECODE-IN", ""))),
                str(row.get("timecode_out", row.get("TIMECODE-OUT", ""))),
                str(row.get("source", row.get("SOURCE", row.get("SPEAKER", "")))),
                str(row.get("dialogue", row.get("DIALOGUE", ""))),
            )
        )
    return trans_rows, orig_rows, unmatched_rows


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
            "issue_type": issue,
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
    trans_rows: List[Tuple[int, str, str, str, str, str]],
    orig_rows: List[Tuple[int, str, str, str, str]],
    by_trans: Dict[int, Dict[str, Any]],
) -> pd.DataFrame:
    orig_by_idx = {r[0]: r for r in orig_rows}
    out_rows: List[Dict[str, Any]] = []

    for ti, tc_in, tc_out, speaker, dialogue, matched in trans_rows:
        r = by_trans.get(ti, {})
        oj = r.get("related_orig_j")
        if oj and oj in orig_by_idx:
            _, o_in, o_out, o_speaker, o_dialogue = orig_by_idx[oj]
        else:
            o_in = o_out = o_speaker = o_dialogue = ""

        flagged = bool(r.get("flagged"))
        out_rows.append(
            {
                "Trans #": ti,
                "TIMECODE-IN": tc_in,
                "TIMECODE-OUT": tc_out,
                "Transcript Speaker": speaker,
                "Transcript Dialogue": dialogue,
                "MATCHED-TEXT": matched,
                "Flagged": "yes" if flagged else "no",
                "Issue Type": r.get("issue_type", "OK"),
                "Issue Note": r.get("issue_note", ""),
                "Corrected Speaker": (r.get("corrected_speaker") or "") if flagged else "",
                "Corrected Dialogue": (r.get("corrected_dialogue") or "") if flagged else "",
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
        description="LLM: Transkript vs. Drehbuch — Überlappung/Sprecher/Sinn (inkl. NOT_MATCHED)."
    )
    p.add_argument(
        "--input",
        "-i",
        default="",
        help="SM2-Excel mit Spalten TIMECODE-IN/OUT, DIALOGUE, SOURCE, MATCHED-TEXT, NOT_MATCHED. "
        "Leer = eingebauter Izzy/Stede-Case.",
    )
    p.add_argument(
        "--output",
        "-o",
        default="",
        help="Ausgabe-Excel (Reviews). Default abhängig von --input.",
    )
    p.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="Nur erste N Transkript-Zeilen (0 = alle). Empfohlen bei großen Excels.",
    )
    p.add_argument(
        "--export-case",
        default="",
        help="Optional: geladene Daten als Excel exportieren (Sheets: transcription, original, not_matched).",
    )
    p.add_argument("--temperature", type=float, default=0.05)
    p.add_argument("--num-ctx", type=int, default=32768)
    p.add_argument("--num-predict", type=int, default=8192)
    p.add_argument("--dry-run", action="store_true", help="Nur Prompt bauen, kein LLM.")
    p.add_argument("--save-prompt", type=str, default="", help="User-Prompt in Datei speichern.")
    args = p.parse_args()

    if args.input:
        transcription, original, not_matched = load_sm2_excel(Path(args.input))
        default_out = _REVIEW_DIR / "output" / "test1175_overlap_review.xlsx"
    else:
        case = build_case()
        transcription = case.transcription.copy()
        original = case.original.copy()
        not_matched = case.not_matched.copy()
        default_out = _REVIEW_DIR / "output" / "izzy_stede_overlap_review.xlsx"

    if args.max_rows and args.max_rows > 0:
        transcription = transcription.iloc[: args.max_rows].copy()
        # Original/NOT_MATCHED nur aus dem Slice neu ableiten (sonst riesiger Prompt)
        tmp = _REVIEW_DIR / "output" / "_slice_tmp.xlsx"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        transcription.to_excel(tmp, index=False)
        transcription, original, not_matched = load_sm2_excel(tmp)
        try:
            tmp.unlink()
        except OSError:
            pass

    if args.export_case:
        export_path = Path(args.export_case)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(export_path, engine="openpyxl") as writer:
            transcription.to_excel(writer, sheet_name="transcription", index=False)
            original.to_excel(writer, sheet_name="original", index=False)
            not_matched.to_excel(writer, sheet_name="not_matched", index=False)
        print(f"[OK] Case-Excel: {export_path}")

    trans_rows, orig_rows, unmatched_rows = _build_lists(transcription, original, not_matched)
    n_trans, n_orig, n_unmatched = len(trans_rows), len(orig_rows), len(unmatched_rows)

    user_prompt = build_user_prompt(
        n_trans=n_trans,
        n_orig=n_orig,
        n_unmatched=n_unmatched,
        transcription_block=_format_trans_block(trans_rows),
        original_block=_format_orig_block(orig_rows),
        not_matched_block=_format_orig_block(unmatched_rows),
    )

    if args.save_prompt:
        Path(args.save_prompt).write_text(user_prompt, encoding="utf-8")
        print(f"[OK] Prompt gespeichert: {args.save_prompt}")

    if args.dry_run:
        print(
            f"[DRY-RUN] trans={n_trans} orig={n_orig} not_matched={n_unmatched} "
            f"chars={len(user_prompt)}"
        )
        print(user_prompt[:2500] + ("\n…" if len(user_prompt) > 2500 else ""))
        return 0

    client = build_client_from_env()
    model = getattr(client, "model", "?")
    print(f"[START] model={model} trans={n_trans} orig={n_orig} not_matched={n_unmatched}")

    t0 = time.time()
    raw = ""
    out_path = Path(args.output) if args.output else default_out
    dump = out_path.with_name(out_path.stem + "_raw.txt")
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
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_excel(out_path, index=False)

    n_flagged = int((df_out["Flagged"] == "yes").sum())
    print(f"[DONE] {out_path} rows={len(df_out)} flagged={n_flagged}")
    print(f"[DONE] elapsed={time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
