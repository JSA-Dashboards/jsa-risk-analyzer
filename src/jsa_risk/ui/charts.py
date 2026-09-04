"""Scenario charts — P&L heatmap, delta-scenario strip, payoff chart, and per-contract
Greeks bars. Ported from the JSA Risk Analyzer HTML tool's hand-rolled SVG/DOM renderers,
using plotly instead — a practical substitution (like Phase 1's scipy-for-erf swap), not
a pixel-for-pixel port. The underlying numbers (portfolio_pnl_at/portfolio_delta_at) are
unchanged from the original tool.
"""
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

import plotly.graph_objects as go
import streamlit as st

from jsa_risk.pricing.portfolio import portfolio_delta_at, portfolio_pnl_at
from jsa_risk.pricing.stress import Position, PositionEval, StressState, days_to_expiry, eval_position

PRICE_SHOCKS = [-0.50, -0.40, -0.30, -0.20, -0.10, 0.0, 0.10, 0.20, 0.30, 0.40, 0.50]
VOL_SHOCKS_BOTTOM_UP = [-30, -15, 0, 15, 30]  # last item renders at the top of the heatmap
ACCENT = "#3987e5"
MUTED = "#898781"
GAIN = "#3a9d5d"
LOSS = "#c0392b"


def _fmt_cents(v: float) -> str:
    sign = "-" if v < 0 else ("+" if v > 0 else "")
    return f"{sign}{round(abs(v) * 100)}¢"


def _fmt_pct_signed(v: float) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}{v:g}%"


def _fmt_dollars_signed(v: float) -> str:
    sign = "-" if v < 0 else "+"
    return f"{sign}${abs(v):,.0f}"


def _fmt_bu_signed(v: float) -> str:
    sign = "-" if v < 0 else "+"
    return f"{sign}{abs(v):,.0f} bu"


