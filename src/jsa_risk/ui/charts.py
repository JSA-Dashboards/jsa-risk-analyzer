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

from jsa_risk.pricing.commodities import CORN, CommoditySpec
from jsa_risk.pricing.portfolio import portfolio_delta_at, portfolio_pnl_at, portfolio_reference_price
from jsa_risk.pricing.stress import Position, PositionEval, StressState, eval_position

# Price shocks are a percent of each contract's own value -- not a flat grain-price move --
# so the same grid works for corn, soybeans, and cattle alike. Cents-per-unit labels are
# derived from the portfolio's reference price (see portfolio_reference_price).
PRICE_SHOCK_STEP = 5      # % per increment
DEFAULT_SHOCK_RANGE = 25  # default window: +/-25% of contract value
PRICE_SHOCKS = [float(p) for p in range(-DEFAULT_SHOCK_RANGE, DEFAULT_SHOCK_RANGE + 1, PRICE_SHOCK_STEP)]
VOL_SHOCKS_BOTTOM_UP = [-30, -15, 0, 15, 30]  # last item renders at the top of the heatmap
ACCENT = "#3987e5"
MUTED = "#898781"
GAIN = "#3a9d5d"
LOSS = "#c0392b"
# One solid color per distinct expiry line on the payoff chart -- avoids red/green (already
# meaning loss/gain everywhere else) and blue (Today), cycles if there are more expiries.
EXPIRY_COLORS = ["#e8a33d", "#9b6bce", "#4fb8af", "#d9779a", "#c9a227", "#6a8caf"]


def _fmt_cents(v: float) -> str:
    """`v` is a price move in dollars per unit; shown as cents, with a decimal under 10¢
    so small moves (e.g. 5% of a cheap contract) don't all round to the same label."""
    cents = abs(v) * 100
    sign = "-" if v < 0 else ("+" if v > 0 else "")
    body = f"{cents:.1f}" if 0 < cents < 10 else f"{cents:.0f}"
    return f"{sign}{body}¢"


def _fmt_pct_signed(v: float) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}{v:g}%"


def _shock_cents(pct: float, ref_price: float) -> float:
    return pct / 100 * ref_price


def _shock_tick(pct: float, ref_price: float) -> str:
    """Two-line axis tick: the % shock over its cents-per-unit equivalent."""
    return f"{_fmt_pct_signed(pct)}<br>{_fmt_cents(_shock_cents(pct, ref_price))}"


def _shock_hover(pct: float, ref_price: float) -> str:
    return f"{_fmt_pct_signed(pct)} ({_fmt_cents(_shock_cents(pct, ref_price))})"


def _shock_axis_title(ref_price: float, commodity: CommoditySpec) -> str:
    return f"Price shock (% of contract · ≈¢/{commodity.unit} at ${ref_price:.2f} avg) →"


def _fmt_dollars_signed(v: float) -> str:
    sign = "-" if v < 0 else "+"
    return f"{sign}${abs(v):,.0f}"


def _fmt_unit_signed(v: float, unit: str) -> str:
    sign = "-" if v < 0 else "+"
    return f"{sign}{abs(v):,.0f} {unit}"


