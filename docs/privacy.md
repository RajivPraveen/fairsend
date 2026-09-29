# FairSend privacy statement

FairSend is built so that personal financial information stays on the device running it.

**Receipts.** Uploaded screenshots and PDFs are processed in memory by Tesseract OCR and a local open-source language
model served by Ollama on the same machine. They are never written to disk (tesseract reads the image over stdin), never
logged, and never sent to any external service. Extracted fields are held only in the app's memory for your session and disappear when
it ends. The only network request is for the public mid-market exchange rate on the transfer date, which contains
the currency pair and date and nothing about you.

**Questions to the explainer.** These are answered by the same local model from a local library of public sources.
Questions are not stored.

**Comparisons, tuition mode and savings.** Inputs such as amounts, routes and providers are used to compute the page
and are not stored.

**Rate alerts.** To send an alert, FairSend stores only:
- your contact (an email address or a Telegram chat id),
- the currency pair and your target rate and direction,
- optionally, the route (for the "best provider" link),
- timestamps and a delivery log (rate, date, success or failure), used to avoid duplicate messages and to measure
  reliability.

There are no accounts or passwords. A random manage token lets you edit, pause, or delete an alert. **Deleting an alert
removes its row and its entire delivery log.** For research, a daily count of active alerts is kept (numbers only, no
contact details).

**Third parties.** Exchange rates come from the Frankfurter API (ECB data) and the fawazahmed0 currency API. Requests
contain only currency codes and dates. Email alerts go through the SMTP server the operator configures, and Telegram
alerts through Telegram's Bot API. Those services see the alert message and your contact.

**No tracking.** FairSend has no analytics, advertising, or third-party scripts, and Streamlit's usage statistics are
disabled (`.streamlit/config.toml`).

**User research.** Study surveys use random participant codes, not names. Raw exports are kept outside version control,
and results are reported only in aggregate.
