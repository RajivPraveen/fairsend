"""Generate synthetic transfer receipts with known ground truth for evaluating the receipt checker.

Every receipt uses a fictional provider name and carries a "sample - testing only" footer. Exchange
rates are built from the real mid-market rate on the receipt date (from FairSend's FX cache) minus a
chosen markup, so the true hidden cost of each receipt is known exactly.

Variety is deliberate: six layouts, different labels, date formats (ISO, US, day-first, long form),
rates quoted in either direction, European number formatting, receipts without a printed rate,
fee-free transfers, and image degradation (blur, rotation, JPEG artefacts, noise). Outputs are PNG/JPG
images, PDFs with a text layer, and scanned (image-only) PDFs.

    python eval/receipts/generate.py            # development set: eval/receipts/synthetic/
    python eval/receipts/generate.py --seed 7 --out eval/receipts/heldout   # held-out set, never used for tuning
"""

from __future__ import annotations

import datetime as dt
import io
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from fairsend import fx

OUT = Path(__file__).resolve().parent / "synthetic"
SEED = 20260929
FOOTER = "SAMPLE RECEIPT - GENERATED FOR TESTING ONLY"

PROVIDERS = ["BlueRiver Remit", "Northstar Money", "Cedar Transfer", "Harbor Community Bank", "Lotus Pay",
             "Meridian Wire", "Kite Remittance", "Summit Credit Union"]

# (send, receive, typical amounts) - mostly ECB pairs; a few need the fallback source (2024-03 onward).
ROUTES = [("USD", "INR", [200, 500, 1000, 2500]), ("USD", "MXN", [150, 300, 750]), ("USD", "PHP", [200, 400, 1000]),
          ("GBP", "INR", [250, 600, 1500]), ("EUR", "PHP", [300, 800]), ("CAD", "INR", [500, 1500]),
          ("AUD", "INR", [400, 1200]), ("USD", "CNY", [500, 3000]), ("EUR", "TRY", [200, 500]),
          ("USD", "BRL", [300, 900]), ("SGD", "INR", [500, 1000]), ("USD", "NGN", [200, 500]),
          ("USD", "PKR", [300, 700]), ("GBP", "KES", [200, 400]), ("EUR", "INR", [15000, 22000]),
          ("USD", "IDR", [400, 1200])]

SYMBOL = {"USD": "$", "GBP": "£", "EUR": "€", "INR": "₹", "PHP": "₱", "NGN": "₦"}
FONT_DIRS = [Path("/System/Library/Fonts/Supplemental"), Path("/Library/Fonts"), Path("/usr/share/fonts/truetype/dejavu")]
FONTS = {"sans": ["Arial Unicode.ttf", "Arial.ttf", "DejaVuSans.ttf"],
         "mono": ["Courier New.ttf", "DejaVuSansMono.ttf"],
         "serif": ["Georgia.ttf", "Times New Roman.ttf", "DejaVuSerif.ttf"]}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for name in FONTS[kind]:
        for d in FONT_DIRS:
            if (d / name).exists():
                return ImageFont.truetype(str(d / name), size)
    return ImageFont.load_default(size)


def money(x: float, decimals: int = 2, european: bool = False) -> str:
    s = f"{x:,.{decimals}f}"
    if european:
        s = s.replace(",", "_").replace(".", ",").replace("_", ".")
    return s


def fmt_date(d: dt.date, style: str) -> str:
    return {
        "iso": d.isoformat(),
        "us": d.strftime("%m/%d/%Y"),
        "dayfirst": d.strftime("%d/%m/%Y"),
        "long": d.strftime("%B %-d, %Y"),
        "short": d.strftime("%d-%b-%Y"),
        "daymonth": d.strftime("%-d %b %Y"),
    }[style]


def random_weekday(rng: random.Random, start: dt.date, end: dt.date) -> dt.date:
    while True:
        d = start + dt.timedelta(days=rng.randrange((end - start).days))
        if d.weekday() < 5:
            return d


# ------------------------------------------------------------------ layouts: return list of (text, style) lines

def layout_app(t: dict) -> list[tuple[str, str]]:
    s = SYMBOL.get(t["send_currency"], t["send_currency"] + " ")
    r = SYMBOL.get(t["receive_currency"], t["receive_currency"] + " ")
    return [(t["provider"], "title"), ("Transfer complete", "sub"), ("", ""),
            (f"You sent        {s}{money(t['amount_sent'])}", "row"),
            (f"Transfer fee    {s}{money(t['fee'])}", "row"),
            (f"Total paid      {s}{money(t['amount_sent'] + t['fee'])}", "row"), ("", ""),
            (f"Exchange rate   1 {t['send_currency']} = {t['rate_text']} {t['receive_currency']}", "row"),
            (f"Recipient gets  {r}{money(t['amount_received'])}", "big"), ("", ""),
            (f"Sent on {t['date_text']}", "sub"), (f"Reference {t['ref']}", "sub")]


