"""Extract transfer details from receipt text with a local LLM, cross-checked by a rule-based parser.

Both extractors produce the same fields. The final answer is the candidate whose numbers agree with
each other best (amount sent x rate ~= amount received), so one extractor's mistake can be caught by
the other. Nothing here makes a network call except to the local Ollama server.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass, field

from fairsend import llm

FIELDS = ["provider", "amount_sent", "send_currency", "fee", "total_paid", "exchange_rate",
          "rate_from", "rate_to", "amount_received", "receive_currency", "transfer_date"]
NUMERIC = {"amount_sent", "fee", "total_paid", "exchange_rate", "amount_received"}

SYMBOLS = {"$": "USD", "US$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "₱": "PHP", "₦": "NGN",
           "Rs": "INR", "Rs.": "INR", "RS": "INR", "C$": "CAD", "CA$": "CAD", "A$": "AUD", "AU$": "AUD",
           "MX$": "MXN", "৳": "BDT", "₨": "PKR", "¥": "JPY", "Ksh": "KES", "KSh": "KES"}
CODES = ("USD EUR GBP INR PHP MXN NGN CAD AUD NZD SGD AED SAR QAR KWD JPY CNY KRW BDT PKR LKR NPR KES GHS "
         "ZAR VND IDR THB MYR BRL COP PEN GTQ HNL DOP JMD HTG EGP MAD TRY PLN RON CHF SEK NOK DKK HKD XOF XAF "
         "UGX TZS ETB").split()
_CODE_RE = "|".join(CODES)
# Grouped thousands ("1,234.56", "1.234,56", "1,23,456.00", "1 234") or a plain number ("87.2962").
_NUM = r"(\d{1,3}(?:[,.\s]\d{2,3}(?!\d))+(?:[.,]\d+)?|\d+(?:[.,]\d+)*)"

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
MONTH_FIRST_CURRENCIES = {"USD", "PHP"}  # senders in these currencies usually write dates month-first


@dataclass
class Extraction:
    provider: str | None = None
    amount_sent: float | None = None
    send_currency: str | None = None
    fee: float | None = None
    total_paid: float | None = None
    exchange_rate: float | None = None
    rate_from: str | None = None
    rate_to: str | None = None
    amount_received: float | None = None
    receive_currency: str | None = None
    transfer_date: str | None = None
    method: str = ""
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)

    def missing(self) -> list[str]:
        need = ["amount_sent", "send_currency", "receive_currency", "transfer_date"]
        out = [f for f in need if getattr(self, f) in (None, "")]
        if self.exchange_rate is None and self.amount_received is None:
            out.append("exchange_rate")
        return out


# ------------------------------------------------------------------ normalization

def parse_number(text: str | float | int | None) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = re.sub(r"[^\d.,\s]", "", str(text)).strip().replace(" ", "")
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):          # 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:                                    # 1,234.56 or 1,23,456.00
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = s.replace(",", "") if len(tail) == 3 else head.replace(",", "") + "." + tail
    try:
        return float(s)
    except ValueError:
        return None


def normalize_currency(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    if v.upper() in CODES:
        return v.upper()
    return SYMBOLS.get(v) or SYMBOLS.get(v.rstrip(".")) or None


def normalize_date(value: str | None, send_currency: str | None = None) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
        return _iso(y, mo, d)
    m = re.search(r"(\d{1,2})[\s\-/.]+([A-Za-z]{3,9})\.?[\s\-/.,]+(\d{4})", s)
    if m and m.group(2)[:3].lower() in MONTHS:
        return _iso(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", s)
    if m and m.group(1)[:3].lower() in MONTHS:
        return _iso(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    if m:
        a, b, y = map(int, m.groups())
        y = y + 2000 if y < 100 else y
        if a > 12:
            return _iso(y, b, a)
        if b > 12:
            return _iso(y, a, b)
        return _iso(y, a, b) if send_currency in MONTH_FIRST_CURRENCIES else _iso(y, b, a)
    return None


def _iso(y: int, m: int, d: int) -> str | None:
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return None


def _money(text: str) -> tuple[float | None, str | None]:
    """First amount in `text` and the currency written next to it."""
    sym = r"(US\$|CA\$|AU\$|MX\$|C\$|A\$|Rs\.?|KSh|Ksh|[$€£₹₱₦৳₨¥])"
    for pattern in (rf"(?P<c>{_CODE_RE})\s*{_NUM}", rf"{sym}\s*{_NUM}", rf"{_NUM}\s*(?P<c>{_CODE_RE})\b",
                    rf"{_NUM}"):
        m = re.search(pattern, text)
        if m:
            groups = [g for g in m.groups() if g]
            cur = next((normalize_currency(g) for g in groups if normalize_currency(g)), None)
            num = next((parse_number(g) for g in groups if parse_number(g) is not None and not normalize_currency(g)),
                       None)
            return num, cur
    return None, None


# ------------------------------------------------------------------ rule-based extractor

LABELS = {
    "amount_sent": r"(transfer amount|amount sent|send amount|sending amount|you sent|you send|amount to send|"
                   r"principal|amount transferred|transfer value|sent amount)",
    "fee": r"(transfer fee|service fee|fees?\b|commission|charges?)",
    "total_paid": r"(total paid|total to pay|total charged|total cost|total amount|amount paid|you paid|\btotal\b)",
    "amount_received": r"(recipient gets|recipient receives|amount received|receive amount|they receive|"
                       r"payout amount|amount to be received|beneficiary receives|amount paid out|recipient amount|amount credited|"
                       r"they get|total to recipient)",
    "transfer_date": r"(transfer date|date sent|sent on|transaction date|date of transfer|payment date|created|\bdate\b)",
    "exchange_rate": r"(exchange rate|fx rate|conversion rate|\brate\b)",
}


def _value_lines(lines: list[str], i: int) -> str:
    """The label's own line, or the next non-empty line when the value sits below the label."""
    here = lines[i]
    if re.search(r"\d", here):
        return here
    for j in range(i + 1, min(i + 4, len(lines))):
        if lines[j].strip() and not REFERENCE_LINE.match(lines[j]):
            return lines[j]
    return here


