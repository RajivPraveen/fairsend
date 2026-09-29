"""FairSend look and feel: a minimal palette, chart template, CSS, and a few small HTML components.

One accent color (money green) on a neutral background. Chart series colors (green for the hidden cost in the
exchange rate, gold for the fee) were checked for colorblind separation and contrast in both light and dark mode;
gold is below 3:1 contrast on white, so gold marks always carry a label or legend.
"""

from __future__ import annotations

import base64
import html

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

LIGHT = {
    "bg": "#FFFFFF", "card": "#FFFFFF", "wash": "#F6F7F6", "ink": "#111418", "ink2": "#4B5563", "muted": "#8A919B",
    "border": "#E6E8EB", "grid": "#EEF0F2", "accent": "#0F7A4F", "accent_soft": "#EAF5EF", "warn": "#B4531C",
    "s_hidden": "#0F7A4F", "s_fee": "#E0A21B", "s_third": "#3A6FC4",
}
DARK = {
    "bg": "#0F1113", "card": "#15181B", "wash": "#181B1E", "ink": "#F3F4F6", "ink2": "#B8BEC6", "muted": "#8A919B",
    "border": "#2A2E33", "grid": "#23272B", "accent": "#34C785", "accent_soft": "#15291F", "warn": "#E6874F",
    "s_hidden": "#20A06A", "s_fee": "#C47F0A", "s_third": "#6A8FE0",
}
CATEGORICAL_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
CATEGORICAL_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]

LOGO_MARK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><circle cx="24" cy="24" r="20" fill="#0F7A4F"/>
<text x="24" y="31.5" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-weight="700" font-size="21"
fill="#FFFFFF">$</text></svg>"""


def is_dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


def palette() -> dict:
    return DARK if is_dark() else LIGHT


def categorical() -> list[str]:
    return CATEGORICAL_DARK if is_dark() else CATEGORICAL_LIGHT


def register_plotly_template() -> None:
    p = palette()
    template = go.layout.Template()
    template.layout = go.Layout(
        font=dict(family="Plus Jakarta Sans, sans-serif", color=p["ink2"], size=13),
        title=dict(font=dict(color=p["ink"], size=15), x=0, xanchor="left"),
        colorway=categorical(), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor=p["grid"], linecolor=p["border"], zeroline=False, tickfont=dict(color=p["muted"]),
                   automargin=True),
        yaxis=dict(gridcolor=p["grid"], linecolor=p["border"], zeroline=False, tickfont=dict(color=p["muted"]),
                   automargin=True),
        legend=dict(orientation="h", y=-0.2, x=0, font=dict(color=p["ink2"])),
        hoverlabel=dict(bgcolor=p["card"], bordercolor=p["border"], font=dict(color=p["ink"])),
        margin=dict(l=10, r=10, t=40, b=10), bargap=0.3,
    )
    pio.templates["fairsend"] = template
    pio.templates.default = "fairsend"


def chart(fig: go.Figure) -> None:
    st.plotly_chart(fig, theme=None, use_container_width=True, config={"displayModeBar": False})


def inject_css() -> None:
    p = palette()
    st.html(f"""<style>
:root {{ --ink:{p['ink']}; --ink2:{p['ink2']}; --muted:{p['muted']}; --border:{p['border']}; --wash:{p['wash']};
  --card:{p['card']}; --accent:{p['accent']}; --accent-soft:{p['accent_soft']}; --warn:{p['warn']}; }}
.block-container {{ max-width: 860px; padding-top: 3.2rem; padding-bottom: 4rem; }}
h1 {{ font-size: 2.05rem !important; font-weight: 700 !important; letter-spacing: -0.025em; padding-bottom: .2rem !important; }}
h2, h3 {{ letter-spacing: -0.015em; }}
.fs-lead {{ color: var(--ink2); font-size: 1.06rem; line-height: 1.55; margin: 0 0 1.6rem; max-width: 62ch; }}
.fs-answer {{ border: 1px solid var(--border); border-radius: 18px; padding: 22px 24px; background: var(--card); margin: 6px 0 14px; }}
.fs-answer .k {{ font-size: .82rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }}
.fs-answer .v {{ font-size: 2.35rem; font-weight: 700; letter-spacing: -0.03em; color: var(--ink); line-height: 1.15; margin: 6px 0 8px; }}
.fs-answer .v .u {{ font-size: 1.1rem; font-weight: 600; color: var(--ink2); letter-spacing: 0; }}
.fs-answer .d {{ color: var(--ink2); font-size: 1rem; line-height: 1.55; }}
.fs-answer .d b {{ color: var(--ink); }}
.fs-answer.good {{ border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }}
.fs-list {{ border: 1px solid var(--border); border-radius: 16px; overflow: hidden; margin: 6px 0 12px; }}
.fs-row {{ display: grid; grid-template-columns: 28px 1fr auto; gap: 14px; align-items: center; padding: 13px 18px;
  border-top: 1px solid var(--border); background: var(--card); }}