def render_pnl_heatmap(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    today: Optional[date] = None,
    commodity: CommoditySpec = CORN,
) -> None:
    # Purely numeric x/y (0,1,2,...) with cosmetic tick labels via update_xaxes/yaxes,
    # rather than handing the Heatmap trace the label strings directly. Plotly's implicit
    # category-axis positioning turned out unreliable for a second overlaid trace: both a
    # go.Shape rect and a numeric-coordinate scatter line, tried in turn to outline the
    # current-scenario cell, landed off-axis (Plotly silently extended the axis with new
    # tick positions instead of aligning to the heatmap's categories). Numeric coordinates
    # end that ambiguity -- the heatmap and the highlight now share one unambiguous grid.
    ref_price = portfolio_reference_price(positions, get_contract_price, stress, today, commodity)
    price_ticks = [_shock_tick(p, ref_price) for p in PRICE_SHOCKS]
    price_hover = [_shock_hover(p, ref_price) for p in PRICE_SHOCKS]
    vol_labels = [_fmt_pct_signed(v) for v in VOL_SHOCKS_BOTTOM_UP]
    x_idx = list(range(len(PRICE_SHOCKS)))
    y_idx = list(range(len(VOL_SHOCKS_BOTTOM_UP)))
    z = [
        [portfolio_pnl_at(positions, get_contract_price, stress, ps, vs, 0, today, commodity) for ps in PRICE_SHOCKS]
        for vs in VOL_SHOCKS_BOTTOM_UP
    ]
    max_abs = max(1.0, max(abs(v) for row in z for v in row))
    text = [[_fmt_dollars_signed(v) for v in row] for row in z]
    customdata = [[[price_hover[j], vol_labels[i]] for j in x_idx] for i in y_idx]

    fig = go.Figure(
        go.Heatmap(
            x=x_idx,
            y=y_idx,
            z=z,
            colorscale="RdYlGn",
            zmid=0,
            zmin=-max_abs,
            zmax=max_abs,
            text=text,
            texttemplate="%{text}",
            textfont={"size": 11},
            customdata=customdata,
            hovertemplate="Price %{customdata[0]} · Vol %{customdata[1]}<br>Book P&L: %{text}<extra></extra>",
            showscale=False,
        )
    )
    # Outline the current-scenario (0 price, 0 vol) cell -- a closed line path at
    # +/-0.5 index either side of its center, tracing exactly the cell's own boundary.
    base_price_idx = PRICE_SHOCKS.index(0.0)
    base_vol_idx = VOL_SHOCKS_BOTTOM_UP.index(0)
    px0, px1 = base_price_idx - 0.5, base_price_idx + 0.5
    py0, py1 = base_vol_idx - 0.5, base_vol_idx + 0.5
    fig.add_trace(
        go.Scatter(
            x=[px0, px1, px1, px0, px0],
            y=[py0, py0, py1, py1, py0],
            mode="lines",
            line=dict(color=ACCENT, width=3),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.update_layout(
        height=340,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(title=_shock_axis_title(ref_price, commodity), tickvals=x_idx, ticktext=price_ticks,
                   automargin=True),
        yaxis=dict(title="Vol shock ↑", tickvals=y_idx, ticktext=vol_labels, automargin=True),
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
    commodity: CommoditySpec = CORN,
) -> None:
    unit = commodity.unit
    ref_price = portfolio_reference_price(positions, get_contract_price, stress, today, commodity)
    price_ticks = [_shock_tick(p, ref_price) for p in PRICE_SHOCKS]
    price_hover = [_shock_hover(p, ref_price) for p in PRICE_SHOCKS]
    x_idx = list(range(len(PRICE_SHOCKS)))
    row = [portfolio_delta_at(positions, get_contract_price, stress, ps, today, commodity) for ps in PRICE_SHOCKS]
    max_abs = max(1.0, max(abs(v) for v in row))
    base = row[PRICE_SHOCKS.index(0.0)]
    text = [[f"{v:,.0f}" for v in row]]

    fig = go.Figure(
        go.Heatmap(
            x=x_idx,
            y=[f"Net delta ({unit})"],
            z=[row],
            colorscale="RdYlGn",
            zmid=0,
            zmin=-max_abs,
            zmax=max_abs,
            text=text,
            texttemplate="%{text}",
            textfont={"size": 11},
            customdata=[price_hover],
            hovertemplate=f"Price %{{customdata}}<br>Net delta: %{{text}} {unit}<extra></extra>",
            showscale=False,
        )
    )
    fig.update_layout(
        height=150,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(title=_shock_axis_title(ref_price, commodity), tickvals=x_idx, ticktext=price_ticks,
                   automargin=True),
        yaxis=dict(automargin=True),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
    )
    st.plotly_chart(fig, use_container_width=True)

    lo, hi = row[0], row[-1]
    st.caption(
        f"Cell = net position delta ({unit}) under that price shock, sign colored long (green) vs short (red). "
        f"At {_shock_hover(PRICE_SHOCKS[0], ref_price)}: {lo:,.0f} {unit} (Δ {lo - base:+,.0f} {unit}) · "
        f"At {_shock_hover(PRICE_SHOCKS[-1], ref_price)}: {hi:,.0f} {unit} (Δ {hi - base:+,.0f} {unit}) "
        f"vs current {base:,.0f} {unit}."
    )


def render_payoff_chart(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    today: Optional[date] = None,
    commodity: CommoditySpec = CORN,
) -> None:
    # Compute well past the default view so zooming/panning out reveals a real, continuing
    # curve instead of hitting blank space at the edge of what used to be the only data.
    compute_range = DEFAULT_SHOCK_RANGE * 3
    default_view = DEFAULT_SHOCK_RANGE
    xs = [float(p) for p in range(-compute_range, compute_range + 1, PRICE_SHOCK_STEP)]  # % of contract value
    ref_price = portfolio_reference_price(positions, get_contract_price, stress, today, commodity)
    # Tick at every step inside the default window, then only at the wider quarter marks so
    # a zoomed-out view doesn't turn the axis into an unreadable wall of two-line labels.
    tick_vals = [x for x in xs if abs(x) <= default_view or x % DEFAULT_SHOCK_RANGE == 0]
    tick_text = [_shock_tick(x, ref_price) for x in tick_vals]

    # One expiry date per distinct expiration among current option positions -- not just
    # the nearest -- so a book with staggered expiries shows every real decay cliff.
    expiry_dates = sorted({p.expiry_date for p in positions if p.expiry_date is not None})
    today_ = today or date.today()
    expiry_dtes = [(d, (d - today_).days) for d in expiry_dates]
    expiry_dtes = [(d, dte) for d, dte in expiry_dtes if dte > 0]

    horizons = [
        {"label": "Today", "days": 0, "dash": None, "width": 2.5, "opacity": 1.0, "color": ACCENT},
    ]
    for i, (expiry_date, dte) in enumerate(expiry_dtes):
        horizons.append({
            "label": f"{expiry_date.strftime('%b')} {expiry_date.day} ({dte}d)",
            "days": dte,
            "dash": None,
            "width": 2.0,
            "opacity": 1.0,
            "color": EXPIRY_COLORS[i % len(EXPIRY_COLORS)],
        })
    for h in horizons:
        h["ys"] = [portfolio_pnl_at(positions, get_contract_price, stress, s, 0, h["days"], today, commodity) for s in xs]

    cur_val = portfolio_pnl_at(positions, get_contract_price, stress, 0, 0, 0, today, commodity)

    # Fit the initial Y-range to just the default-visible window's values, not the whole
    # (much wider) computed dataset -- otherwise the visible curve gets squashed into a
    # sliver by extremes that only occur far outside the default zoom.
    visible_ys = [
        y for h in horizons for x, y in zip(xs, h["ys"]) if abs(x) <= default_view
    ]
    y_lo, y_hi = min(visible_ys), max(visible_ys)
    y_pad = max((y_hi - y_lo) * 0.1, 1.0)

    fig = go.Figure()
    today_h = horizons[0]
    fig.add_trace(
        go.Scatter(
            x=xs, y=today_h["ys"], mode="lines", name=today_h["label"],
            line=dict(width=today_h["width"], color=today_h["color"]),
            fill="tozeroy", fillcolor="rgba(57,135,229,0.12)",
            customdata=[_shock_hover(x, ref_price) for x in xs],
            hovertemplate="%{y:$,.0f} · shock %{customdata}<extra>" + today_h["label"] + "</extra>",
        )
    )
    for h in horizons[1:]:
        fig.add_trace(
            go.Scatter(
                x=xs, y=h["ys"], mode="lines", name=h["label"],
                line=dict(width=h["width"], color=h["color"], dash=h["dash"]),
                opacity=h["opacity"],
                hovertemplate="%{y:$,.0f}<extra>" + h["label"] + "</extra>",
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
        xaxis=dict(
            title=_shock_axis_title(ref_price, commodity),
            range=[-default_view, default_view],
            tickvals=tick_vals, ticktext=tick_text,
            ticksuffix="%", automargin=True,
        ),
        yaxis_title="Book P&L ($)",
        yaxis=dict(tickprefix="$", separatethousands=True, range=[y_lo - y_pad, y_hi + y_pad]),
        height=520,
        margin=dict(l=10, r=30, t=10, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"Current mark: **{_fmt_dollars_signed(cur_val)}** at a 0% shock (blue dot). Default view is "
        f"±{DEFAULT_SHOCK_RANGE}% of contract value; drag or zoom out to see up to ±{compute_range}%. "
        f"Other lines hold vol at the current scenario and roll time forward — theta & gamma "
        f"reshape the curve as they decay."
    )


def _contract_group_key(p: Position) -> str:
    if p.is_cash:
        return f"Futures cash {p.underlying_override}"
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
    commodity: CommoditySpec = CORN,
) -> None:
    evals = {id(p): eval_position(p, stress, get_contract_price, commodity=commodity) for p in positions}
    cols = st.columns(3)
    order, delta_data = _group_by_contract(positions, evals, lambda r: r.delta_d)
    _render_mini_bar(cols[0], f"Delta ({commodity.unit})", "per $1", order, delta_data,
                      lambda v: _fmt_unit_signed(v, commodity.unit))
    order, vega_data = _group_by_contract(positions, evals, lambda r: r.vega_d)
    _render_mini_bar(cols[1], "Vega $", "per vol pt", order, vega_data, _fmt_dollars_signed)
    order, theta_data = _group_by_contract(positions, evals, lambda r: r.theta_d)
    _render_mini_bar(cols[2], "Theta $", "per day", order, theta_data, _fmt_dollars_signed)
