from __future__ import annotations

import argparse
import json
import math
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from llm_clients import build_client_from_env, parse_json_response, LLMError
from prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, BATCH_USER_PROMPT_TEMPLATE


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


def word_tokens(s: str) -> List[str]:
    return re.findall(r"\w+", normalize_ws(s).lower())


def token_ratio(a: str, b: str) -> float:
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

    # Anti-Synonym/Anti-Rewrite Check:
    # Wenn Tokens "sinnvoll" komplett ausgetauscht werden, verwerfen.
    # Erlaubt sind i.d.R. nur kleine Schreibkorrekturen oder Tokens, die direkt aus matched_text stammen.
    mt_set = set(word_tokens(matched_text))
    o_toks = word_tokens(o)
    c_toks = word_tokens(c)

    # If lengths are equal: check per-position replacements
    if len(o_toks) == len(c_toks) and len(o_toks) > 0:
        for ot, ct in zip(o_toks, c_toks):
            if ot == ct:
                continue
            # allow if very similar spelling (typo/ASR) OR corrected token exists in matched_text
            if token_ratio(ot, ct) >= 0.82:
                continue
            if ct in mt_set:
                continue
            return False, "rewrite_or_synonym_detected"
    else:
        # If tokenization differs, be stricter: corrected tokens must mostly come from original or matched_text
        o_set = set(o_toks)
        for ct in c_toks:
            if ct in o_set:
                continue
            if ct in mt_set:
                continue
            return False, "rewrite_or_synonym_detected"

    # Wenn matched_text offensichtlich nicht passt, lieber nichts tun
    ts = token_similarity(o, matched_text)
    if ts < 0.12:
        return False, "dialogue_matched_text_unrelated"

    return True, "ok"