def fix_ocr_numbers(text: str) -> str:
    """Repair a common OCR slip: a decimal point read as a hyphen ("53-3947" -> "53.3947").

    Only a 1-3 digit group followed by a 4+ digit group is changed, so dates like 2023-03-27 are left alone.
    """
    return re.sub(r"\b(\d{1,3})[-–](\d{4,})\b", r"\1.\2", text)


REFERENCE_LINE = re.compile(r"^\s*(ref|reference|txn|transaction (no|number|id)|tracking|mtcn|order)\b", re.IGNORECASE)


def regex_extract(text: str) -> Extraction:
    text = fix_ocr_numbers(text)
    lines = [ln.strip() for ln in text.splitlines()]
    found: dict = {}
    m = re.search(rf"1(?:\.0+)?\s*(?P<a>{_CODE_RE}|[$€£₹])\s*=\s*{_NUM}\s*(?P<b>{_CODE_RE}|[$€£₹₱₦])", text)
    if m:
        found["exchange_rate"] = parse_number(m.group(2))
        found["rate_from"], found["rate_to"] = normalize_currency(m.group("a")), normalize_currency(m.group("b"))
    for i, raw in enumerate(lines):
        low = raw.lower()
        for fld, pattern in LABELS.items():
            if fld in found or not re.search(pattern, low):
                continue
            if fld == "total_paid" and re.search(LABELS["amount_received"], low):
                continue
            if fld == "fee" and re.search(r"(no fee|fee:\s*free|\bfree\b)", low):
                found["fee"] = 0.0
                break
            value_text = _value_lines(lines, i)
            if fld == "transfer_date":
                d = normalize_date(value_text)
                if d:
                    found["transfer_date_raw"] = value_text
                    found[fld] = d
                    break
                continue
            if fld == "exchange_rate":
                after = re.split(pattern, value_text, maxsplit=1, flags=re.IGNORECASE)[-1]
                num = parse_number(re.search(_NUM, after).group(1)) if re.search(_NUM, after) else None
                if num:
                    found[fld] = num
                    break
                continue
            num, cur = _money(re.split(pattern, value_text, maxsplit=1, flags=re.IGNORECASE)[-1]
                              if value_text is raw else value_text)
            if num is None:
                continue
            found[fld] = num
            if fld in ("amount_sent", "total_paid", "fee") and cur and "send_currency" not in found:
                found["send_currency"] = cur
            if fld == "amount_received" and cur:
                found["receive_currency"] = cur
            break
    ex = Extraction(method="rules")
    for k, v in found.items():
        if hasattr(ex, k):
            setattr(ex, k, v)
    if ex.send_currency is None and ex.rate_from:
        ex.send_currency = ex.rate_from
    if ex.receive_currency is None and ex.rate_to and ex.rate_to != ex.send_currency:
        ex.receive_currency = ex.rate_to
    if found.get("transfer_date_raw"):
        ex.transfer_date = normalize_date(found["transfer_date_raw"], ex.send_currency)
    first = next((ln for ln in lines if re.search(r"[A-Za-z]{3,}", ln)), None)
    ex.provider = first[:60] if first else None
    return ex


# ------------------------------------------------------------------ LLM extractor

