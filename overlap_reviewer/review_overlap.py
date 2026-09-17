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


def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    """Fortschritt wie beim Excel-Corrector — sofort sichtbar auf RunPod."""
    print(f"[{_ts()}] {msg}", flush=True)


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _cell(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if s.lower() in ("nan", "none"):
        return ""
    return s


def _normalize_matched_ref_timecodes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Gleiches MATCHED-TEXT (+ SOURCE) → dieselben REF-IN/REF-OUT.
    Kanonisch: frühester REF-IN und spätester REF-OUT der Gruppe
    (fällt auf Transkript-TC zurück, wenn REF fehlt).
    """
    out = df.copy()
    if "REF-IN" not in out.columns:
        out["REF-IN"] = ""
    if "REF-OUT" not in out.columns:
        out["REF-OUT"] = ""

    canon: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for _, row in out.iterrows():
        mat = normalize_ws(_cell(row.get("MATCHED-TEXT")))
        if not mat:
            continue
        src = _cell(row.get("SOURCE")).upper()
        key = (src, mat)
        tin = _cell(row.get("REF-IN")) or _cell(row.get("TIMECODE-IN"))
        tout = _cell(row.get("REF-OUT")) or _cell(row.get("TIMECODE-OUT"))
        if not tin and not tout:
            continue
        if key not in canon:
            canon[key] = (tin, tout)
        else:
            cur_in, cur_out = canon[key]
            new_in = tin if (tin and (not cur_in or tin < cur_in)) else cur_in
            new_out = tout if (tout and (not cur_out or tout > cur_out)) else cur_out
            canon[key] = (new_in, new_out)

    for i, row in out.iterrows():
        mat = normalize_ws(_cell(row.get("MATCHED-TEXT")))
        if not mat:
            continue
        key = (_cell(row.get("SOURCE")).upper(), mat)
        if key in canon:
            out.at[i, "REF-IN"] = canon[key][0]
            out.at[i, "REF-OUT"] = canon[key][1]
    return out


def load_original_script_csv(path: Path) -> pd.DataFrame:
    """
    Original-Drehbuch-CSV (Semikolon), Dateireihenfolge = Script-Reihenfolge.
    Erwartet Spalten: Source, Text, Startzeit/Endzeit (oder In/Out).
    """
    last_err: Optional[Exception] = None
    df: Optional[pd.DataFrame] = None
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin1"):
        try:
            df = pd.read_csv(path, sep=";", encoding=enc)
            break
        except Exception as e:  # noqa: BLE001 — Encoding-Probe
            last_err = e
            df = None
    if df is None:
        raise ValueError(f"Original-CSV nicht lesbar ({path}): {last_err}")

    colmap = {str(c).strip().lower(): c for c in df.columns}

    def _col(*names: str) -> Optional[str]:
        for n in names:
            if n.lower() in colmap:
                return colmap[n.lower()]
        return None

    c_src = _col("Source", "SOURCE", "Speaker", "SPEAKER")
    c_txt = _col("Text", "TEXT", "Dialogue", "DIALOGUE")
    c_in = _col("Startzeit", "In", "TIMECODE-IN", "timecode_in")
    c_out = _col("Endzeit", "Out", "TIMECODE-OUT", "timecode_out")
    if not c_src or not c_txt:
        raise ValueError(f"Original-CSV braucht Source+Text: {path} cols={list(df.columns)}")

    rows: List[Dict[str, str]] = []
    for _, row in df.iterrows():
        src = _cell(row.get(c_src))
        dialogue = _cell(row.get(c_txt))
        if not src and not dialogue:
            continue
        if not src:
            continue
        tin = _cell(row.get(c_in)) if c_in else ""
        tout = _cell(row.get(c_out)) if c_out else ""
        rows.append(
            {
                "timecode_in": tin,
                "timecode_out": tout,
                "source": src,
                "dialogue": dialogue,
            }
        )
    if not rows:
        raise ValueError(f"Original-CSV ohne Dialogzeilen: {path}")
    return pd.DataFrame(rows)


def _transcription_tc_window(transcription: pd.DataFrame) -> Tuple[str, str]:
    """Min/Max Timecode aus REF- und TRANSCRIPT-TCs (für Original-Fenster)."""
    vals_in: List[str] = []
    vals_out: List[str] = []
    for _, row in transcription.iterrows():
        for c in ("REF-IN", "TIMECODE-IN", "MATCHED-TEXT-IN"):
            v = _cell(row.get(c))
            if v:
                vals_in.append(v)
        for c in ("REF-OUT", "TIMECODE-OUT", "MATCHED-TEXT-OUT"):
            v = _cell(row.get(c))
            if v:
                vals_out.append(v)
    if not vals_in or not vals_out:
        return "", ""
    return min(vals_in), max(vals_out)


def filter_original_by_window(
    original: pd.DataFrame,
    tc_lo: str,
    tc_hi: str,
    *,
    pad_before: str = "00:00:15:00",
    pad_after: str = "00:00:15:00",
) -> pd.DataFrame:
    """
    Schneidet Original auf das Transkript-Zeitfenster (Datei-Reihenfolge bleibt).
    pad_* sind relative Dauern HH:MM:SS:FF die vom Fenster abgezogen/addiert werden.
    """
    if original.empty or not tc_lo or not tc_hi:
        return original

    def _tc_to_frames(tc: str) -> Optional[int]:
        parts = (tc or "").strip().split(":")
        if len(parts) != 4 or not all(p.isdigit() for p in parts):
            return None
        h, m, s, f = (int(x) for x in parts)
        return ((h * 60 + m) * 60 + s) * 25 + f

    def _frames_to_tc(n: int) -> str:
        if n < 0:
            n = 0
        f = n % 25
        n //= 25
        s = n % 60
        n //= 60
        m = n % 60
        h = n // 60
        return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"

    lo_f = _tc_to_frames(tc_lo)
    hi_f = _tc_to_frames(tc_hi)
    if lo_f is None or hi_f is None:
        return original
    pad_lo = _tc_to_frames(pad_before) or 0
    pad_hi = _tc_to_frames(pad_after) or 0
    win_lo = _frames_to_tc(lo_f - pad_lo)
    win_hi = _frames_to_tc(hi_f + pad_hi)

    keep_idx: List[Any] = []
    for i, row in original.iterrows():
        tin = _cell(row.get("timecode_in"))
        tout = _cell(row.get("timecode_out")) or tin
        if not tin:
            keep_idx.append(i)
            continue
        # Overlap: start <= win_hi AND end >= win_lo
        if tin <= win_hi and tout >= win_lo:
            keep_idx.append(i)
    return original.loc[keep_idx].reset_index(drop=True)


def load_sm2_excel(
    path: Path,
    *,
    original_override: Optional[pd.DataFrame] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    SM2-Ergebnis-Excel:
    TIMECODE-IN/OUT, DIALOGUE, SOURCE, MATCHED-TEXT, NOT_MATCHED,
    optional REF-IN/REF-OUT (Original-Timecodes zum Match).

    Wenn original_override gesetzt ist (z.B. aus Drehbuch-CSV), wird das als
    ORIGINAL genutzt — Dateireihenfolge bleibt erhalten.
    """
    df = pd.read_excel(path)
    if not isinstance(df, pd.DataFrame):
        df = pd.read_excel(path, sheet_name=0)

    need = ["TIMECODE-IN", "TIMECODE-OUT", "DIALOGUE", "SOURCE", "MATCHED-TEXT", "NOT_MATCHED"]
    for c in need:
        if c not in df.columns:
            raise ValueError(f"Spalte fehlt in {path}: {c}")

    cols = list(need)
    for opt in ("REF-IN", "REF-OUT", "MATCHED-TEXT-IN", "MATCHED-TEXT-OUT"):
        if opt in df.columns:
            cols.append(opt)
    transcription = df[cols].copy()
    if "REF-IN" not in transcription.columns and "MATCHED-TEXT-IN" in transcription.columns:
        transcription["REF-IN"] = transcription["MATCHED-TEXT-IN"]
    if "REF-OUT" not in transcription.columns and "MATCHED-TEXT-OUT" in transcription.columns:
        transcription["REF-OUT"] = transcription["MATCHED-TEXT-OUT"]
    if "REF-IN" not in transcription.columns:
        transcription["REF-IN"] = ""
    if "REF-OUT" not in transcription.columns:
        transcription["REF-OUT"] = ""

    # Gleicher MATCHED-TEXT (+ SOURCE) → gleiche REF-Timecodes (kanonisch: frühester IN, spätester OUT)
    transcription = _normalize_matched_ref_timecodes(transcription)

    unmatched_rows: List[Dict[str, str]] = []
    for _, row in transcription.iterrows():
        nm = _cell(row.get("NOT_MATCHED"))
        if not nm:
            continue
        flat = nm.replace("\n", " ")
        matches = list(_NOT_MATCHED_RE.finditer(flat))
        if matches:
            for m in matches:
                tin, tout, speaker, dialogue = (
                    m.group(1),
                    m.group(2),
                    m.group(3).strip(),
                    m.group(4).strip(),
                )
                dialogue = dialogue.split("|")[0].strip()
                unmatched_rows.append(
                    {
                        "timecode_in": tin,
                        "timecode_out": tout,
                        "source": speaker,
                        "dialogue": dialogue,
                    }
                )
        else:
            unmatched_rows.append(
                {
                    "timecode_in": _cell(row.get("TIMECODE-IN")),
                    "timecode_out": _cell(row.get("TIMECODE-OUT")),
                    "source": "?",
                    "dialogue": nm[:200],
                }
            )

    def _tc_key(r: Dict[str, str]) -> str:
        return r.get("timecode_in") or ""

    unmatched_rows.sort(key=_tc_key)
    not_matched = pd.DataFrame(unmatched_rows) if unmatched_rows else pd.DataFrame(
        columns=["timecode_in", "timecode_out", "source", "dialogue"]
    )

    if original_override is not None and not original_override.empty:
        original = original_override.copy().reset_index(drop=True)
        return transcription, original, not_matched

    # Fallback: Original aus Matches + NOT_MATCHED rekonstruieren
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
        ref_in = _cell(row.get("REF-IN")) or _cell(row.get("TIMECODE-IN"))
        ref_out = _cell(row.get("REF-OUT")) or _cell(row.get("TIMECODE-OUT"))
        orig_rows.append(
            {
                "timecode_in": ref_in,
                "timecode_out": ref_out,
                "source": src,
                "dialogue": mat,
            }
        )
    for entry in unmatched_rows:
        key = (entry["source"].upper(), normalize_ws(entry["dialogue"]))
        if key not in seen:
            seen.add(key)
            orig_rows.append(entry)

    orig_rows.sort(key=_tc_key)
    original = pd.DataFrame(orig_rows) if orig_rows else pd.DataFrame(
        columns=["timecode_in", "timecode_out", "source", "dialogue"]
    )
    return transcription, original, not_matched


def _tc_norm(tc: str) -> str:
    s = (tc or "").strip()
    if len(s) >= 3 and s[2] == ":" and s[:2].isdigit():
        return "00" + s[2:]
    return s


def _format_trans_block(rows: List[Tuple[int, str, str, str, str, str, str, str]]) -> str:
    """idx, tc_in, tc_out, speaker, dialogue, matched_text, ref_in, ref_out"""
    lines: List[str] = []
    for idx, tc_in, tc_out, speaker, dialogue, matched, ref_in, ref_out in rows:
        sp = speaker if speaker else "(kein Sprecher / unmatched)"
        if matched:
            if ref_in or ref_out:
                mt = (
                    f"[{_tc_norm(ref_in)} – {_tc_norm(ref_out)}] {matched}"
                )
            else:
                mt = matched
        else:
            mt = "(kein MATCHED-TEXT)"
        lines.append(
            f"{idx}. TRANSCRIPT-TC [{_tc_norm(tc_in)} – {_tc_norm(tc_out)}] "
            f"SPEAKER={sp!r} | DIALOGUE={dialogue!r} | "
            f"MATCHED-TEXT + ORIGINAL-TC={mt!r}"
        )
    return "\n".join(lines)


def _format_orig_block(
    rows: List[Tuple[int, str, str, str, str]],
    *,
    unmatched_keys: Optional[set] = None,
) -> str:
    lines: List[str] = []
    unmatched_keys = unmatched_keys or set()
    for idx, tc_in, tc_out, speaker, dialogue in rows:
        key = (speaker.upper(), normalize_ws(dialogue))
        tag = " [NOT_MATCHED]" if key in unmatched_keys else ""
        lines.append(
            f"{idx}. [{_tc_norm(tc_in)} – {_tc_norm(tc_out)}] "
            f"SPEAKER={speaker!r} | {dialogue}{tag}"
        )
    return "\n".join(lines)


def _build_lists(
    transcription: pd.DataFrame,
    original: pd.DataFrame,
    not_matched: pd.DataFrame,
) -> Tuple[
    List[Tuple[int, str, str, str, str, str, str, str]],
    List[Tuple[int, str, str, str, str]],
    List[Tuple[int, str, str, str, str]],
]:
    trans_rows: List[Tuple[int, str, str, str, str, str, str, str]] = []
    for _, row in transcription.iterrows():
        trans_rows.append(
            (
                len(trans_rows) + 1,
                _cell(row.get("TIMECODE-IN", row.get("timecode_in", ""))),
                _cell(row.get("TIMECODE-OUT", row.get("timecode_out", ""))),
                _cell(row.get("SOURCE", row.get("SPEAKER", ""))),
                _cell(row.get("DIALOGUE", row.get("dialogue", ""))),
                _cell(row.get("MATCHED-TEXT", row.get("Matched Text", ""))),
                _cell(row.get("REF-IN", row.get("MATCHED-TEXT-IN", ""))),
                _cell(row.get("REF-OUT", row.get("MATCHED-TEXT-OUT", ""))),
            )
        )

    orig_rows: List[Tuple[int, str, str, str, str]] = []
    for _, row in original.iterrows():
        orig_rows.append(
            (
                len(orig_rows) + 1,
                _cell(row.get("timecode_in", row.get("TIMECODE-IN", ""))),
                _cell(row.get("timecode_out", row.get("TIMECODE-OUT", ""))),
                _cell(row.get("source", row.get("SOURCE", row.get("SPEAKER", "")))),
                _cell(row.get("dialogue", row.get("DIALOGUE", ""))),
            )
        )

    unmatched_rows: List[Tuple[int, str, str, str, str]] = []
    for _, row in not_matched.iterrows():
        unmatched_rows.append(
            (
                len(unmatched_rows) + 1,
                _cell(row.get("timecode_in", row.get("TIMECODE-IN", ""))),
                _cell(row.get("timecode_out", row.get("TIMECODE-OUT", ""))),
                _cell(row.get("source", row.get("SOURCE", row.get("SPEAKER", "")))),
                _cell(row.get("dialogue", row.get("DIALOGUE", ""))),
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


def _parse_reviews(
    data: Dict[str, Any],
    expected_ids: List[int],
    n_orig: int,
) -> Dict[int, Dict[str, Any]]:
    raw = data.get("reviews")
    if not isinstance(raw, list):
        raise ValueError("JSON ohne 'reviews'-Liste")

    expected = set(expected_ids)
    by_trans: Dict[int, Dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            ti = int(item.get("trans_i"))
        except (TypeError, ValueError):
            continue
        if ti not in expected:
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

    if len(by_trans) != len(expected):
        missing = [i for i in expected_ids if i not in by_trans]
        raise ValueError(
            f"reviews: erwartet {len(expected)} trans_i, bekam {len(by_trans)}; "
            f"fehlend={missing[:10]}"
        )
    return by_trans


def _chunk_rows(
    rows: List[Tuple[int, str, str, str, str, str, str, str]],
    batch_size: int,
) -> List[List[Tuple[int, str, str, str, str, str, str, str]]]:
    if batch_size <= 0 or batch_size >= len(rows):
        return [rows]
    return [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]


def _reviews_to_dataframe(
    trans_rows: List[Tuple[int, str, str, str, str, str, str, str]],
    orig_rows: List[Tuple[int, str, str, str, str]],
    by_trans: Dict[int, Dict[str, Any]],
) -> pd.DataFrame:
    orig_by_idx = {r[0]: r for r in orig_rows}
    out_rows: List[Dict[str, Any]] = []

    for ti, tc_in, tc_out, speaker, dialogue, matched, ref_in, ref_out in trans_rows:
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
                "REF-IN": ref_in,
                "REF-OUT": ref_out,
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
        default=str(_REVIEW_DIR / "testdata" / "test.1175.xlsx"),
        help="SM2-Excel (TIMECODE-IN/OUT, DIALOGUE, SOURCE, MATCHED-TEXT, REF-IN/OUT, NOT_MATCHED). "
        "Default: testdata/test.1175.xlsx (sauber, ohne Test-Injects). Mit --case izzy den Mini-Case nutzen.",
    )
    p.add_argument(
        "--case",
        choices=("excel", "izzy"),
        default="excel",
        help="excel = Default-Test-Excel; izzy = eingebauter Mini-Case ohne Datei.",
    )
    p.add_argument(
        "--original",
        default=str(_REVIEW_DIR / "testdata" / "CsvOurFlagMeansDeath201.csv"),
        help="Original-Drehbuch-CSV (Semikolon, Dateireihenfolge). "
        "Default: testdata/CsvOurFlagMeansDeath201.csv. Leer = aus Matches rekonstruieren.",
    )
    p.add_argument(
        "--original-full",
        action="store_true",
        help="Gesamtes Original-CSV ins Prompt (sonst nur Zeitfenster der Transkription ±15s).",
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
        "--batch-size",
        type=int,
        default=25,
        help="Transkript-Zeilen pro LLM-Call (Default 25). 0 = alles in einem Call "
        "(riskant: JSON wird oft abgeschnitten).",
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
    p.add_argument("--no-warmup", action="store_true", help="LLM-Warmup überspringen.")
    args = p.parse_args()

    t_all = time.time()
    log("[START] overlap_reviewer")

    original_csv_path = Path(args.original) if str(args.original).strip() else None
    original_full_script: Optional[pd.DataFrame] = None
    use_izzy = args.case == "izzy"
    if original_csv_path and not use_izzy:
        if original_csv_path.is_file():
            log(f"[LOAD] Original-Script CSV: {original_csv_path}")
            t0 = time.time()
            original_full_script = load_original_script_csv(original_csv_path)
            log(
                f"[LOAD] original CSV done in {time.time() - t0:.2f}s | "
                f"lines={len(original_full_script)} (Datei-Reihenfolge)"
            )
        else:
            log(f"[WARN] --original nicht gefunden, Fallback Matches: {original_csv_path}")
            original_csv_path = None

    if use_izzy:
        log("[LOAD] embedded izzy_stede_overlap_case (--case izzy)")
        t0 = time.time()
        case = build_case()
        transcription = case.transcription.copy()
        original = case.original.copy()
        not_matched = case.not_matched.copy()
        log(
            f"[LOAD] done in {time.time() - t0:.2f}s | "
            f"trans={len(transcription)} orig={len(original)} not_matched={len(not_matched)}"
        )
        default_out = _REVIEW_DIR / "output" / "izzy_stede_overlap_review.xlsx"
    else:
        in_path = Path(args.input)
        if not in_path.is_file():
            log(f"[ERROR] Input-Excel fehlt: {in_path}")
            log("[ERROR] Erwartet z.B. overlap_reviewer/testdata/test.1175.injected.xlsx (im Repo).")
            return 2
        log(f"[LOAD] Excel: {in_path}")
        t0 = time.time()
        transcription, original, not_matched = load_sm2_excel(
            in_path,
            original_override=original_full_script,
        )
        log(
            f"[LOAD] done in {time.time() - t0:.2f}s | "
            f"trans={len(transcription)} orig={len(original)} not_matched={len(not_matched)}"
        )
        default_out = _REVIEW_DIR / "output" / "test1175_overlap_review.xlsx"

    if args.max_rows and args.max_rows > 0:
        log(f"[SLICE] max-rows={args.max_rows} (vorher trans={len(transcription)})")
        t0 = time.time()
        transcription = transcription.iloc[: args.max_rows].copy()
        tmp = _REVIEW_DIR / "output" / "_slice_tmp.xlsx"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        transcription.to_excel(tmp, index=False)
        transcription, original, not_matched = load_sm2_excel(
            tmp,
            original_override=original_full_script,
        )
        try:
            tmp.unlink()
        except OSError:
            pass
        log(
            f"[SLICE] done in {time.time() - t0:.2f}s | "
            f"trans={len(transcription)} orig={len(original)} not_matched={len(not_matched)}"
        )

    # Original auf Transkript-Zeitfenster schneiden (Reihenfolge bleibt), außer --original-full / izzy
    if original_full_script is not None and not args.original_full and not use_izzy:
        tc_lo, tc_hi = _transcription_tc_window(transcription)
        before = len(original)
        original = filter_original_by_window(original_full_script, tc_lo, tc_hi)
        log(
            f"[ORIG-WINDOW] {tc_lo} - {tc_hi} (+/-15s) -> "
            f"orig {before} -> {len(original)} (Script-Reihenfolge)"
        )
    elif original_full_script is not None and args.original_full:
        original = original_full_script.copy().reset_index(drop=True)
        log(f"[ORIG-FULL] gesamtes Script | orig={len(original)}")

    if args.export_case:
        export_path = Path(args.export_case)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        log(f"[EXPORT] case → {export_path}")
        with pd.ExcelWriter(export_path, engine="openpyxl") as writer:
            transcription.to_excel(writer, sheet_name="transcription", index=False)
            original.to_excel(writer, sheet_name="original", index=False)
            not_matched.to_excel(writer, sheet_name="not_matched", index=False)
        log(f"[EXPORT] done")

    log("[BUILD] Listen + Prompt-Kontext (Original/NOT_MATCHED)")
    t0 = time.time()
    trans_rows, orig_rows, unmatched_rows = _build_lists(transcription, original, not_matched)
    n_trans, n_orig, n_unmatched = len(trans_rows), len(orig_rows), len(unmatched_rows)
    unmatched_keys = {
        (sp.upper(), normalize_ws(dlg)) for _, _, _, sp, dlg in unmatched_rows if sp and dlg
    }
    orig_block = _format_orig_block(orig_rows, unmatched_keys=unmatched_keys)
    nm_block = _format_orig_block(unmatched_rows)
    batches = _chunk_rows(trans_rows, args.batch_size)
    log(
        f"[BUILD] done in {time.time() - t0:.2f}s | "
        f"trans={n_trans} orig={n_orig} not_matched={n_unmatched} "
        f"batches={len(batches)} batch_size={args.batch_size or 'all'}"
    )

    if args.save_prompt:
        # ersten Batch als Beispiel speichern
        sample_ids = [r[0] for r in batches[0]]
        sample_prompt = build_user_prompt(
            n_trans=n_trans,
            n_orig=n_orig,
            n_unmatched=n_unmatched,
            transcription_block=_format_trans_block(batches[0]),
            original_block=orig_block,
            not_matched_block=nm_block,
            required_trans_ids=sample_ids,
        )
        Path(args.save_prompt).write_text(sample_prompt, encoding="utf-8")
        log(f"[OK] Prompt (Batch 1) gespeichert: {args.save_prompt}")

    if args.dry_run:
        sample_ids = [r[0] for r in batches[0]]
        sample_prompt = build_user_prompt(
            n_trans=n_trans,
            n_orig=n_orig,
            n_unmatched=n_unmatched,
            transcription_block=_format_trans_block(batches[0]),
            original_block=orig_block,
            not_matched_block=nm_block,
            required_trans_ids=sample_ids,
        )
        log(
            f"[DRY-RUN] trans={n_trans} orig={n_orig} not_matched={n_unmatched} "
            f"batches={len(batches)} batch1_chars={len(sample_prompt)}"
        )
        print(sample_prompt[:2500] + ("\n…" if len(sample_prompt) > 2500 else ""), flush=True)
        log(f"[DONE] dry-run total={time.time() - t_all:.1f}s")
        return 0

    log("[CLIENT] build_client_from_env")
    client = build_client_from_env()
    # Lange Batch-Läufe: Timeout mindestens 10 Min, falls Env kleiner
    if isinstance(client, OllamaClient) and getattr(client, "timeout_s", 180) < 600:
        client.timeout_s = 600
    model = getattr(client, "model", "?")
    provider = type(client).__name__
    base_url = getattr(client, "base_url", "?")
    log(f"[START] provider={provider} base_url={base_url} model={model}")
    log(f"[START] num_ctx={args.num_ctx} num_predict={args.num_predict} temperature={args.temperature}")

    if not args.no_warmup and hasattr(client, "warmup"):
        log("[WARMUP] starting…")
        t0w = time.time()
        try:
            client.warmup()
            log(f"[WARMUP] done in {time.time() - t0w:.1f}s")
        except Exception as e:
            log(f"[WARMUP] skipped/failed: {e}")

    out_path = Path(args.output) if args.output else default_out
    dump = out_path.with_name(out_path.stem + "_raw.txt")
    by_trans: Dict[int, Dict[str, Any]] = {}
    raw_parts: List[str] = []

    for bi, batch in enumerate(batches, start=1):
        ids = [r[0] for r in batch]
        user_prompt = build_user_prompt(
            n_trans=n_trans,
            n_orig=n_orig,
            n_unmatched=n_unmatched,
            transcription_block=_format_trans_block(batch),
            original_block=orig_block,
            not_matched_block=nm_block,
            required_trans_ids=ids,
        )
        log(
            f"[LLM] batch {bi}/{len(batches)} starting "
            f"(trans_i {ids[0]}-{ids[-1]}, {len(ids)} rows, prompt_chars={len(user_prompt)}) "
            f"→ waiting…"
        )
        t0 = time.time()
        raw = ""
        try:
            raw = _call_llm(
                client,
                user_prompt,
                num_ctx=args.num_ctx,
                num_predict=args.num_predict,
                temperature=args.temperature,
            )
            dt_llm = time.time() - t0
            log(f"[LLM] batch {bi}/{len(batches)} done in {dt_llm:.1f}s | raw_chars={len(raw)}")
            raw_parts.append(f"===== BATCH {bi} trans_i={ids[0]}-{ids[-1]} =====\n{raw}\n")
            log(f"[PARSE] batch {bi}/{len(batches)}")
            t0p = time.time()
            data = parse_json_response(raw)
            part = _parse_reviews(data, ids, n_orig)
            by_trans.update(part)
            n_flagged_parse = sum(1 for v in part.values() if v.get("flagged"))
            log(
                f"[PARSE] batch {bi} done in {time.time() - t0p:.2f}s | "
                f"items={len(part)} flagged={n_flagged_parse}"
            )
        except (LLMError, json.JSONDecodeError, ValueError) as e:
            dump.parent.mkdir(parents=True, exist_ok=True)
            dump.write_text("\n".join(raw_parts) + (f"\n===== FAIL BATCH {bi} =====\n{raw}\n" if raw else ""), encoding="utf-8")
            log(f"[ERROR] raw dumped: {dump}")
            hint = ""
            err_s = str(e)
            if "Unterminated" in err_s or "Expecting" in err_s:
                hint = (
                    " | Hinweis: Antwort vermutlich abgeschnitten — "
                    "kleineres --batch-size oder höheres --num-predict"
                )
            log(f"[ERROR] batch {bi}/{len(batches)}: {e}{hint}")
            return 1

    if len(by_trans) != n_trans:
        missing = [i for i in range(1, n_trans + 1) if i not in by_trans]
        log(f"[ERROR] nach allen Batches fehlend: {missing[:20]}")
        return 1

    log("[WRITE] building Excel")
    t0 = time.time()
    df_out = _reviews_to_dataframe(trans_rows, orig_rows, by_trans)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_excel(out_path, index=False)
    n_flagged = int((df_out["Flagged"] == "yes").sum())
    by_type = df_out["Issue Type"].value_counts().to_dict() if "Issue Type" in df_out.columns else {}
    log(f"[WRITE] done in {time.time() - t0:.2f}s → {out_path}")
    log(f"[DONE] rows={len(df_out)} flagged={n_flagged} issue_types={by_type}")
    log(f"[DONE] elapsed_total={time.time() - t_all:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