.fs-row:first-child {{ border-top: none; }}
.fs-row .n {{ color: var(--muted); font-weight: 600; font-size: .9rem; }}
.fs-row .t {{ font-weight: 600; color: var(--ink); }}
.fs-row .s {{ font-size: .86rem; color: var(--muted); margin-top: 2px; }}
.fs-row .r {{ text-align: right; }}
.fs-row .r .t {{ font-variant-numeric: tabular-nums; }}
.fs-tag {{ display: inline-block; font-size: .72rem; font-weight: 700; color: var(--accent); background: var(--accent-soft);
  border-radius: 999px; padding: 2px 8px; margin-left: 8px; vertical-align: 2px; }}
.fs-tag.warn {{ color: var(--warn); background: transparent; border: 1px solid var(--warn); }}
.fs-note {{ color: var(--muted); font-size: .86rem; line-height: 1.5; margin: 4px 0 10px; }}
.fs-bar {{ display: flex; height: 8px; border-radius: 999px; overflow: hidden; background: var(--wash); margin: 12px 0 8px; }}
.fs-legend {{ display: flex; flex-wrap: wrap; gap: 18px; font-size: .86rem; color: var(--ink2); }}
.fs-dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px; }}
.fs-task .t {{ font-weight: 700; font-size: 1.08rem; color: var(--ink); }}
.fs-task .s {{ color: var(--ink2); font-size: .95rem; margin-top: 3px; }}
.fs-steps {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; margin-top: 8px; }}
.fs-steps div {{ color: var(--ink2); font-size: .93rem; line-height: 1.5; }}
.fs-steps b {{ display: block; color: var(--ink); font-size: 1rem; margin-bottom: 2px; }}
@media (max-width: 640px) {{ .fs-steps {{ grid-template-columns: 1fr; }} .fs-answer .v {{ font-size: 1.9rem; }} }}
[data-testid="stMetric"] {{ border: 1px solid var(--border); border-radius: 14px; padding: 12px 14px; }}
</style>""")


# ---------------------------------------------------------------------------------------------- components

def svg_img(svg: str, style: str = "") -> str:
    data = base64.b64encode(svg.encode()).decode()
    return f'<img alt="" style="{style}" src="data:image/svg+xml;base64,{data}"/>'


def header(title: str, lead: str) -> None:
    st.title(title)
    st.html(f'<p class="fs-lead">{lead}</p>')


def answer(label: str, value: str, detail: str = "", unit: str = "", good: bool = False) -> None:
    """The one big result on a page: a label, a big value, and a plain-language sentence."""
    u = f' <span class="u">{html.escape(unit)}</span>' if unit else ""
    st.html(f'<div class="fs-answer {"good" if good else ""}"><div class="k">{html.escape(label)}</div>'
            f'<div class="v">{html.escape(value)}{u}</div><div class="d">{detail}</div></div>')


def option_list(rows: list[dict]) -> None:
    """Simple ranked list. Each row: title, subtitle, right, right_sub, tag (optional), tag_warn (optional)."""
    items = []
    for i, r in enumerate(rows, start=1):
        tag = ""
        if r.get("tag"):
            tag = f'<span class="fs-tag {"warn" if r.get("tag_warn") else ""}">{html.escape(r["tag"])}</span>'
        items.append(
            f'<div class="fs-row"><div class="n">{i}</div>'
            f'<div><div class="t">{html.escape(r["title"])}{tag}</div><div class="s">{html.escape(r.get("subtitle", ""))}</div></div>'
            f'<div class="r"><div class="t">{html.escape(r["right"])}</div><div class="s">{html.escape(r.get("right_sub", ""))}</div></div></div>')
    st.html(f'<div class="fs-list">{"".join(items)}</div>')


def note(text: str) -> None:
    st.html(f'<p class="fs-note">{text}</p>')


def cost_bar(fee: float, hidden: float, fee_label: str, hidden_label: str) -> None:
    """Thin bar splitting a cost into the fee you see and the cost hidden in the exchange rate."""
    p = palette()
    total = max(fee, 0) + max(hidden, 0)
    if total <= 0:
        return
    f = max(fee, 0) / total * 100
    st.html(f"""<div class="fs-bar"><span style="width:{f:.1f}%;background:{p['s_fee']}"></span>
<span style="width:{100 - f:.1f}%;background:{p['s_hidden']}"></span></div>
<div class="fs-legend"><span><span class="fs-dot" style="background:{p['s_fee']}"></span>{html.escape(fee_label)}</span>
<span><span class="fs-dot" style="background:{p['s_hidden']}"></span>{html.escape(hidden_label)}</span></div>""")


def task(title: str, text: str) -> None:
    st.html(f'<div class="fs-task"><div class="t">{html.escape(title)}</div><div class="s">{html.escape(text)}</div></div>')
