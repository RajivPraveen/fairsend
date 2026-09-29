# FairSend evaluation results

*Generated 2026-09-29 11:53.*

## Cost model accuracy
Hand-calculated test cases (`tests/test_cost_model.py`): **13 passed, 0 failed**. They cover fees, markups, and amounts received in both conventions, a $20,000 tuition payment, delivery with intermediary deductions, fee interpolation and extrapolation, rate orientation, and an exact reproduction of a published World Bank total-cost figure.

## Alert reliability
Scenario tests (`tests/test_alerts.py`): **15 passed, 0 failed**. They cover firing exactly at the target, never below it (including 200 randomized days), cooldowns, no duplicate firing for the same rate date, both directions, paused and deleted alerts, retry after a failed delivery, and manage-token checks.

## Receipt checker
Synthetic receipts with known ground truth: fictional providers, 6 layouts, PNG/JPG/text PDF/scanned PDF, blur, rotation and JPEG noise, and rates from the real ECB rate on each date minus a chosen markup. The development and earlier held-out sets were used to find and fix extraction problems, so their scores are optimistic. The **final test set** (a new random seed) was generated after those fixes and scored once, as shown. Two later fixes (repairing a misread rate from the amounts, and using the more precise amount-based rate) were prompted by 3 of its receipts and are covered by unit tests; the set was not re-scored after them. Real receipts will vary more; see `eval/receipts/real/`.

| Set · extractor | Receipts | Field accuracy (7 fields) | All fields correct | Markup within 0.05 pts | Time / receipt |
|---|---|---|---|---|---|
| **Final test set** · Qwen 3.5 4B + rules (default) | 40 | 99.6% | 97.5% | 92.5% | 6.8 s |
| **Final test set** · Mistral 7B + rules | 40 | 99.6% | 97.5% | 92.5% | 10.9 s |
| **Final test set** · rules only (no AI) | 40 | 99.6% | 97.5% | 92.5% | 0.4 s |
| Earlier held-out set (used to tune) · Qwen 3.5 4B + rules | 40 | 98.2% | 90.0% | 92.5% | 6.8 s |
| Development set (used to tune) · local AI + rules | 40 | 100.0% | 100.0% | 97.5% | 11.5 s |

## Plain-language explainer
45 reviewed questions (37 answerable, 8 that must be declined); model `qwen3.5:4b`, embeddings `sentence-transformers/all-MiniLM-L6-v2`.

| Metric | Result |
|---|---|
| Correct answers (all key facts present) | 83.8% |
| Cites a correct source | 100.0% |
| Correct **and** cites a correct source | 83.8% |
| Retrieval hit@5 | 100.0% |
| Declines out-of-scope questions | 100% |
| Declines personal-advice requests | 100% |
| Answerable questions wrongly declined | 0 |
| Mean time per question | 5.3 s |

Model comparison on the same 45 questions (same retrieval, prompt and settings):

| Model | Correct + right citation | Declines | Time / answer |
|---|---|---|---|
| Qwen 3.5 4B (default) | 83.8% | 100% | 5.3 s |
| Mistral 7B | 89.2% | 100% | 9.2 s |

The prompt, answer length and advice guard were adjusted after inspecting earlier runs on this question set (first run: 78.4% with Mistral), so these figures are somewhat optimistic.

## Data quality and coverage
Latest successful run: 253,960 rows loaded, 253,599 valid (99.86%). Coverage: 378 routes, 869 providers, 49 sending and 111 receiving countries, 54 periods (2011_1Q to 2025_3Q).

| Check | Severity | Rows failed | Pass rate |
|---|---|---|---|
| duplicate_id | error | 5 | 100.00% |
| implausible_fx_margin | error | 184 | 99.93% |
| impossible_total_cost | error | 143 | 99.94% |
| interbank_vs_ecb | warning | 978 | 99.61% |
| margin_inconsistent | warning | 1,940 | 99.24% |
| missing_200_cost | error | 138 | 99.95% |
| missing_500_cost | warning | 1,282 | 99.50% |
| missing_key_fields | error | 0 | 100.00% |
| negative_fee | error | 0 | 100.00% |
| negative_fx_margin | warning | 10,806 | 95.75% |
| non_transparent | warning | 7,418 | 97.08% |
| nonpositive_amount | error | 103 | 99.96% |
| nonpositive_rate | error | 1 | 100.00% |
| nonstandard_currency_code | warning | 457 | 99.82% |
| total_cost_inconsistent | warning | 139 | 99.95% |
| unknown_receive_currency | error | 0 | 100.00% |
| unknown_speed | warning | 10 | 100.00% |

Full test suite: **90 passed, 0 failed**.
