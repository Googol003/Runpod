from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from llm_clients import build_client_from_env, parse_json_response, LLMError, OllamaClient
from prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, BATCH_USER_PROMPT_TEMPLATE

_NV_SMI_CACHE_TS = 0.0
_NV_SMI_CACHE_VAL = ""


def _nvidia_smi_summary() -> str:
    """Kurzinfo erste GPU (gecached, damit nvidia-smi nicht zu oft läuft)."""
    global _NV_SMI_CACHE_TS, _NV_SMI_CACHE_VAL
    now = time.time()
    if _NV_SMI_CACHE_TS > 0.0 and now - _NV_SMI_CACHE_TS < 3.0:
        return _NV_SMI_CACHE_VAL
    _NV_SMI_CACHE_TS = now
    exe = shutil.which("nvidia-smi")
    if not exe:
        _NV_SMI_CACHE_VAL = ""
        return ""
    try:
        cp = subprocess.run(
            [
                exe,
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=1.2,
        )
        if cp.returncode != 0 or not (cp.stdout or "").strip():
            _NV_SMI_CACHE_VAL = ""
            return ""
        line = (cp.stdout or "").strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            util, used, total = parts[0], parts[1], parts[2]
            _NV_SMI_CACHE_VAL = f"gpu={util}% vram={used}/{total}MiB"
        else:
            _NV_SMI_CACHE_VAL = ""
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        _NV_SMI_CACHE_VAL = ""
    return _NV_SMI_CACHE_VAL


def format_resource_usage() -> str:
    """CPU/RAM dieses Prozesses + optional erste NVIDIA-GPU."""
    chunks: List[str] = []
    try:
        import psutil

        chunks.append(f"cpu={psutil.cpu_percent(interval=None):.0f}%")
        v = psutil.virtual_memory()
        chunks.append(f"ram={v.percent:.0f}%")
        rss = psutil.Process(os.getpid()).memory_info().rss / 1024**2
        chunks.append(f"rss={rss:.0f}MiB")
    except Exception:
        chunks.append("cpu=na ram=na rss=na")
    gpu = _nvidia_smi_summary()
    if gpu:
        chunks.append(gpu)
    return " ".join(chunks)


def _prime_cpu_percent_sample() -> None:
    try:
        import psutil

        psutil.cpu_percent(interval=0.08)
    except Exception:
        pass


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


_DISALLOWED_REASON_RE = re.compile(
    r"(ergänz|hinzufüg|auffüll|vollständ|unvollständig|zusatz|fehlende\s+wörter?)",
    re.IGNORECASE,
)


def _reason_disallowed(reason: str) -> bool:
    return bool(_DISALLOWED_REASON_RE.search(reason or ""))


def _apply_corrections_to_text(original: str, corrections: List[Dict[str, str]]) -> str:
    """
    Best-effort: wenn das Modell corrections liefert, aber corrected_dialogue unverändert lässt,
    versuchen wir die from->to Ersetzungen direkt auf den Originaltext anzuwenden.
    """
    out = original
    for c in corrections:
        frm = str(c.get("from", ""))
        to = str(c.get("to", ""))
        if not frm or normalize_ws(frm) == normalize_ws(to):
            continue
        if frm in out:
            out = out.replace(frm, to, 1)
    return out


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
        kind_raw = str(c.get("kind", "")).strip().upper()
        # Nur phonetische Transkriptions-/Schreibfehler; Legacy ALTERNATIVE_WORD wie MISSPELLING behandeln.
        kind = "MISSPELLING" if kind_raw in ("MISSPELLING", "ALTERNATIVE_WORD", "") else ""
        out.append(
            {
                "from": frm,
                "to": to,
                "reason": str(c.get("reason", "")),
                "kind": kind,
            }
        )
    return out


def stringify(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return str(val)


def _coerce_single_row_dict(data: Dict[str, Any]) -> Dict[str, Any] | None:
    """
    Einzelantwort: entweder flaches Objekt mit leave_unchanged/corrected_dialogue
    oder fälschlich {"items":[{...}]}. Mehrere items → nicht eindeutig → None.
    """
    items = data.get("items")
    if isinstance(items, list):
        if len(items) == 1 and isinstance(items[0], dict):
            return items[0]
        return None
    if "leave_unchanged" in data or "corrected_dialogue" in data:
        return data
    return None


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
    p.add_argument("--kind-col", default="Correction Kind", help="Neue Spalte: Kategorie der übernommenen Korrektur.")
    p.add_argument("--decision-col", default="Decision", help="Neue Spalte: warum eine Zeile (nicht) korrigiert wurde.")
    p.add_argument("--max-rows", type=int, default=0, help="Optional: max Zeilen (0=alle)")
    p.add_argument("--log-every", type=int, default=25, help="Progress-Log alle N Zeilen (0=aus)")
    p.add_argument("--workers", type=int, default=1, help="Parallelität: batch = pro Matched-Text-Gruppe; single = pro Zeile.")
    p.add_argument("--num-ctx", type=int, default=8192, help="Ollama: num_ctx (größer = mehr Kontext, nutzt VRAM).")
    p.add_argument("--num-predict", type=int, default=1024, help="Ollama: num_predict (max Ausgabe-Tokens).")
    p.add_argument("--llm-item-col", default="LLM Item", help="Neue Spalte: LLM-JSON pro Zeile (falls verarbeitet).")
    p.add_argument(
        "--resource-log",
        choices=("off", "progress", "all"),
        default="progress",
        help="Auslastung: off | progress (START/PROGRESS/DONE) | all (+ pro fertigem LLM-Batch).",
    )
    p.add_argument(
        "--row-mode",
        choices=("batch", "single"),
        default="batch",
        help="batch = alle Zeilen mit gleichem Matched Text in einem LLM-Call (schnell, kann Details übersehen). "
        "single = eine Excel-Zeile pro LLM-Call (langsam, meist gründlicher; gut zum Testen).",
    )
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
    print(
        f"[START] rows={len(df)} dialogue_col='{dialogue_col}' matched_col='{matched_col}' "
        f"row_mode={args.row_mode} resource_log={args.resource_log}"
    )
    # optional warmup (nur für ollama client sinnvoll, aber schadet nicht)
    if hasattr(client, "warmup"):
        t0w = time.time()
        client.warmup()
        print(f"[WARMUP] done in {time.time() - t0w:.1f}s")
    if args.resource_log != "off":
        _prime_cpu_percent_sample()
        print(f"[START] res={format_resource_usage()}")

    corrected_values: List[str] = []
    corrections_values: List[str] = []
    kind_values: List[str] = []
    decision_values: List[str] = []
    llm_item_values: List[str] = []

    total = len(df) if args.max_rows <= 0 else min(len(df), args.max_rows)
    t0 = time.time()
    n_applied = 0  # Zeilen mit geändertem Text (übernommen)
    n_leave_unchanged = 0  # Modell: leave_unchanged=true
    n_failed = 0
    n_rejected_reason = 0  # Korrektur verworfen (Reason deutet Auffüllen/Ergänzen an)

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
            f"applied={n_applied} "
            f"unchanged={n_leave_unchanged} "
            f"rejected={n_rejected_reason} "
            f"errors={n_failed}"
            + (f" | res={format_resource_usage()}" if args.resource_log != "off" else "")
        )

    # prefill output arrays with originals
    corrected_values = [stringify(df.at[i, dialogue_col]) for i in range(len(df))]
    corrections_values = ["[]"] * len(df)
    kind_values = [""] * len(df)
    decision_values = [""] * len(df)
    llm_item_values = [""] * len(df)

    def _apply_parsed_item(ridx: int, original_dialogue: str, it: Dict[str, Any] | None) -> Tuple[int, int, int, int]:
        """Wendet ein geparstes LLM-Item auf eine Zeile an. Rückgabe (applied, unchanged, failed)."""
        if not it:
            decision_values[ridx] = "llm_missing_item"
            llm_item_values[ridx] = ""
            return (0, 0, 0, 1)
        leave_unchanged = bool(it.get("leave_unchanged", True))
        corrected = stringify(it.get("corrected_dialogue", original_dialogue))
        corrections = normalize_corrections_list(it.get("corrections", []))
        try:
            llm_item_values[ridx] = json.dumps(it, ensure_ascii=False)
        except Exception:
            llm_item_values[ridx] = ""

        if leave_unchanged:
            leave_reason = stringify(it.get("leave_reason", "")).strip()
            corrected_values[ridx] = original_dialogue
            corrections_values[ridx] = "[]"
            kind_values[ridx] = ""
            decision_values[ridx] = f"leave_unchanged:{leave_reason}" if leave_reason else "leave_unchanged"
            return (0, 1, 0, 0)

        # Hard safety: reject any correction that even hints at fill-in/addition in the reason.
        for c in corrections:
            if _reason_disallowed(str(c.get("reason", ""))):
                corrected_values[ridx] = original_dialogue
                corrections_values[ridx] = "[]"
                kind_values[ridx] = ""
                decision_values[ridx] = "rejected:reason_addition"
                return (0, 0, 1, 0)

        applied_here = 0
        if normalize_ws(corrected) == normalize_ws(original_dialogue) and corrections:
            corrected_auto = _apply_corrections_to_text(original_dialogue, corrections)
            if normalize_ws(corrected_auto) != normalize_ws(original_dialogue):
                corrected = corrected_auto

        if normalize_ws(corrected) != normalize_ws(original_dialogue):
            applied_here = 1

        corrected_values[ridx] = corrected
        try:
            if normalize_ws(corrected) == normalize_ws(original_dialogue):
                corrections_values[ridx] = "[]"
                kind_values[ridx] = ""
                decision_values[ridx] = "no_change"
            else:
                corrections_values[ridx] = json.dumps(corrections, ensure_ascii=False)
                kind_values[ridx] = "Falsche Schreibweise"
                decision_values[ridx] = "applied"
        except Exception:
            corrections_values[ridx] = "[]"
            kind_values[ridx] = ""
            decision_values[ridx] = "applied"
        return (applied_here, 0, 0, 0)

    def _chat_kwargs() -> Dict[str, Any]:
        if isinstance(client, OllamaClient):
            return {"options": {"num_ctx": int(args.num_ctx), "num_predict": int(args.num_predict)}}
        return {}

    def process_batch(row_indices: List[int], matched_text: str) -> Tuple[int, int, int, int]:
        """Returns (n_applied, n_leave_unchanged, n_rejected, n_failed) for this batch only."""
        batch_applied = 0
        batch_unchanged = 0
        batch_failed = 0
        batch_rejected = 0

        kept: List[Tuple[int, str]] = []
        for ridx in row_indices:
            dialogue = stringify(df.at[ridx, dialogue_col])
            kept.append((ridx, dialogue))

        if not kept:
            return (0, 0, 0, 0)

        # IMPORTANT: Always send ALL dialogues for this matched_text together in ONE request.
        dialogue_list = "\n".join([f"{j+1}. {d}" for j, (_, d) in enumerate(kept)])
        user_prompt = BATCH_USER_PROMPT_TEMPLATE.format(matched_text=matched_text, dialogue_list=dialogue_list)

        def _call_llm_batch() -> Tuple[Dict[str, Any] | None, str]:
            t_llm0 = time.perf_counter()
            raw = client.chat(SYSTEM_PROMPT, user_prompt, temperature=0.05, **_chat_kwargs())
            dt_llm = time.perf_counter() - t_llm0
            if args.resource_log == "all":
                print(f"[BATCH] lines={len(kept)} llm_s={dt_llm:.2f}s | {format_resource_usage()}")
            try:
                return parse_json_response(raw), raw
            except Exception:
                return None, raw

        last_raw = ""
        data: Dict[str, Any] | None = None
        for attempt in range(1, 3):
            try:
                data, last_raw = _call_llm_batch()
                if data is not None:
                    break
            except LLMError as e:
                last_raw = str(e)
            except Exception as e:
                last_raw = str(e)
            time.sleep(0.25 * attempt)

        if data is None or not isinstance(data, dict):
            if args.resource_log == "all":
                print(f"[BATCH] lines={len(kept)} FAILED | {format_resource_usage()}")
            batch_failed += len(kept)
            for ridx, _d in kept:
                decision_values[ridx] = "llm_bad_json"
                llm_item_values[ridx] = (last_raw or "")[:8000]
            return (0, 0, 0, batch_failed)

        items = data.get("items", [])

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
            a, u, r, f = _apply_parsed_item(ridx, original_dialogue, it)
            batch_applied += a
            batch_unchanged += u
            batch_failed += f
            batch_rejected += r

        return (batch_applied, batch_unchanged, batch_rejected, batch_failed)

    def process_one_row(ridx: int) -> Tuple[int, int, int, int]:
        """Ein LLM-Call pro Excel-Zeile (row_mode=single)."""
        matched_text = stringify(df.at[ridx, matched_col]).strip()
        original_dialogue = stringify(df.at[ridx, dialogue_col])
        user_prompt = USER_PROMPT_TEMPLATE.format(dialogue=original_dialogue, matched_text=matched_text)
        def _call_llm_row() -> Tuple[Dict[str, Any] | None, str]:
            t_llm0 = time.perf_counter()
            raw = client.chat(SYSTEM_PROMPT, user_prompt, temperature=0.05, **_chat_kwargs())
            dt_llm = time.perf_counter() - t_llm0
            if args.resource_log == "all":
                print(f"[ROW] ridx={ridx} llm_s={dt_llm:.2f}s | {format_resource_usage()}")
            try:
                return parse_json_response(raw), raw
            except Exception:
                return None, raw

        last_raw = ""
        data: Dict[str, Any] | None = None
        for attempt in range(1, 3):
            try:
                data, last_raw = _call_llm_row()
                if data is not None:
                    break
            except LLMError as e:
                last_raw = str(e)
            except Exception as e:
                last_raw = str(e)
            time.sleep(0.25 * attempt)

        if data is None or not isinstance(data, dict):
            decision_values[ridx] = "llm_bad_json"
            llm_item_values[ridx] = (last_raw or "")[:8000]
            corrected_values[ridx] = original_dialogue
            corrections_values[ridx] = "[]"
            return (0, 0, 0, 1)

        it = _coerce_single_row_dict(data) if isinstance(data, dict) else None
        if it is None:
            try:
                llm_item_values[ridx] = (
                    json.dumps(data, ensure_ascii=False)[:8000] if isinstance(data, dict) else ""
                )
            except Exception:
                llm_item_values[ridx] = ""
            decision_values[ridx] = "llm_bad_shape"
            corrected_values[ridx] = original_dialogue
            corrections_values[ridx] = "[]"
            return (0, 0, 0, 1)
        a, u, r, f = _apply_parsed_item(ridx, original_dialogue, it)
        return (a, u, r, f)

    from concurrent.futures import ThreadPoolExecutor, as_completed

    if args.row_mode == "single":
        print(f"[START] row_mode=single llm_calls={total} (eine Zeile pro Request, workers={int(args.workers)})")
        if int(args.workers) <= 1:
            for ridx in range(total):
                a, u, r, f = process_one_row(ridx)
                n_applied += a
                n_leave_unchanged += u
                n_rejected_reason += r
                n_failed += f
                _progress(ridx + 1)
        else:
            with ThreadPoolExecutor(max_workers=int(args.workers)) as ex:
                futures = {ex.submit(process_one_row, ridx): ridx for ridx in range(total)}
                done_rows = 0
                for fut in as_completed(futures):
                    a, u, r, f = fut.result()
                    n_applied += a
                    n_leave_unchanged += u
                    n_rejected_reason += r
                    n_failed += f
                    done_rows += 1
                    _progress(done_rows)
    else:
        # group rows by matched_text to maximize name spelling reuse + batching
        groups: Dict[str, List[int]] = {}
        for i in range(total):
            matched = stringify(df.at[i, matched_col]).strip()
            groups.setdefault(matched, []).append(i)

        print(
            f"[START] row_mode=batch llm_batches={len(groups)} "
            f"(ein Call pro identischem Matched Text, workers={int(args.workers)})"
        )

        group_items = list(groups.items())

        def run_group(matched_text: str, idxs: List[int]) -> Tuple[Tuple[int, int, int, int], int]:
            counts = process_batch(idxs, matched_text)
            return counts, len(idxs)

        if int(args.workers) <= 1:
            done_rows = 0
            for matched_text, idxs in group_items:
                (a, u, r, f), n = run_group(matched_text, idxs)
                n_applied += a
                n_leave_unchanged += u
                n_rejected_reason += r
                n_failed += f
                done_rows += n
                _progress(min(done_rows, total))
        else:
            done_rows = 0
            with ThreadPoolExecutor(max_workers=int(args.workers)) as ex:
                futures = [ex.submit(run_group, mt, idxs) for mt, idxs in group_items]
                for fut in as_completed(futures):
                    (a, u, r, f), n = fut.result()
                    n_applied += a
                    n_leave_unchanged += u
                    n_rejected_reason += r
                    n_failed += f
                    done_rows += n
                    _progress(min(done_rows, total))

    # Restliche Zeilen (falls max_rows) unverändert übernehmen ist bereits abgedeckt (prefill)

    df_out = df.copy()
    df_out[args.corrected_col] = corrected_values
    df_out[args.corrections_col] = corrections_values
    df_out[args.kind_col] = kind_values
    df_out[args.decision_col] = decision_values
    df_out[args.llm_item_col] = llm_item_values
    df_out.to_excel(out_path, index=False)

    elapsed = time.time() - t0
    print(f"[DONE] written={out_path}")
    print(
        f"[DONE] processed={total} applied={n_applied} "
        f"unchanged={n_leave_unchanged} rejected={n_rejected_reason} errors={n_failed} elapsed={elapsed:.1f}s"
        + (f" | res={format_resource_usage()}" if args.resource_log != "off" else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