_NUM_OR_NULL = {"anyOf": [{"type": "number"}, {"type": "null"}]}
_STR_OR_NULL = {"anyOf": [{"type": "string"}, {"type": "null"}]}
SCHEMA = {
    "type": "object",
    "properties": {
        "provider": _STR_OR_NULL, "amount_sent": _NUM_OR_NULL, "send_currency": _STR_OR_NULL,
        "fee": _NUM_OR_NULL, "total_paid": _NUM_OR_NULL, "exchange_rate": _NUM_OR_NULL,
        "rate_from": _STR_OR_NULL, "rate_to": _STR_OR_NULL, "amount_received": _NUM_OR_NULL,
        "receive_currency": _STR_OR_NULL, "transfer_date": _STR_OR_NULL,
    },
    "required": FIELDS,
}

SYSTEM = (
    "You extract data from international money transfer receipts. Copy values exactly as printed. "
    "Never guess: use null for anything that is not on the receipt. Reply with JSON only."
)

PROMPT = """Receipt text (from OCR, may contain errors):
<<<
{text}
>>>

Extract:
- provider: company name
- amount_sent: amount converted to the recipient's currency, NOT including the fee
- send_currency / receive_currency: 3-letter ISO codes (e.g. USD, INR, MXN, PHP, GBP, EUR)
- fee: transfer fee in the sending currency (0 if the receipt says the fee is free)
- total_paid: total charged to the sender including the fee, if shown
- exchange_rate: the exchange rate number exactly as printed
- rate_from / rate_to: the currencies on each side of the printed rate ("1 USD = 83.2 INR" -> USD, INR)
- amount_received: amount the recipient gets
- transfer_date: the date the transfer was made, copied as printed
"""


def llm_extract(text: str, model: str | None = None) -> Extraction:
    data = llm.generate_json(PROMPT.format(text=text[:4000]), SCHEMA, system=SYSTEM, model=model,
                             num_predict=300)
    ex = Extraction(method="llm")
    for k in FIELDS:
        v = data.get(k)
        if k in NUMERIC:
            v = parse_number(v)
        elif k in ("send_currency", "receive_currency", "rate_from", "rate_to"):
            v = normalize_currency(v) if isinstance(v, str) else None
        elif isinstance(v, str):
            v = v.strip() or None
        setattr(ex, k, v)
    ex.transfer_date = normalize_date(data.get("transfer_date"), ex.send_currency) if data.get("transfer_date") else None
    return ex


# ------------------------------------------------------------------ reconciliation

def _drop_misread_symbol(value: float, expected: float) -> float | None:
    """OCR often reads a currency symbol (₹, £) as a leading digit: '₹165,711' -> '1165,711'.

    If removing the first digit makes the amount match what sent x rate predicts, return the repaired value.
    """
    whole, _, frac = f"{value:.2f}".partition(".")
    if len(whole) < 2:
        return None
    candidate = float(whole[1:] + "." + frac)
    return candidate if expected and abs(candidate - expected) / expected < 0.005 else None


def complete(ex: Extraction) -> Extraction:
    """Fill fields that follow from others (principal from total - fee, etc.) and repair common misreads."""
    # A "rate" identical to one of the amounts was put in the wrong field.
    if ex.exchange_rate is not None and ex.exchange_rate in {ex.amount_received, ex.amount_sent, ex.total_paid, ex.fee}:
        if ex.amount_received is None and ex.exchange_rate != ex.amount_sent:
            ex.amount_received = ex.exchange_rate
        ex.exchange_rate = None
        ex.warnings.append("Moved a value that looked like an amount out of the exchange-rate field")
    if ex.amount_sent and ex.exchange_rate and ex.amount_received:
        predictions = [ex.amount_sent * ex.exchange_rate, ex.amount_sent / ex.exchange_rate]
        if min(abs(p - ex.amount_received) / ex.amount_received for p in predictions) > 0.02:
            for p in predictions:
                repaired = _drop_misread_symbol(ex.amount_received, p)
                if repaired is not None:
                    ex.amount_received = repaired
                    ex.warnings.append("Fixed an amount where a currency symbol was read as a digit")
                    break
    if ex.amount_sent is None and ex.total_paid is not None and ex.fee is not None:
        ex.amount_sent = round(ex.total_paid - ex.fee, 2)
    if ex.fee is None and ex.total_paid is not None and ex.amount_sent is not None and ex.total_paid >= ex.amount_sent:
        ex.fee = round(ex.total_paid - ex.amount_sent, 2)
    if ex.amount_sent is not None and ex.total_paid is not None and ex.fee is not None:
        # Some receipts show the total as the "amount"; if sent == total and fee > 0, back the fee out.
        if abs(ex.amount_sent - ex.total_paid) < 0.005 and ex.fee > 0 and ex.amount_received and ex.exchange_rate:
            implied = min(ex.amount_received / ex.exchange_rate, ex.amount_received * ex.exchange_rate,
                          key=lambda x: abs(x - ex.amount_sent))
            if abs(implied - (ex.total_paid - ex.fee)) < abs(implied - ex.total_paid):
                ex.amount_sent = round(ex.total_paid - ex.fee, 2)
    if ex.send_currency and ex.receive_currency == ex.send_currency:
        ex.receive_currency = ex.rate_to if ex.rate_to and ex.rate_to != ex.send_currency else None
    return ex


