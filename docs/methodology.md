# FairSend methodology

This note explains where FairSend's numbers come from, the choices behind them, and their limits.

## 1. Data

| Source | What it provides | Refresh |
|---|---|---|
| World Bank *Remittance Prices Worldwide* (RPW), `rpw_dataset_2011_2025_q3.xlsx`, CC BY 4.0 | Mystery-shopping prices for sending ~USD 200 and ~USD 500: fee, provider exchange rate, FX margin vs interbank, speed, payout method, payment instrument; 2011–2025, ~378 routes | Quarterly (the pipeline detects a new file by hash) |
| ECB reference rates via the Frankfurter API | Daily mid-market rates for ~30 currencies, 1999 onward | Daily, around 16:00 CET |
| fawazahmed0 currency API (jsDelivr / Cloudflare mirrors) | Daily rates for 200+ currencies (NGN, PKR, BDT, KES, ...), March 2024 onward | Daily |
| CFPB Regulation E Subpart B and "Ask CFPB" pages, UN SDG 10.c metadata, RPW Q3 2025 report | The explainer's source library (`fairsend/explainer/corpus/`) | Manual |

## 2. Pipeline (`fairsend/pipeline/`)

1. **Ingest**: both RPW sheets (their layout changed in Q2 2016) are mapped onto one schema.
2. **Clean**:
   - Provider names are matched on a key that ignores case, punctuation, legal suffixes and parenthetical
     qualifiers, plus a manual alias list, so 910 raw names become 869 providers. "X via Western Union" rows keep
     their agent name but get `network = Western Union`.
   - Firm types, payout methods and speed categories are standardized. Speed becomes an upper bound in business days.
   - Non-ISO currency codes are fixed: `CFA` becomes XOF or XAF depending on the country, and `CLF` becomes CLP.
3. **Payout currency inference**: RPW doesn't record which currency a product pays out in. Many products pay USD or
   EUR rather than local currency (EUR to Romania, USD to the Philippines, USD to China), and some countries changed
   currency during the period (Lithuania, Latvia, Croatia). For each row, FairSend compares the recorded interbank rate
   with the ECB rate for each candidate currency (local, USD, EUR, the sending currency, any legacy currency) on the
   collection date and keeps the match within 5%. This cut the rows where interbank and ECB rates disagree from
   16,471 to 978. The remaining 978 are genuine source errors, such as a thousands-scaling slip on USA→Indonesia.
4. **ECB join**: daily ECB history for every relevant pair is loaded once (about 400,000 rates) and attached to each
   row by collection date.
5. **Quality checks**: 17 checks per run, stored in `quality_results`. Errors exclude the row; warnings flag it.
   - Errors: duplicate ids, missing key fields or $200 prices, zero or negative amounts or rates, negative fees,
     total cost above 100% or below −10%, a margin more than 10% better or 50% worse than interbank, and an unmapped
     currency.
   - Warnings: published totals or margins that don't match their components, non-transparent pricing, negative
     margins, a missing $500 price, a fixed currency code, an unknown speed, and interbank more than 5% from ECB.
6. **Load**: rows are upserted by a stable id (`sheet:world bank id`), so history accumulates across releases. Each
   run is logged in `pipeline_runs` with the source file's SHA-256, and re-running on an unchanged file is a no-op.

**Validation.** Before exclusions, FairSend's simple average of total cost at USD 200 is 6.36% for Q3 2025 and 6.49%
for Q1 2025. Both equal the World Bank's published Global Average.

## 3. True total cost (`fairsend/cost_model.py`)

- markup % = (mid − provider rate) ÷ mid
- markup cost = amount converted × markup %
- total cost = fee + markup cost
- amount received = amount converted × provider rate

There are two conventions:

- **Budget mode** (used for comparisons): the sender hands over a fixed amount and the fee comes out of it, so the
  amount received is directly comparable across providers.
- **Principal mode** (receipts; the World Bank convention): the fee is paid on top.

**Other amounts.** Each product's fee is observed at two amounts. FairSend interpolates it linearly, which identifies
a fixed + percentage fee, and floors it at 0. The markup is interpolated between the two points and held at the
nearest one outside them. Anything outside the surveyed range is flagged as extrapolated.

**Today's estimate.** A product's provider rate today is modelled as today's mid rate less the product's surveyed
markup. The markup is the stable part of pricing; the rate moves daily. Markups are used exactly as recorded: a
surveyed markup below 0% (a promotion that beat the real rate) keeps its real value and is labelled as a special
offer. The raw recorded values (amount, fee, provider rate, interbank rate, date) are shown in the app.

**Undisclosed rates.** When a provider didn't disclose its rate, RPW records a 0% margin. FairSend treats that as
unknown: the product can't be ranked, but it is still listed with its recorded fee.

## 4. Features

- **Comparison**: the latest survey period for the route. Duplicate listings are removed, and payout and speed
  filters apply. Products are ranked by amount received.
- **Tuition mode**: when the World Bank recorded products converting the paying currency into the bill's currency
  (for example Indian banks sending USD), each of those real providers is listed with its latest recorded markup, fee
  and speed. Otherwise the app says so and shows worldwide medians of real bank and online-service prices. The
  recorded fee (at ~USD 500) is treated as flat and the markup is kept, which is an estimate for large bills. User
  quotes are exact. Nothing is assumed: arrival time, deductions and university processing time come from the data
  or from the user.
- **Receipt checker**:
  - Tesseract OCR runs over stdin/stdout. PDFs use their text layer when present and are rendered in memory
    otherwise.
  - A local LLM (Ollama, default `mistral:7b-instruct`, JSON-schema constrained) and a rule-based parser both
    extract the fields. The candidate whose amount × rate best matches the amount received wins.
  - Two misreads are repaired automatically: an amount put in the rate field, and a currency symbol read as a
    leading digit.
  - The markup is measured against the mid rate on the transfer date.
- **Savings summary**: compares the user's provider (its cheapest matching product) with the cheapest suitable product,
  multiplied by transfers per year.
- **Rate alerts**: a daily job fires when the latest published rate meets the target, the alert hasn't fired for
  that rate date, and its cooldown has passed. The message gives where today's rate sits in its 90-day range
  (descriptive, not a forecast) and links to the comparison.
- **Explainer**:
  - Sources are split into sections of up to 200 words and embedded with `all-MiniLM-L6-v2` into a FAISS
    inner-product index. Retrieval takes the top 5 passages at cosine ≥ 0.30.
  - The local LLM answers only from numbered passages and must cite them. Uncited answers are retried once, then
    withheld.
  - A rule-based guard declines requests for personal financial advice and rate predictions.

## 5. Global analysis (`fairsend/analysis/`)

The analysis follows World Bank conventions: USD 200, simple averages across services, and SDG 10.c thresholds of 3%
and 5% applied to route averages. Markup shares use transparent services only. Price dispersion is max ÷ min
within a route, for routes with 5 or more services and a cheapest service of at least 0.25%.

## 6. Limitations

- RPW prices are quarterly snapshots at two amounts. They don't cover every provider or product, and providers
  change prices, run promotions, and price large amounts differently.
- Reference rates are daily, not intraday. A few tenths of a percent of any receipt's measured markup can be
  intraday movement.
- Tuition benchmarks extrapolate USD 500 prices to large sums. Transfer limits, tiered pricing and negotiated rates
  aren't modelled.
- Payout currency is inferred, not recorded.
- Receipt accuracy is measured on synthetic receipts with known ground truth (fictional providers; see
  `eval/receipts/`). Real receipts vary more, so add your own to `eval/receipts/real/` to measure them.
- All results are estimates, not financial advice.