def render_pnl_heatmap(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    today: Optional[date] = None,
) -> None:
    price_labels = [_fmt_cents(p) for p in PRICE_SHOCKS]
    vol_labels = [_fmt_pct_signed(v) for v in VOL_SHOCKS_BOTTOM_UP]
    z = [
        [portfolio_pnl_at(positions, get_contract_price, stress, ps, vs, 0, today) for ps in PRICE_SHOCKS]
        for vs in VOL_SHOCKS_BOTTOM_UP
    ]
    max_abs = max(1.0, max(abs(v) for row in z for v in row))
    text = [[_fmt_dollars_signed(v) for v in row] for row in z]

    fig = go.Figure(
        go.Heatmap(
            x=price_labels,
            y=vol_labels,
            z=z,
            colorscale="RdYlGn",
            zmid=0,
            zmin=-max_abs,
            zmax=max_abs,
            text=text,
            texttemplate="%{text}",
            textfont={"size": 11},
            hovertemplate="Price %{x} · Vol %{y}<br>Book P&L: %{text}<extra></extra>",
            showscale=False,
        )
    )
    base_price_label, base_vol_label = _fmt_cents(0.0), _fmt_pct_signed(0)
    fig.add_trace(
        go.Scatter(
            x=[base_price_label],
            y=[base_vol_label],
            mode="markers",
            marker=dict(size=34, color="rgba(0,0,0,0)", line=dict(color=ACCENT, width=3), symbol="square"),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.update_layout(
        height=300,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Price shock →",
        yaxis_title="Vol shock ↑",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_delta_scenario(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    today: Optional[date] = None,
) -> None:
    price_labels = [_fmt_cents(p) for p in PRICE_SHOCKS]
    row = [portfolio_delta_at(positions, get_contract_price, stress, ps, today) for ps in PRICE_SHOCKS]
    max_abs = max(1.0, max(abs(v) for v in row))
    base = row[PRICE_SHOCKS.index(0.0)]
    text = [[f"{v:,.0f}" for v in row]]

    fig = go.Figure(
        go.Heatmap(
            x=price_labels,
            y=["Net delta (bu)"],
            z=[row],
            colorscale="RdYlGn",
            zmid=0,
            zmin=-max_abs,
            zmax=max_abs,
            text=text,
            texttemplate="%{text}",
            textfont={"size": 11},
            hovertemplate="Price %{x}<br>Net delta: %{text} bu<extra></extra>",
            showscale=False,
        )
    )
    fig.update_layout(
        height=110,
        margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
    )
    st.plotly_chart(fig, use_container_width=True)

    lo, hi = row[0], row[-1]
    st.caption(
        f"Cell = net position delta (bu) under that price shock, sign colored long (green) vs short (red). "
        f"At -50¢: {lo:,.0f} bu (Δ {lo - base:+,.0f} bu) · "
        f"At +50¢: {hi:,.0f} bu (Δ {hi - base:+,.0f} bu) vs current {base:,.0f} bu."
    )


def _frange(start: float, stop: float, step: float) -> List[float]:
    n = round((stop - start) / step)
    return [round(start + i * step, 2) for i in range(n + 1)]


def render_payoff_chart(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    today: Optional[date] = None,
) -> None:
    range_ = 0.50
    xs = _frange(-range_, range_, 0.10)
    x_cents = [round(s * 100) for s in xs]

    dtes = [days_to_expiry(p.expiry_date, today) for p in positions]
    dtes = [d for d in dtes if d is not None and d > 0]
    nearest_dte = min(dtes) if dtes else None

    horizons = [
        {"label": "Today", "days": 0, "dash": None, "width": 2.5, "opacity": 1.0, "color": ACCENT},
        {"label": "+7d", "days": 7, "dash": "dash", "width": 1.5, "opacity": 0.7, "color": ACCENT},
        {"label": "+30d", "days": 30, "dash": "dot", "width": 1.5, "opacity": 0.45, "color": ACCENT},
    ]
    if nearest_dte is not None:
        horizons.append(
            {"label": f"At expiry ({nearest_dte}d)", "days": nearest_dte, "dash": "dashdot",
             "width": 1.5, "opacity": 0.9, "color": MUTED}
        )
    for h in horizons:
        h["ys"] = [portfolio_pnl_at(positions, get_contract_price, stress, s, 0, h["days"], today) for s in xs]

    cur_val = portfolio_pnl_at(positions, get_contract_price, stress, 0, 0, 0, today)

    fig = go.Figure()
    today_h = horizons[0]
    fig.add_trace(
        go.Scatter(
            x=x_cents, y=today_h["ys"], mode="lines", name=today_h["label"],
            line=dict(width=today_h["width"], color=today_h["color"]),
            fill="tozeroy", fillcolor="rgba(57,135,229,0.12)",
        )
    )
    for h in horizons[1:]:
        fig.add_trace(
            go.Scatter(
                x=x_cents, y=h["ys"], mode="lines", name=h["label"],
                line=dict(width=h["width"], color=h["color"], dash=h["dash"]),
                opacity=h["opacity"],
            )
        )
    fig.add_trace(
        go.Scatter(
            x=[0], y=[cur_val], mode="markers", name="Current",
            marker=dict(size=9, color=ACCENT, line=dict(color="white", width=1)),
            showlegend=False,
        )
    )
    fig.add_vline(x=0, line_dash="dot", line_color=MUTED)
    fig.update_layout(
        hovermode="x unified",
        xaxis_title="Price shock (¢)",
        yaxis_title="Book P&L ($)",
        height=320,
        margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"Current mark: **{_fmt_dollars_signed(cur_val)}** at 0¢ shock (blue dot). Other lines hold vol at "
        f"the current scenario and roll time forward — theta & gamma reshape the curve as they decay."
    )


def _contract_group_key(p: Position) -> str:
    return p.expiry_date.isoformat() if p.expiry_date else f"Futures {p.label}"


def _contract_group_label(key: str) -> str:
    if key.startswith("Futures"):
        return key
    d = date.fromisoformat(key)
    return f"{d.strftime('%b')} {d.day}, '{d.strftime('%y')}"


def _group_by_contract(
    positions: List[Position],
    evals: Dict[int, PositionEval],
    value_fn: Callable[[PositionEval], float],
) -> Tuple[List[str], Dict[str, float]]:
    data: Dict[str, float] = {}
    order: List[str] = []
    for p in positions:
        k = _contract_group_key(p)
        if k not in data:
            data[k] = 0.0
            order.append(k)
        data[k] += value_fn(evals[id(p)])
    order.sort(key=lambda k: (k.startswith("Futures"), k))
    return order, data


def _render_mini_bar(
    col,
    title: str,
    unit: str,
    order: List[str],
    data: Dict[str, float],
    fmt: Callable[[float], str],
) -> None:
    with col:
        st.markdown(f"**{title}** <span style='font-size:11px;color:{MUTED}'>{unit}</span>", unsafe_allow_html=True)
        if not order:
            st.caption("No positions.")
            return
        labels = [_contract_group_label(k) for k in order]
        values = [data[k] for k in order]
        max_abs = max(1.0, max(abs(v) for v in values))
        colors = [GAIN if v >= 0 else LOSS for v in values]
        text = [fmt(v) for v in values]
        fig = go.Figure(
            go.Bar(
                x=values, y=labels, orientation="h",
                marker_color=colors, text=text, textposition="outside",
                hovertemplate=f"%{{y}}<br>{title}: %{{text}}<extra></extra>",
            )
        )
        fig.update_layout(
            height=34 * len(order) + 50,
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis=dict(range=[-max_abs * 1.3, max_abs * 1.3], zeroline=True, zerolinewidth=1, showgrid=False,
                       showticklabels=False),
            yaxis=dict(autorange="reversed"),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(size=11),
        )
        st.plotly_chart(fig, use_container_width=True)


def render_greeks_bars(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
) -> None:
    evals = {id(p): eval_position(p, stress, get_contract_price) for p in positions}
    cols = st.columns(3)
    order, delta_data = _group_by_contract(positions, evals, lambda r: r.delta_d)
    _render_mini_bar(cols[0], "Delta (bu)", "per $1", order, delta_data, _fmt_bu_signed)
    order, vega_data = _group_by_contract(positions, evals, lambda r: r.vega_d)
    _render_mini_bar(cols[1], "Vega $", "per vol pt", order, vega_data, _fmt_dollars_signed)
    order, theta_data = _group_by_contract(positions, evals, lambda r: r.theta_d)
    _render_mini_bar(cols[2], "Theta $", "per day", order, theta_data, _fmt_dollars_signed)
