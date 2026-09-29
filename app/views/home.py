import streamlit as st

import theme

theme.header(
    "Find the cheapest way to send money abroad.",
    "Every international transfer costs you twice: the <b>fee</b> you can see, and a <b>worse exchange rate</b> "
    "that you usually can't. FairSend adds both up for every provider, so you can see which one gets the most "
    "money there. Made for international students paying tuition and sending money home.",
)

st.subheader("What do you want to do?")
TASKS = [
    ("Compare providers", "See which provider would get the most money to your family.", "views/compare.py"),
    ("Compare tuition costs", "See the cheapest way to pay a big bill from home, and if it would arrive in time.",
     "views/tuition.py"),
    ("Check a past receipt", "Find out how much a transfer you already made really cost.", "views/receipt.py"),
    ("Set a rate alert", "Get an email when the exchange rate reaches your target.", "views/alerts.py"),
]
for row in (TASKS[:2], TASKS[2:]):
    cols = st.columns(2)
    for col, (title, text, page) in zip(cols, row):
        with col, st.container(border=True):
            theme.task(title, text)
            st.page_link(page, label="Open", icon=":material/arrow_forward:")

st.subheader("How it works")
st.html("""<div class="fs-steps">
<div><b>1. Real prices</b>The World Bank checks what hundreds of providers really charge, every quarter.</div>
<div><b>2. The real exchange rate</b>We compare each provider's rate with the rate banks trade at today. The gap is a
hidden cost.</div>
<div><b>3. Your answer</b>You see how much would arrive with each option, and which one is cheapest.</div>
</div>""")
theme.note("FairSend doesn't send or hold money. It compares real prices so you can choose a provider, then you send "
           "with that provider directly. Your receipts and questions stay on this computer. Not financial advice.")
