"""Evaluate the receipt checker against receipts with known ground truth.

    python eval/receipts/evaluate.py                 # local LLM + rules (default)
    python eval/receipts/evaluate.py --rules-only    # rule-based extractor only
    python eval/receipts/evaluate.py --dir eval/receipts/real   # your own receipts (same truth.json format)

For each receipt: OCR -> extraction -> markup check, compared field by field with truth.json.
Writes eval/results/receipts_<mode>.json and prints a summary.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

from fairsend import fx
from fairsend.receipts import checker, extract, ocr

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
FIELDS = ["amount_sent", "send_currency", "fee", "exchange_rate", "amount_received", "receive_currency",
          "transfer_date"]


def field_correct(name: str, got, want) -> bool:
    if want is None:
        return got is None or name == "exchange_rate"   # receipts without a printed rate: anything derived is fine
    if got is None:
        return False
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        if name == "exchange_rate":
            # Accept the rate in either direction; the checker orients it against the mid-market rate.
            return min(abs(got - want) / want, abs(1 / got - want) / want) < 1e-3
        return abs(got - want) <= max(0.011, abs(want) * 1e-6)
    return str(got) == str(want)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=HERE / "synthetic")
    ap.add_argument("--rules-only", action="store_true")
    args = ap.parse_args()
    truths = json.loads((args.dir / "truth.json").read_text())
    rows = []
    for t in truths:
        t.setdefault("layout", "real")
        t.setdefault("format", Path(t["file"]).suffix.lstrip("."))
        t.setdefault("degradation", None)
        t.setdefault("mid_source", "truth.json")
        if "true_markup_pct" not in t:
            rate = t.get("exchange_rate") or t["amount_received"] / t["amount_sent"]
            rate = rate if abs(rate - t["mid_rate"]) < abs(1 / rate - t["mid_rate"]) else 1 / rate
            t["true_markup_pct"] = (t["mid_rate"] - rate) / t["mid_rate"] * 100
            t["true_markup_cost"] = t["amount_sent"] * t["true_markup_pct"] / 100
        start = time.time()
        data = (args.dir / t["file"]).read_bytes()
        o = ocr.extract_text(data)
        e = extract.extract(o.text, use_llm=not args.rules_only)
        per_field = {f: field_correct(f, getattr(e, f), t.get(f)) for f in FIELDS}
        # Markup error against the same mid-market rate the truth used, isolating extraction error.
        mid = fx.Rate(t["send_currency"], t["receive_currency"], t["mid_rate"],
                      dt.date.fromisoformat(t["mid_rate_date"]), t["mid_source"])
        try:
            c = checker.check_fields(e, mid_rate=mid if e.send_currency == t["send_currency"]
                                     and e.receive_currency == t["receive_currency"] else None)
            markup, markup_cost = c.markup_pct, c.markup_cost
        except (checker.IncompleteReceipt, fx.RateUnavailable, ValueError, ZeroDivisionError):
            markup = markup_cost = None
        rows.append({
            "id": t["id"], "layout": t["layout"], "format": t["format"], "degradation": t["degradation"],
            "ocr_method": o.method, "extraction_method": e.method, "seconds": round(time.time() - start, 1),
            "fields": per_field, "all_fields_correct": all(per_field.values()),
            "true_markup_pct": t["true_markup_pct"], "markup_pct": markup,
            "markup_abs_error_pts": None if markup is None else abs(markup - t["true_markup_pct"]),
            "markup_cost_abs_error": None if markup_cost is None else abs(markup_cost - t["true_markup_cost"]),
            "extracted": {f: getattr(e, f) for f in FIELDS},
        })
        r = rows[-1]
        print(f"{t['id']} {t['layout']:8} {t['format']:8} fields {sum(per_field.values())}/{len(FIELDS)} "
              f"markup err {r['markup_abs_error_pts'] if r['markup_abs_error_pts'] is None else round(r['markup_abs_error_pts'], 3)} "
              f"({r['seconds']}s)")

    n = len(rows)
    field_acc = {f: sum(r["fields"][f] for r in rows) / n for f in FIELDS}
    errs = [r["markup_abs_error_pts"] for r in rows if r["markup_abs_error_pts"] is not None]
    summary = {
        "mode": "rules" if args.rules_only else "llm+rules", "receipts": n, "dataset": str(args.dir.name),
        "field_accuracy": field_acc,
        "overall_field_accuracy": sum(sum(r["fields"].values()) for r in rows) / (n * len(FIELDS)),
        "receipts_all_fields_correct": sum(r["all_fields_correct"] for r in rows) / n,
        "markup_computed": len(errs) / n,
        "markup_within_0_05_pts": sum(e <= 0.05 for e in errs) / n,
        "median_markup_error_pts": sorted(errs)[len(errs) // 2] if errs else None,
        "by_format": {fmt: sum(r["all_fields_correct"] for r in rows if r["format"] == fmt) /
                      max(1, sum(r["format"] == fmt for r in rows)) for fmt in sorted({r["format"] for r in rows})},
        "mean_seconds": sum(r["seconds"] for r in rows) / n,
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"receipts_{args.dir.name}_{'rules' if args.rules_only else 'llm'}.json"
    out.write_text(json.dumps({"summary": summary, "receipts": rows}, indent=2, default=str))
    print(json.dumps(summary, indent=2))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