def layout_bank(t: dict) -> list[tuple[str, str]]:
    return [(t["provider"], "title"), ("International Wire Transfer - Confirmation", "sub"), ("", ""),
            (f"Transaction date:          {t['date_text']}", "row"),
            (f"Transfer amount:           {t['send_currency']} {money(t['amount_sent'])}", "row"),
            (f"Commission:                {t['send_currency']} {money(t['fee'])}", "row"),
            (f"Total debited:             {t['send_currency']} {money(t['amount_sent'] + t['fee'])}", "row"),
            (f"Conversion rate:           {t['rate_text']}", "row"),
            (f"Amount credited to beneficiary: {t['receive_currency']} {money(t['amount_received'])}", "row"),
            ("", ""), (f"Our reference: {t['ref']}", "sub"),
            ("Beneficiary bank charges, if any, are borne by the beneficiary.", "sub")]


def layout_email(t: dict) -> list[tuple[str, str]]:
    fee_line = "Transfer fee    0.00 {c} (Free)".format(c=t["send_currency"]) if t["fee"] == 0 else \
        f"Transfer fee    {money(t['fee'])} {t['send_currency']}"
    return [(f"{t['provider']} - your receipt", "title"), ("", ""),
            (f"Date            {t['date_text']}", "row"),
            (f"Amount to send  {money(t['amount_sent'])} {t['send_currency']}", "row"),
            (fee_line, "row"),
            (f"Rate            1 {t['send_currency']} = {t['rate_text']} {t['receive_currency']}", "row"),
            (f"They receive    {money(t['amount_received'])} {t['receive_currency']}", "row"), ("", ""),
            ("Thanks for sending with us.", "sub")]


def layout_slip(t: dict) -> list[tuple[str, str]]:
    return [(t["provider"].upper(), "title"), ("AGENT LOCATION #1042", "sub"), ("-" * 34, "row"),
            (f"DATE        {t['date_text']}", "row"), (f"TXN NO      {t['ref']}", "row"),
            (f"PRINCIPAL   {t['send_currency']} {money(t['amount_sent'])}", "row"),
            (f"CHARGES     {t['send_currency']} {money(t['fee'])}", "row"),
            (f"TOTAL       {t['send_currency']} {money(t['amount_sent'] + t['fee'])}", "row"),
            (f"RATE        {t['rate_text']}", "row"),
            (f"PAYOUT AMOUNT {t['receive_currency']} {money(t['amount_received'])}", "row"), ("-" * 34, "row"),
            ("CUSTOMER COPY", "sub")]


def layout_norate(t: dict) -> list[tuple[str, str]]:
    return [(t["provider"], "title"), ("Payment summary", "sub"), ("", ""),
            (f"Date of transfer   {t['date_text']}", "row"),
            (f"Amount sent        {t['send_currency']} {money(t['amount_sent'])}", "row"),
            (f"Service fee        {t['send_currency']} {money(t['fee'])}", "row"),
            (f"Amount received    {t['receive_currency']} {money(t['amount_received'])}", "row"), ("", ""),
            (f"Ref: {t['ref']}", "sub")]


def layout_european(t: dict) -> list[tuple[str, str]]:
    return [(t["provider"], "title"), ("Transfer receipt", "sub"), ("", ""),
            (f"Transfer date      {t['date_text']}", "row"),
            (f"Amount sent        {money(t['amount_sent'], european=True)} {t['send_currency']}", "row"),
            (f"Fee                {money(t['fee'], european=True)} {t['send_currency']}", "row"),
            (f"Exchange rate      1 {t['send_currency']} = {t['rate_text']} {t['receive_currency']}", "row"),
            (f"Recipient receives {money(t['amount_received'], european=True)} {t['receive_currency']}", "row"),
            ("", ""), (f"Transaction {t['ref']}", "sub")]


LAYOUTS = {"app": (layout_app, "sans"), "bank": (layout_bank, "serif"), "email": (layout_email, "sans"),
           "slip": (layout_slip, "mono"), "norate": (layout_norate, "sans"), "european": (layout_european, "sans")}


def render(lines: list[tuple[str, str]], kind: str, width: int = 1100) -> Image.Image:
    sizes = {"title": 44, "big": 36, "row": 28, "sub": 22, "": 20}
    height = 120 + sum(sizes[s] * 1.6 for _, s in lines) + 80
    img = Image.new("RGB", (width, int(height)), "white")
    draw = ImageDraw.Draw(img)
    y = 60
    for text, style in lines:
        f = font(kind, sizes[style])
        draw.text((60, y), text, fill=(20, 20, 20) if style != "sub" else (90, 90, 90), font=f)
        y += int(sizes[style] * 1.6)
    draw.text((60, y + 20), FOOTER, fill=(150, 150, 150), font=font("sans", 18))
    return img