def normalize_corrections_list(corrections: Any) -> List[Dict[str, str]]:
    """
    Entfernt No-op Einträge (from==to) und normalisiert das Format.
    """
    if not isinstance(corrections, list):
        return []
    out: List[Dict[str, str]] = []
    for c in corrections:
        if not isinstance(c, dict):
            continue
        frm = str(c.get("from", ""))
        to = str(c.get("to", ""))
        if normalize_ws(frm) == normalize_ws(to):
            continue
        out.append(
            {
                "from": frm,
                "to": to,
                "reason": str(c.get("reason", "")),
            }
        )
    return out


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
    p.add_argument("--log-every", type=int, default=25, help="Progress-Log alle N Zeilen (0=aus)")
    p.add_argument("--workers", type=int, default=1, help="Parallelisierung über Matched-Text-Gruppen (1=aus).")
    p.add_argument("--num-ctx", type=int, default=8192, help="Ollama: num_ctx (größer = mehr Kontext, nutzt VRAM).")
    p.add_argument("--num-predict", type=int, default=1024, help="Ollama: num_predict (max Ausgabe-Tokens).")
    args = p.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        raise SystemExit(f"Input nicht gefunden: {in_path}")

    out_path = Path(args.output) if args.output else in_path.with_name(f"{in_path.stem}_corrected.xlsx")

    df = pd.read_excel(in_path)
    dialogue_col = find_column(df, args.dialogue_col)
    matched_col = find_column(df, args.matched_col)

    client = build_client_from_env()
    provider = getattr(client, "__class__", type("x", (), {})).__name__
    model = getattr(client, "model", "?")
    base_url = getattr(client, "base_url", "?")
    print(f"[START] input={in_path}")
    print(f"[START] provider={provider} base_url={base_url} model={model}")
    print(f"[START] rows={len(df)} dialogue_col='{dialogue_col}' matched_col='{matched_col}'")
    # optional warmup (nur für ollama client sinnvoll, aber schadet nicht)
    if hasattr(client, "warmup"):
        t0w = time.time()
        client.warmup()
        print(f"[WARMUP] done in {time.time() - t0w:.1f}s")

    corrected_values: List[str] = []
    corrections_values: List[str] = []

    total = len(df) if args.max_rows <= 0 else min(len(df), args.max_rows)
    t0 = time.time()
    n_corrected = 0
    n_skipped_unrelated = 0
    n_skipped_lowconf = 0
    n_skipped_postcheck = 0
    n_failed = 0

    def _progress(i_done: int) -> None:
        if args.log_every <= 0:
            return
        if i_done <= 0:
            return
        if i_done % args.log_every != 0 and i_done != total:
            return
        elapsed = max(1e-6, time.time() - t0)
        rps = i_done / elapsed
        eta_s = (total - i_done) / rps if rps > 0 else 0.0
        print(
            f"[PROGRESS] {i_done}/{total} "
            f"({(i_done/total*100):.1f}%) "
            f"elapsed={elapsed:.1f}s "
            f"rate={rps:.2f} rows/s "
            f"eta={eta_s/60:.1f}m "
            f"corrected={n_corrected} "
            f"skips(unrelated={n_skipped_unrelated},lowconf={n_skipped_lowconf},post={n_skipped_postcheck}) "
            f"errors={n_failed}"
        )

    # group rows by matched_text to maximize name spelling reuse + batching
    groups: Dict[str, List[int]] = {}
    for i in range(total):
        matched = stringify(df.at[i, matched_col]).strip()
        groups.setdefault(matched, []).append(i)

    # prefill output arrays with originals
    corrected_values = [stringify(df.at[i, dialogue_col]) for i in range(len(df))]
    corrections_values = ["[]"] * len(df)

    def process_batch(row_indices: List[int], matched_text: str) -> None:
        nonlocal n_corrected, n_skipped_unrelated, n_skipped_lowconf, n_skipped_postcheck, n_failed

        # Build list and apply early skip per row (unrelated)
        kept: List[Tuple[int, str]] = []
        for ridx in row_indices:
            dialogue = stringify(df.at[ridx, dialogue_col])
            if token_similarity(dialogue, matched_text) < args.min_token_sim:
                n_skipped_unrelated += 1
                corrected_values[ridx] = dialogue
                corrections_values[ridx] = "[]"
            else:
                kept.append((ridx, dialogue))

        if not kept:
            return

        # IMPORTANT: Always send ALL dialogues for this matched_text together in ONE request.
        dialogue_list = "\n".join([f"{j+1}. {d}" for j, (_, d) in enumerate(kept)])
        user_prompt = BATCH_USER_PROMPT_TEMPLATE.format(matched_text=matched_text, dialogue_list=dialogue_list)

        try:
            chat_kwargs: Dict[str, Any] = {}
            # Ollama-specific options if supported
            if hasattr(client, "base_url"):
                chat_kwargs["options"] = {"num_ctx": int(args.num_ctx), "num_predict": int(args.num_predict)}
            raw = client.chat(SYSTEM_PROMPT, user_prompt, temperature=0.05, **chat_kwargs)
            data = parse_json_response(raw)
            items = data.get("items", [])
        except (LLMError, json.JSONDecodeError, ValueError):
            n_failed += len(kept)
            return

        # index by i
        by_i: Dict[int, Dict[str, Any]] = {}
        for it in items if isinstance(items, list) else []:
            try:
                ii = int(it.get("i"))
                by_i[ii] = it
            except Exception:
                continue

        for j, (ridx, original_dialogue) in enumerate(kept, start=1):
            it = by_i.get(j)
            if not it:
                n_failed += 1
                continue

            leave_unchanged = bool(it.get("leave_unchanged", True))
            confidence = str(it.get("confidence", "low")).lower().strip()
            corrected = stringify(it.get("corrected_dialogue", original_dialogue))
            corrections = normalize_corrections_list(it.get("corrections", []))

            if leave_unchanged or confidence != "high":
                n_skipped_lowconf += 1
                corrected_values[ridx] = original_dialogue
                corrections_values[ridx] = "[]"
                continue

            ok, _reason = safe_to_apply(original_dialogue, corrected, matched_text)
            if not ok:
                n_skipped_postcheck += 1
                corrected_values[ridx] = original_dialogue
                corrections_values[ridx] = "[]"
                continue

            if normalize_ws(corrected) != normalize_ws(original_dialogue):
                n_corrected += 1

            corrected_values[ridx] = corrected
            try:
                # If corrected dialogue is unchanged, don't store "no-op corrections"
                if normalize_ws(corrected) == normalize_ws(original_dialogue):
                    corrections_values[ridx] = "[]"
                else:
                    corrections_values[ridx] = json.dumps(corrections, ensure_ascii=False)
            except Exception:
                corrections_values[ridx] = "[]"

    # process groups (optionally parallel)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    group_items = list(groups.items())

    def run_group(matched_text: str, idxs: List[int]) -> int:
        # send the whole group in one go (see requirement)
        process_batch(idxs, matched_text)
        return len(idxs)

    if int(args.workers) <= 1:
        done_rows = 0
        for matched_text, idxs in group_items:
            done_rows += run_group(matched_text, idxs)
            _progress(min(done_rows, total))
    else:
        done_rows = 0
        with ThreadPoolExecutor(max_workers=int(args.workers)) as ex:
            futures = [ex.submit(run_group, mt, idxs) for mt, idxs in group_items]
            for fut in as_completed(futures):
                done_rows += int(fut.result() or 0)
                _progress(min(done_rows, total))

    # Restliche Zeilen (falls max_rows) unverändert übernehmen ist bereits abgedeckt (prefill)

    df_out = df.copy()
    df_out[args.corrected_col] = corrected_values
    df_out[args.corrections_col] = corrections_values
    df_out.to_excel(out_path, index=False)

    elapsed = time.time() - t0
    print(f"[DONE] written={out_path}")
    print(
        f"[DONE] processed={total} corrected={n_corrected} "
        f"skips(unrelated={n_skipped_unrelated},lowconf={n_skipped_lowconf},post={n_skipped_postcheck}) "
        f"errors={n_failed} elapsed={elapsed:.1f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

