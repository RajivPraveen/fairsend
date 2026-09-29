# Your own receipts (not committed)

To measure the checker on real receipts:

1. Put screenshots or PDFs in this folder. Crop or black out names and account numbers first.
2. Add a `truth.json` in the same format as `../synthetic/truth.json`, with the values printed on each receipt and
   the mid-market rate for its date. Get the rate with
   `python -c "from fairsend import fx; print(fx.get_rate('USD','INR','2025-03-14'))"`.
3. Run `python eval/receipts/evaluate.py --dir eval/receipts/real`.

Everything in this folder except this README is git-ignored.