def consistency_error(ex: Extraction) -> float | None:
    """Relative gap between amount_sent x rate and amount_received (rate read in either direction)."""
    if not (ex.amount_sent and ex.exchange_rate and ex.amount_received):
        return None
    options = [ex.amount_sent * ex.exchange_rate, ex.amount_sent / ex.exchange_rate]
    return min(abs(o - ex.amount_received) / ex.amount_received for o in options)


def _score(ex: Extraction) -> float:
    filled = sum(getattr(ex, f) is not None for f in FIELDS)
    err = consistency_error(ex)
    bonus = 0 if err is None else (6 if err < 0.005 else 3 if err < 0.02 else -4)
    return filled + bonus - 3 * len(ex.missing())


def _merge(primary: Extraction, secondary: Extraction, method: str) -> Extraction:
    out = Extraction(method=method)
    for f in FIELDS:
        v = getattr(primary, f)
        setattr(out, f, v if v not in (None, "") else getattr(secondary, f))
    return out


def printed_numbers(text: str) -> list[float]:
    return [v for v in (parse_number(m.group(1)) for m in re.finditer(_NUM, text)) if v is not None]


def keep_printed(ex: Extraction, text: str) -> Extraction:
    """Drop any number the model returned that isn't actually printed on the receipt.

    Small models sometimes round a rate (53.3947 -> 53.0) or do arithmetic the receipt didn't ask for
    (amount minus fee). A value that appears nowhere in the text is treated as unknown, so the exactly
    printed value from the rule-based reader, or a value derived from the other fields, is used instead.
    """
    printed = printed_numbers(fix_ocr_numbers(text))
    for f in ("amount_sent", "fee", "total_paid", "exchange_rate", "amount_received"):
        v = getattr(ex, f)
        if v is None or (f == "fee" and v == 0):
            continue
        if not any(abs(v - p) <= max(0.005, abs(p) * 1e-9) for p in printed):
            setattr(ex, f, None)
            ex.warnings.append(f"Ignored a {f.replace('_', ' ')} that isn't printed on the receipt")
    return ex


def repair_rate(ex: Extraction, text: str) -> Extraction:
    """If amount sent x rate doesn't give the amount received, look for the printed number that does.

    OCR sometimes misreads the rate line ("1 GBP = 166.42" read as "4 GBP = 166.42", so the rule-based reader
    takes 4). The two amounts pin down the real rate, so a printed number matching it is the right one.
    """
    if not (ex.amount_sent and ex.amount_received):
        return ex
    err = consistency_error(ex)
    if ex.exchange_rate is not None and err is not None and err <= 0.02:
        return ex
    implied = ex.amount_received / ex.amount_sent
    for p in printed_numbers(text):
        if p > 0 and min(abs(p - implied) / implied, abs(1 / p - implied) / implied) < 0.005:
            if ex.exchange_rate is not None:
                ex.warnings = [w for w in ex.warnings if "does not match" not in w]
                ex.warnings.append("Corrected the exchange rate using the amounts on the receipt")
            ex.exchange_rate = p
            break
    return ex


def extract(text: str, use_llm: bool = True, model: str | None = None) -> Extraction:
    text = fix_ocr_numbers(text)
    rules = complete(regex_extract(text))
    candidates = [rules]
    warnings = []
    if use_llm:
        try:
            ai = complete(keep_printed(llm_extract(text, model), text))
            # Ties go to the earliest candidate: the rule-based values (copied exactly from labelled lines), with the
            # AI filling only the gaps. The AI's own reading wins only when its numbers are more consistent.
            candidates = [complete(_merge(rules, ai, "rules+llm")), rules, complete(_merge(ai, rules, "llm+rules")), ai]
        except (llm.LLMUnavailable, ValueError) as exc:
            warnings.append(f"Local LLM unavailable, used rule-based extraction only ({exc.__class__.__name__})")
    # A "rate" that equals an amount some extractor found is a misplaced amount, whichever candidate it came from.
    amounts = {v for c in candidates for v in (c.amount_sent, c.amount_received, c.total_paid) if v}
    best = max(candidates, key=lambda c: _score(c) - (8 if c.exchange_rate in amounts else 0))
    best = repair_rate(best, text)
    best.warnings = list(dict.fromkeys(best.warnings + warnings))
    err = consistency_error(best)
    if err is not None and err > 0.02:
        best.warnings.append("Amount sent x rate does not match the amount received; please check the fields")
    return best