def degrade(img: Image.Image, rng: random.Random, level: int) -> Image.Image:
    if level == 0:
        return img
    if level >= 1:
        img = img.rotate(rng.uniform(-1.5, 1.5), expand=True, fillcolor="white")
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 1.0)))
    if level >= 2:
        w, h = img.size
        img = img.resize((int(w * 0.6), int(h * 0.6)))
        noise = Image.effect_noise(img.size, 18).convert("RGB")
        img = Image.blend(img, noise, 0.08)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=rng.choice([55, 70, 85]))
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def text_pdf(lines: list[tuple[str, str]], path: Path) -> None:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    ttf = next((d / n for n in FONTS["sans"] for d in FONT_DIRS if (d / n).exists()), None)
    if ttf:
        pdf.add_font("body", "", str(ttf))
        pdf.set_font("body", size=12)
    else:
        pdf.set_font("helvetica", size=12)
    for text, style in lines:
        pdf.set_font_size({"title": 18, "big": 15, "row": 12, "sub": 10, "": 8}[style])
        pdf.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font_size(8)
    pdf.cell(0, 10, FOOTER, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def make_truth(rng: random.Random, i: int, layout: str) -> dict:
    send, recv, amounts = rng.choice(ROUTES)
    if layout == "european":
        send, recv, amounts = rng.choice([r for r in ROUTES if r[0] == "EUR"])
    start = dt.date(2024, 4, 1) if recv in {"NGN", "PKR", "KES"} or send in {"NGN"} else dt.date(2023, 1, 1)
    day = random_weekday(rng, start, dt.date(2026, 9, 1))
    mid = fx.get_rate(send, recv, day)
    markup = round(rng.choice([rng.uniform(0.0, 0.8), rng.uniform(0.8, 2.5), rng.uniform(2.5, 4.5)]), 3)
    rate = mid.rate * (1 - markup / 100)
    decimals = 4 if rate < 1000 else 2
    rate_printed = round(rate, decimals)
    amount = float(rng.choice(amounts)) + rng.choice([0, 0, 0.5, 25])
    fee = 0.0 if rng.random() < 0.15 else rng.choice([0.99, 1.99, 2.99, 3.99, 4.99, 7.5, 12.0, 25.0, 35.0])
    received = round(amount * rate_printed, 2)
    inverted = layout in {"bank", "slip"} and rng.random() < 0.5
    if inverted:
        rate_text = f"{1 / rate_printed:.6f}" if 1 / rate_printed < 1 else f"{1 / rate_printed:.4f}"
    else:
        rate_text = money(rate_printed, decimals, european=(layout == "european"))
    date_style = {"app": "long", "bank": rng.choice(["us" if send == "USD" else "dayfirst", "iso"]),
                  "email": "short", "slip": "iso", "norate": "daymonth", "european": "dayfirst"}[layout]
    printed_rate = None if layout == "norate" else (float(rate_text) if inverted else rate_printed)
    return {
        "id": f"r{i:02d}", "layout": layout, "provider": rng.choice(PROVIDERS),
        "send_currency": send, "receive_currency": recv, "amount_sent": amount, "fee": fee,
        "total_paid": round(amount + fee, 2), "exchange_rate": printed_rate, "rate_text": rate_text,
        "rate_inverted": inverted, "amount_received": received, "transfer_date": day.isoformat(),
        "date_text": fmt_date(day, date_style), "ref": f"{rng.randrange(10**9, 10**10)}",
        "mid_rate": mid.rate, "mid_rate_date": mid.rate_date.isoformat(), "mid_source": mid.source,
        "true_markup_pct": (mid.rate - rate_printed) / mid.rate * 100,
        "true_markup_cost": amount * (mid.rate - rate_printed) / mid.rate,
    }


def main(n: int = 40, seed: int = SEED, out: Path = OUT) -> None:
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("r*.*"):
        old.unlink()
    layouts = list(LAYOUTS)
    truths = []
    for i in range(1, n + 1):
        layout = layouts[(i - 1) % len(layouts)]
        t = make_truth(rng, i, layout)
        build, kind = LAYOUTS[layout]
        lines = build(t)
        fmt = ["png", "jpg", "png", "pdf-text", "pdf-scan"][(i - 1) % 5]
        level = 0 if fmt in ("png", "pdf-text") else rng.choice([1, 2])
        if fmt == "pdf-text":
            path = out / f"{t['id']}.pdf"
            text_pdf(lines, path)
        else:
            img = degrade(render(lines, kind), rng, level)
            path = out / (f"{t['id']}.pdf" if fmt == "pdf-scan" else f"{t['id']}.{fmt}")
            img.save(path, **({"resolution": 150} if fmt == "pdf-scan" else {}))
        t.update(file=path.name, format=fmt, degradation=level)
        truths.append(t)
        print(f"{t['id']} {layout:8} {fmt:8} {t['send_currency']}->{t['receive_currency']} markup {t['true_markup_pct']:.2f}%")
    (out / "truth.json").write_text(json.dumps(truths, indent=2))
    print(f"Wrote {len(truths)} receipts to {out}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    main(a.n, a.seed, a.out)
