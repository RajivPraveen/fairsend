"""Collect every evaluation into eval/RESULTS.md.

    python eval/summarize.py

Reads: the pipeline's quality results (database), eval/results/*.json from the receipt and explainer evaluations,
and runs the cost-model and alert test suites.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

from fairsend import db
from fairsend.analysis import global_costs as g

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def pytest_counts(path: str) -> tuple[int, int]:
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", path], capture_output=True, text=True, cwd=ROOT)
    last = out.stdout.strip().splitlines()[-1]
    passed = int(last.split(" passed")[0].split()[-1]) if " passed" in last else 0
    failed = int(last.split(" failed")[0].split()[-1]) if " failed" in last else 0
    return passed, failed


def load(name: str) -> dict | None:
    p = HERE / "results" / name
    return json.loads(p.read_text())["summary"] if p.exists() else None


def main() -> None:
    lines = ["# FairSend evaluation results", "", f"*Generated {dt.datetime.now():%Y-%m-%d %H:%M}.*", ""]

    cm_p, cm_f = pytest_counts("tests/test_cost_model.py")
    al_p, al_f = pytest_counts("tests/test_alerts.py")
    all_p, all_f = pytest_counts("tests")
    lines += ["## Cost model accuracy",
              f"Hand-calculated test cases (`tests/test_cost_model.py`): **{cm_p} passed, {cm_f} failed**. They cover "
              "fees, markups, and amounts received in both conventions, a $20,000 tuition payment, delivery with "
              "intermediary deductions, fee interpolation and extrapolation, rate orientation, and an exact "
              "reproduction of a published World Bank total-cost figure.", ""]

    lines += ["## Alert reliability",
              f"Scenario tests (`tests/test_alerts.py`): **{al_p} passed, {al_f} failed**. They cover firing exactly "
              "at the target, never below it (including 200 randomized days), cooldowns, no duplicate firing for "
              "the same rate date, both directions, paused and deleted alerts, retry after a failed delivery, and "
              "manage-token checks.", ""]

    rows = []
    for fname, label in (("receipts_heldout2_qwen35.json", "**Final test set** · Qwen 3.5 4B + rules (default)"),
                         ("receipts_heldout2_mistral.json", "**Final test set** · Mistral 7B + rules"),
                         ("receipts_heldout2_rules.json", "**Final test set** · rules only (no AI)"),
                         ("receipts_heldout_llm.json", "Earlier held-out set (used to tune) · Qwen 3.5 4B + rules"),
                         ("receipts_synthetic_llm.json", "Development set (used to tune) · local AI + rules")):
        r = load(fname)
        if r:
            rows.append(f"| {label} | {r['receipts']} | {r['overall_field_accuracy']:.1%} | "
                        f"{r['receipts_all_fields_correct']:.1%} | {r['markup_within_0_05_pts']:.1%} | "
                        f"{r['mean_seconds']:.1f} s |")
    if rows:
        lines += ["## Receipt checker",
                  "Synthetic receipts with known ground truth: fictional providers, 6 layouts, PNG/JPG/text PDF/scanned "
                  "PDF, blur, rotation and JPEG noise, and rates from the real ECB rate on each date minus a chosen "
                  "markup. The development and earlier held-out sets were used to find and fix extraction problems, so "
                  "their scores are optimistic. The **final test set** (a new random seed) was generated after those "
                  "fixes and scored once, as shown. Two later fixes (repairing a misread rate from the amounts, and "
                  "using the more precise amount-based rate) were prompted by 3 of its receipts and are covered by "
                  "unit tests; the set was not re-scored after them. Real receipts will vary more; see "
                  "`eval/receipts/real/`.", "",
                  "| Set · extractor | Receipts | Field accuracy (7 fields) | All fields correct | Markup within 0.05 pts "
                  "| Time / receipt |",
                  "|---|---|---|---|---|---|", *rows, ""]

    s = load("explainer.json")
    if s:
        lines += ["## Plain-language explainer",
                  f"{s['questions']} reviewed questions ({s['answerable']} answerable, {s['must_decline']} that must be "
                  f"declined); model `{s['model']}`, embeddings `{s['embedding_model']}`.", "",
                  "| Metric | Result |", "|---|---|",
                  f"| Correct answers (all key facts present) | {s['answer_accuracy']:.1%} |",
                  f"| Cites a correct source | {s['citation_accuracy']:.1%} |",
                  f"| Correct **and** cites a correct source | {s['correct_with_right_citation']:.1%} |",
                  f"| Retrieval hit@5 | {s['retrieval_hit_at_5']:.1%} |",
                  f"| Declines out-of-scope questions | {s['decline_accuracy_out_of_scope']:.0%} |",
                  f"| Declines personal-advice requests | {s['decline_accuracy_personal_advice']:.0%} |",
                  f"| Answerable questions wrongly declined | {s['false_declines']} |",
                  f"| Mean time per question | {s['mean_seconds']:.1f} s |", ""]
        mistral = load("explainer_mistral.json")
        if mistral:
            lines += ["Model comparison on the same 45 questions (same retrieval, prompt and settings):", "",
                      "| Model | Correct + right citation | Declines | Time / answer |", "|---|---|---|---|",
                      f"| Qwen 3.5 4B (default) | {s['correct_with_right_citation']:.1%} | {s['decline_accuracy']:.0%} | "
                      f"{s['mean_seconds']:.1f} s |",
                      f"| Mistral 7B | {mistral['correct_with_right_citation']:.1%} | {mistral['decline_accuracy']:.0%} | "
                      f"{mistral['mean_seconds']:.1f} s |", "",
                      "The prompt, answer length and advice guard were adjusted after inspecting earlier runs on this "
                      "question set (first run: 78.4% with Mistral), so these figures are somewhat optimistic.", ""]

    with db.session() as conn:
        q = conn.execute("SELECT check_name, severity, rows_failed, pass_rate FROM quality_results WHERE run_id = "
                         "(SELECT run_id FROM pipeline_runs WHERE status='success' ORDER BY finished_at DESC LIMIT 1)"
                         ).fetchall()
        run = conn.execute("SELECT rows_in, rows_valid FROM pipeline_runs WHERE status='success' "
                           "ORDER BY finished_at DESC LIMIT 1").fetchone()
        df = g.load(conn)
    cov = g.coverage(df)
    lines += ["## Data quality and coverage",
              f"Latest successful run: {run['rows_in']:,} rows loaded, {run['rows_valid']:,} valid "
              f"({run['rows_valid'] / run['rows_in']:.2%}). Coverage: {cov['corridors']} routes, {cov['providers']} "
              f"providers, {cov['sending_countries']} sending and {cov['receiving_countries']} receiving countries, "
              f"{cov['periods']} periods ({cov['first_period']} to {cov['last_period']}).", "",
              "| Check | Severity | Rows failed | Pass rate |", "|---|---|---|---|"]
    lines += [f"| {r['check_name']} | {r['severity']} | {r['rows_failed']:,} | {r['pass_rate']:.2%} |" for r in q]
    lines += ["", f"Full test suite: **{all_p} passed, {all_f} failed**."]
    (HERE / "RESULTS.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
