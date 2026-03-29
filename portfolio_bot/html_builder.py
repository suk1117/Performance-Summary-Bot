from __future__ import annotations
import json
import pandas as pd
from datetime import datetime, date, timedelta
from html import escape

from portfolio_bot.storage.history import load_history
from portfolio_bot.storage.cashflow import load_cashflow, compute_combined_nav
from portfolio_bot.storage.trades import compute_realized_pnl

PALETTE = [
    "#0ea5e9","#8b5cf6","#f59e0b","#ef4444",
    "#10b981","#f97316","#06b6d4","#84cc16","#ec4899","#6366f1",
]


def _build_portfolio_tabs(
    all_portfolios: dict,
    current_pname: str,
    uid: int = 0,
    token: str = "",
) -> str:
    if not all_portfolios:
        return ""
    tabs = ""
    if len(all_portfolios) > 1:
        if current_pname == "all":
            tabs += '<span class="tab active" style="display:inline-flex;align-items:center;cursor:default">전체</span>'
        else:
            tabs += f'<a href="/u/{uid}/p/all?t={token}" class="tab">전체</a>'
    for pname, p in all_portfolios.items():
        name = escape(p.get("name", pname))
        name_esc = name.replace("'", "\\'")
        if pname == current_pname:
            del_btn = ""
            if len(all_portfolios) > 1:
                del_btn = (
                    f'<button onclick="deletePortfolio(\'{pname}\')" title="삭제" '
                    f'style="background:none;border:none;cursor:pointer;padding:1px 3px;'
                    f'font-size:.7rem;color:#94a3b8;line-height:1;margin-left:2px">🗑️</button>'
                )
            ren_btn = (
                f'<button onclick="openRenameModal(\'{pname}\',\'{name_esc}\')" title="이름 변경" '
                f'style="background:none;border:none;cursor:pointer;padding:1px 3px;'
                f'font-size:.7rem;color:#94a3b8;line-height:1;margin-left:4px">✏️</button>'
            )
            tabs += (
                f'<span class="tab active" style="display:inline-flex;align-items:center;cursor:default">'
                f'{name}{ren_btn}{del_btn}</span>'
            )
        else:
            tabs += f'<a href="/u/{uid}/p/{pname}?t={token}" class="tab">{name}</a>'
    tabs += (
        '<button onclick="openNewPortfolioModal()" title="새 포트폴리오" '
        'style="display:inline-flex;align-items:center;height:52px;padding:0 10px;'
        'background:none;border:none;cursor:pointer;font-size:1rem;color:#94a3b8;'
        'font-family:inherit;flex-shrink:0">＋</button>'
    )
    return tabs


def fmt_krw(v: float) -> str:
    if abs(v) >= 1e8:
        return f"₩{v/1e8:,.2f}억"
    if abs(v) >= 1e4:
        return f"₩{v/1e4:,.0f}만"
    return f"₩{v:,.0f}"


def build_user_html(
    df: pd.DataFrame,
    display_name: str = "",
    cashflows: list = None,
    pname: str = "",
    all_portfolios: dict = None,
    uid: int = 0,
    token: str = "",
    trades: list = None,
    hist: dict = None,
    realized_pnl: tuple = None,
) -> str:
    today_str  = datetime.now().strftime("%Y.%m.%d %H:%M")
    cashflows  = cashflows or []
    trades     = trades or []
    pname_js   = pname or ""
    net_investment = (
        sum(c["amount"] for c in cashflows if c["type"] == "in")
        - sum(c["amount"] for c in cashflows if c["type"] == "out")
    )
    portfolio_tabs = _build_portfolio_tabs(all_portfolios or {}, pname, uid=uid, token=token)

    # hist=None이면 storage에서 직접 로드 (하위호환 유지)
    if hist is None:
        hist = load_history(uid, pname) if pname else {}

    hist_dates  = sorted(hist.keys())
    hist_twr_vals = [hist[d].get("total_return") for d in hist_dates]
    hist_mwr_vals = [hist[d].get("mwr") for d in hist_dates]
    hist_nav_vals = [hist[d].get("nav_return") for d in hist_dates]
    hist_dates_js = json.dumps(hist_dates)
    hist_twr_js   = json.dumps([round(v, 4) if v is not None else None for v in hist_twr_vals])
    hist_mwr_js   = json.dumps([round(v, 4) if v is not None else None for v in hist_mwr_vals])
    hist_nav_js   = json.dumps([round(v, 4) if v is not None else None for v in hist_nav_vals])
    show_hist     = len(hist_dates) > 1

    def _period_ret(days):
        if not hist:
            return None
        sorted_dates = sorted(hist.keys())
        cur_nav = hist[sorted_dates[-1]].get("nav_return")
        if cur_nav is None:
            return None
        target = (date.today() - timedelta(days=days)).isoformat()
        past_dates = [d for d in sorted_dates if d <= target]
        if not past_dates:
            return None
        past_nav = hist[past_dates[-1]].get("nav_return")
        if past_nav is None:
            return None
        denom = 1 + past_nav / 100
        if denom == 0:
            return None
        return round((1 + cur_nav / 100) / denom * 100 - 100, 2)

    _period_labels = [("1개월", 30), ("3개월", 90), ("6개월", 180), ("1년", 365), ("전체", None)]
    def _period_ret_all():
        if not hist:
            return None
        sorted_dates = sorted(hist.keys())
        first_nav = None
        for d in sorted_dates:
            v = hist[d].get("nav_return")
            if v is not None:
                first_nav = v
                break
        cur_nav = hist[sorted_dates[-1]].get("nav_return")
        if cur_nav is None or first_nav is None:
            return None
        denom = 1 + first_nav / 100
        if denom == 0:
            return None
        return round((1 + cur_nav / 100) / denom * 100 - 100, 2)

    _period_vals = []
    for _lbl, _days in _period_labels:
        if _days is None:
            _v = _period_ret_all()
        else:
            _v = _period_ret(_days)
        _period_vals.append((_lbl, _v))

    def _pret_html(lbl, val):
        if val is None:
            return (
                f'<div style="text-align:center;padding:8px 0">'
                f'<div style="font-size:.75rem;color:#94a3b8;margin-bottom:4px">{lbl}</div>'
                f'<div style="font-size:1rem;font-weight:700;color:#94a3b8">-</div>'
                f'</div>'
            )
        color = "#10b981" if val >= 0 else "#ef4444"
        sign  = "+" if val >= 0 else ""
        return (
            f'<div style="text-align:center;padding:8px 0">'
            f'<div style="font-size:.75rem;color:#94a3b8;margin-bottom:4px">{lbl}</div>'
            f'<div style="font-size:1rem;font-weight:700;color:{color}">{sign}{val:.2f}%</div>'
            f'</div>'
        )

    _period_cells = "".join(_pret_html(lbl, val) for lbl, val in _period_vals)
    period_html = (
        '<div class="card" style="margin-bottom:16px">'
        '<div class="card-title">기간별 수익률'
        '<span style="font-size:.72rem;font-weight:400;color:#94a3b8;margin-left:6px">NAV 기준가 방식 · 복리 계산</span>'
        '</div>'
        f'<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:4px">'
        f'{_period_cells}'
        f'</div>'
        f'</div>'
    ) if hist else ""

    for col in ["수익률(%)", "등락률(%)", "현재가", "USD_KRW"]:
        if col not in df.columns:
            df = df.copy()
            df[col] = float("nan")

    usd_krw = float(df["USD_KRW"].iloc[0]) if "USD_KRW" in df.columns and len(df) > 0 else 1370.0

    stock_eval_krw = 0.0
    total_buy      = 0.0
    for _, _r in df.iterrows():
        _mult  = usd_krw if str(_r["통화"]).upper() == "USD" else 1.0
        _qty   = float(_r["수량"]) if "수량" in _r.index and pd.notna(_r.get("수량")) else 0.0
        _cur   = _r.get("현재가")
        _price = float(_cur) if pd.notna(_cur) else float(_r["평단가"])
        stock_eval_krw += _price * _qty * _mult
        total_buy      += float(_r["평단가"]) * _qty * _mult
    total_return = (stock_eval_krw - total_buy) / total_buy * 100 if total_buy > 0 else 0.0
    cash_krw    = max(0.0, net_investment - total_buy) if net_investment > 0 else 0.0
    total_ev    = stock_eval_krw + cash_krw
    show_cash   = net_investment > 0 and cash_krw > 0
    _w_scale    = stock_eval_krw / total_ev if total_ev > 0 else 1.0
    cash_wpct   = round(cash_krw / total_ev * 100, 2) if total_ev > 0 else 0.0

    _w_main = df[df["비중(%)"] >= 1.0]
    _w_small = df[df["비중(%)"] < 1.0]
    if not _w_small.empty:
        _other = pd.DataFrame([{"종목명": "기타", "비중(%)": _w_small["비중(%)"].sum()}])
        _w_chart = pd.concat([_w_main[["종목명", "비중(%)"]], _other], ignore_index=True)
    else:
        _w_chart = _w_main[["종목명", "비중(%)"]].copy()
    name_to_idx = {name: i for i, name in enumerate(df["종목명"].tolist())}
    _w_chart = _w_chart.copy()
    _w_chart["비중(%)"] = (_w_chart["비중(%)"] * _w_scale).round(2)
    if show_cash:
        _w_chart = pd.concat(
            [_w_chart, pd.DataFrame([{"종목명": "현금", "비중(%)": cash_wpct}])],
            ignore_index=True,
        )
    wl = json.dumps([escape(str(n)) for n in _w_chart["종목명"].tolist()], ensure_ascii=False)
    wd = json.dumps([round(v, 2) for v in _w_chart["비중(%)"].tolist()])
    wp = json.dumps([
        PALETTE[name_to_idx[n] % len(PALETTE)] if n in name_to_idx else "#94a3b8"
        for n in _w_chart["종목명"].tolist()
    ])

    cg = df.groupby("국가")["비중(%)"].sum().reset_index()
    _cg_total = cg["비중(%)"].sum()
    if _cg_total > 0:
        cg["비중(%)"] = (cg["비중(%)"] / _cg_total * 100 * _w_scale).round(2)
    _country_color_list = []
    for c in cg["국가"].tolist():
        first_stock = df[df["국가"] == c]["종목명"].iloc[0] if not df[df["국가"] == c].empty else None
        idx = name_to_idx.get(first_stock, len(_country_color_list)) if first_stock else len(_country_color_list)
        _country_color_list.append(PALETTE[idx % len(PALETTE)])
    if show_cash:
        cg = pd.concat(
            [cg, pd.DataFrame([{"국가": "현금", "비중(%)": cash_wpct}])],
            ignore_index=True,
        )
        _country_color_list.append("#94a3b8")
    cl = json.dumps(cg["국가"].tolist(), ensure_ascii=False)
    cd = json.dumps(cg["비중(%)"].tolist())
    country_colors = json.dumps(_country_color_list)

    ret_df = (
        df[df["수익률(%)"].notna() & (df["국가"] != "현금")]
        .sort_values("수익률(%)", ascending=True)
    )
    rl = json.dumps([escape(str(n)) for n in ret_df["종목명"].tolist()], ensure_ascii=False)
    rd = json.dumps(ret_df["수익률(%)"].tolist())
    rc = json.dumps([PALETTE[name_to_idx.get(n, 0) % len(PALETTE)] for n in ret_df["종목명"].tolist()])
    ret_count    = len(ret_df)
    ret_chart_h  = max(160, ret_count * 56)

    total_eval = 0.0
    name_to_color = {name: PALETTE[i % len(PALETTE)] for i, name in enumerate(df["종목명"].tolist())}
    table_rows = ""

    for _, r in df.iterrows():
        ret_val    = r["수익률(%)"]
        chg_val    = r["등락률(%)"]
        cur_price  = r.get("현재가")
        avg        = float(r["평단가"])
        weight     = float(r["비중(%)"])
        currency   = str(r["통화"]).upper()
        flag       = {"KR": "🇰🇷 한국", "US": "🇺🇸 미국", "현금": "💵 현금"}.get(r["국가"], f"🌐 {r['국가']}")
        color      = name_to_color.get(r["종목명"], "#64748b")
        name       = escape(r["종목명"])
        initial    = escape(str(r["종목명"])[0].upper())

        if pd.isna(ret_val):
            ret_str, ret_col = "—", "#94a3b8"
        elif ret_val > 0:
            ret_str, ret_col = f"+{ret_val:.2f}%", "#16a34a"
        elif ret_val < 0:
            ret_str, ret_col = f"{ret_val:.2f}%", "#dc2626"
        else:
            ret_str, ret_col = "0.00%", "#64748b"

        if pd.isna(chg_val):
            chg_str, chg_col = "—", "#94a3b8"
        elif chg_val > 0:
            chg_str, chg_col = f"+{chg_val:.2f}%", "#16a34a"
        elif chg_val < 0:
            chg_str, chg_col = f"{chg_val:.2f}%", "#dc2626"
        else:
            chg_str, chg_col = "0.00%", "#64748b"

        cur_str = (f"₩{cur_price:,.0f}" if currency == "KRW" else f"${cur_price:,.2f}") if pd.notna(cur_price) else "—"
        avg_str = f"₩{avg:,.0f}" if currency == "KRW" else f"${avg:,.2f}"

        multiplier = usd_krw if currency == "USD" else 1.0
        qty = float(r["수량"]) if "수량" in r.index and pd.notna(r["수량"]) else None

        if qty is not None:
            buy_krw  = avg * qty * multiplier
            buy_str  = f"₩{buy_krw:,.0f}" if currency == "KRW" else f"${avg*qty:,.2f}"
            if pd.notna(cur_price):
                eval_krw   = float(cur_price) * qty * multiplier
                total_eval += eval_krw
                eval_str   = f"₩{eval_krw:,.0f}" if currency == "KRW" else f"${float(cur_price)*qty:,.2f}"
            else:
                eval_str = "—"
        else:
            buy_str = eval_str = "—"

        _ed = json.dumps({"name": name, "country": r["국가"], "qty": qty or 0, "avg": avg, "weight": weight})
        _name_js = json.dumps(name, ensure_ascii=False).replace('"', '&quot;')
        edit_btns = (
            f'<td style="text-align:right;white-space:nowrap">'
            f'<button onclick=\'openEditModal({_ed})\' style="background:none;border:1px solid var(--border);'
            f'border-radius:6px;padding:4px 8px;cursor:pointer;font-size:.75rem;color:var(--secondary);margin-right:4px">✏️</button>'
            f'<button onclick="deleteStock({_name_js})" style="background:none;border:1px solid #fecaca;'
            f'border-radius:6px;padding:4px 8px;cursor:pointer;font-size:.75rem;color:#dc2626">🗑️</button>'
            f'</td>'
        )

        table_rows += f"""<tr>
          <td>
            <div style="display:flex;align-items:center;gap:10px">
              <div style="width:32px;height:32px;border-radius:50%;background:{color};
                display:flex;align-items:center;justify-content:center;
                font-weight:700;font-size:.8rem;color:#fff;flex-shrink:0">{initial}</div>
              <div>
                <div style="font-weight:600;color:#0f172a;font-size:.88rem">{name}</div>
                <div style="font-size:.72rem;color:#94a3b8">{flag}</div>
              </div>
            </div>
          </td>
          <td class="num">{avg_str}</td>
          <td class="num" style="color:#0f172a;font-weight:600">{cur_str}</td>
          <td class="num" style="color:{chg_col};font-weight:700">{chg_str}</td>
          <td class="num" style="color:{ret_col};font-weight:600">{ret_str}</td>
          <td class="num">{weight * _w_scale:.1f}%</td>
          <td class="num">{buy_str}</td>
          <td class="num">{eval_str}</td>
          {edit_btns}
        </tr>"""

    total_pnl     = stock_eval_krw - total_buy
    total_pnl_pct = (total_pnl / total_buy * 100) if total_buy > 0 else 0.0
    total_eval   += cash_krw
    cash_weight   = round(cash_krw / total_ev * 100, 1) if total_ev > 0 else 0.0
    stock_count   = len(df)

    daily_pnl = 0.0
    for _, r in df.iterrows():
        chg = r.get("등락률(%)")
        cp  = r.get("현재가")
        if pd.isna(chg) or chg is None or pd.isna(cp) or cp is None:
            continue
        currency = str(r["통화"]).upper()
        qty      = float(r["수량"]) if "수량" in r.index and pd.notna(r["수량"]) else 0.0
        mult     = usd_krw if currency == "USD" else 1.0
        prev_price   = float(cp) / (1 + float(chg) / 100)
        daily_pnl   += (float(cp) - prev_price) * qty * mult
    daily_pnl_pct = (daily_pnl / stock_eval_krw * 100) if stock_eval_krw > 0 else 0.0

    if show_cash:
        table_rows += (
            f'<tr>'
            f'<td><div style="font-weight:600;color:#0f172a;font-size:.88rem;padding:4px 0">💵 현금</div></td>'
            f'<td class="num">—</td>'
            f'<td class="num" style="color:#0f172a;font-weight:600">{fmt_krw(cash_krw)}</td>'
            f'<td class="num">—</td>'
            f'<td class="num">—</td>'
            f'<td class="num">{cash_weight:.1f}%</td>'
            f'<td class="num">—</td>'
            f'<td class="num">{fmt_krw(cash_krw)}</td>'
            f'<td></td>'
            f'</tr>'
        )

    net_inv_disp = fmt_krw(net_investment) if cashflows else "—"

    current_nav_return = None
    if hist:
        last_d = sorted(hist.keys())[-1]
        current_nav_return = hist[last_d].get("nav_return")
    if current_nav_return is not None:
        nav_sign  = "+" if current_nav_return >= 0 else ""
        nav_color = "#16a34a" if current_nav_return >= 0 else "#dc2626"
        nav_card  = (
            f'<div class="ov-metric">'
            f'<div class="m-label"><span class="help-wrap">계좌 수익률<span class="help-icon">?</span>'
            f'<span class="help-tip">입출금 타이밍을 제거한 순수 운용 성과(NAV 기준가 방식).<br>추가 입금이 많아도 수익률이 희석되지 않습니다.</span></span></div>'
            f'<div class="m-value" style="color:{nav_color}">{nav_sign}{current_nav_return:.2f}%</div>'
            f'<div class="m-sub">입출금 제거 기준</div>'
            f'</div>'
        )
    else:
        nav_card = ""

    if cashflows:
        cf_rows = ""
        for cf in reversed(cashflows):
            t_label = "🟢 입금" if cf["type"] == "in" else "🔴 출금"
            t_color = "#16a34a" if cf["type"] == "in" else "#dc2626"
            a_str   = fmt_krw(cf["amount"])
            memo    = cf.get("memo", "")
            cf_rows += (
                f'<tr>'
                f'<td style="padding:10px">{cf["date"]}</td>'
                f'<td style="padding:10px;color:{t_color};font-weight:600">{t_label}</td>'
                f'<td class="num" style="padding:10px">{a_str}</td>'
                f'<td style="padding:10px;color:#64748b">{memo}</td>'
                f'</tr>'
            )
    else:
        cf_rows = '<tr><td colspan="4" style="text-align:center;color:#94a3b8;padding:28px">자금 기록이 없습니다</td></tr>'

    if show_hist:
        hist_chart_html = (
            '<div class="card" style="margin-bottom:16px">'
            '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">'
            '<div class="card-title" style="margin-bottom:0">수익률 추이'
            '<span style="font-size:.72rem;font-weight:400;color:#94a3b8;margin-left:8px">'
            '종목 수익률 = 매수금 기준 &nbsp;·&nbsp; 단순 계좌 수익률 = 입출금 포함 &nbsp;·&nbsp; 계좌 수익률 = 입출금 제거(NAV)'
            '</span></div>'
            '<div style="display:flex;gap:6px;flex-wrap:wrap">'
            '<button id="idx-btn-KOSPI"  onclick="toggleIndex(\'KOSPI\')"  '
            'style="padding:3px 10px;border-radius:20px;border:1px solid #e2e8f0;'
            'background:#fff;font-size:.72rem;font-weight:600;cursor:pointer;color:#64748b;'
            'transition:all .15s">KOSPI</button>'
            '<button id="idx-btn-KOSDAQ" onclick="toggleIndex(\'KOSDAQ\')" '
            'style="padding:3px 10px;border-radius:20px;border:1px solid #e2e8f0;'
            'background:#fff;font-size:.72rem;font-weight:600;cursor:pointer;color:#64748b;'
            'transition:all .15s">KOSDAQ</button>'
            '<button id="idx-btn-NASDAQ" onclick="toggleIndex(\'NASDAQ\')" '
            'style="padding:3px 10px;border-radius:20px;border:1px solid #e2e8f0;'
            'background:#fff;font-size:.72rem;font-weight:600;cursor:pointer;color:#64748b;'
            'transition:all .15s">NASDAQ</button>'
            '<button id="idx-btn-SP500"  onclick="toggleIndex(\'S&P500\')" '
            'style="padding:3px 10px;border-radius:20px;border:1px solid #e2e8f0;'
            'background:#fff;font-size:.72rem;font-weight:600;cursor:pointer;color:#64748b;'
            'transition:all .15s">S&P500</button>'
            '</div></div>'
            '<div style="position:relative;height:220px">'
            '<canvas id="histChart"></canvas>'
            '</div></div>'
        )
        hist_chart_js = f"""
const _histStart  = {hist_dates_js}.length > 0 ? {hist_dates_js}[0] : null;
const _idxColors  = {{ "KOSPI": "#f59e0b", "KOSDAQ": "#10b981", "NASDAQ": "#ef4444", "S&P500": "#f97316" }};
const _idxVisible = {{ "KOSPI": false, "KOSDAQ": false, "NASDAQ": false, "S&P500": false }};
const _idxCache   = {{}};

const histChart = new Chart(document.getElementById("histChart"), {{
  type: "line",
  data: {{
    labels: {hist_dates_js},
    datasets: [
      {{
        label: "종목 수익률",
        data: {hist_twr_js},
        borderColor: "#0ea5e9",
        backgroundColor: "rgba(14,165,233,.08)",
        tension: 0.3, fill: true, pointRadius: 3, borderWidth: 2,
      }},
      {{
        label: "단순 계좌 수익률",
        data: {hist_mwr_js},
        borderColor: "#6366f1",
        backgroundColor: "rgba(99,102,241,.04)",
        tension: 0.3, fill: false, pointRadius: 3, borderWidth: 2, spanGaps: true,
      }},
      {{
        label: "계좌 수익률(NAV)",
        data: {hist_nav_js},
        borderColor: "#f59e0b",
        backgroundColor: "rgba(245,158,11,.04)",
        tension: 0.3, fill: false, pointRadius: 3, borderWidth: 2, spanGaps: true,
      }},
    ],
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ position: "top", labels: {{ boxWidth: 9, padding: 10, font: {{ size: 11 }} }} }},
      tooltip: {{
        mode: "index", intersect: false,
        callbacks: {{
          label: function(c) {{
            var v = c.parsed.y;
            return " " + c.dataset.label + ": " + (v == null ? "—" : (v >= 0 ? "+" : "") + v.toFixed(2) + "%");
          }},
        }},
      }},
    }},
    scales: {{
      x: {{ grid: {{ display: false }}, ticks: {{ color: "#94a3b8", font: {{ size: 10 }}, maxTicksLimit: 8 }} }},
      y: {{ grid: {{ color: "#f1f5f9" }}, ticks: {{ color: "#94a3b8", callback: function(v) {{ return (v >= 0 ? "+" : "") + v + "%"; }} }} }},
    }},
  }},
}});

function _alignToLabels(idxData, labels) {{
  const map = {{}};
  idxData.forEach(d => {{ map[d.date] = d.return; }});
  return labels.map(d => map[d] != null ? map[d] : null);
}}

window.toggleIndex = async function(name) {{
  const btn     = document.getElementById("idx-btn-" + name.replace("&", ""));
  const color   = _idxColors[name];
  const visible = _idxVisible[name];
  if (visible) {{
    _idxVisible[name] = false;
    btn.style.background = "#fff"; btn.style.color = "#64748b"; btn.style.borderColor = "#e2e8f0";
    const idx = histChart.data.datasets.findIndex(d => d.label === name);
    if (idx > 0) histChart.data.datasets.splice(idx, 1);
    histChart.update();
    return;
  }}
  _idxVisible[name] = true;
  btn.style.background = color; btn.style.color = "#fff"; btn.style.borderColor = color;
  if (!_idxCache[name] && _histStart) {{
    try {{
      const r = await fetch(`/u/${{UID}}/api/index_returns?start=${{_histStart}}&t=${{TOKEN}}`);
      const all = await r.json();
      Object.keys(all).forEach(k => {{ _idxCache[k] = all[k]; }});
    }} catch(e) {{
      console.error("지수 데이터 조회 실패", e);
      _idxVisible[name] = false;
      btn.style.background = "#fff"; btn.style.color = "#64748b";
      return;
    }}
  }}
  const aligned = _alignToLabels(_idxCache[name] || [], histChart.data.labels);
  histChart.data.datasets.push({{
    label: name, data: aligned, borderColor: color, backgroundColor: "transparent",
    tension: 0.3, fill: false, pointRadius: 0, pointHoverRadius: 5, borderWidth: 1.5, spanGaps: true,
  }});
  histChart.update();
}};"""
    else:
        hist_chart_html = ""
        hist_chart_js   = ""

    eval_disp      = fmt_krw(total_ev)
    pnl_disp       = fmt_krw(total_pnl)
    pnl_sign       = "+" if total_pnl >= 0 else ""
    pnl_color      = "#16a34a" if total_pnl >= 0 else "#dc2626"
    daily_disp     = fmt_krw(daily_pnl)
    daily_sign     = "+" if daily_pnl >= 0 else ""
    daily_color    = "#16a34a" if daily_pnl >= 0 else "#dc2626"
    ret_sign   = "+" if total_return >= 0 else ""
    ret_color  = "#16a34a" if total_return >= 0 else "#dc2626"
    title_name = escape(display_name or "포트폴리오")
    action_th  = "<th></th>"
    add_btn    = (
        '<div style="display:flex;gap:8px;align-items:center">'
        f'<span class="badge">{len(df)}개 종목</span>'
        '<button id="refresh-btn" onclick="refreshPrices()" style="background:#f1f5f9;border:1px solid var(--border);'
        'border-radius:8px;padding:5px 12px;cursor:pointer;font-size:.78rem;font-weight:600;color:var(--secondary)">🔄 가격 새로고침</button>'
        '<button onclick="openAddModal()" style="background:var(--accent);border:none;'
        'border-radius:8px;padding:5px 14px;cursor:pointer;font-size:.78rem;font-weight:700;color:#fff">+ 종목 추가</button>'
        '</div>'
    )

    # realized_pnl=None이면 storage에서 직접 로드 (하위호환 유지)
    if realized_pnl is None:
        realized_total, realized_per_stock = compute_realized_pnl(uid, pname)
    else:
        realized_total, realized_per_stock = realized_pnl

    r_sign  = "+" if realized_total >= 0 else ""
    r_color = "#16a34a" if realized_total >= 0 else "#dc2626"
    r_disp  = fmt_krw(realized_total)

    realized_card = f'''
<div class="ov-metric">
  <div class="m-label">
    <span class="help-wrap">실현 손익
      <span class="help-icon">?</span>
      <span class="help-tip">매도 거래 기준 실현 손익.<br>매도단가 입력 시에만 집계됩니다.</span>
    </span>
  </div>
  <div class="m-value" style="color:{r_color}">{r_sign}{r_disp}</div>
  <div class="m-sub">청산 종목 기준</div>
</div>'''

    trade_rows = ""
    total = len(trades)
    for i, t in enumerate(reversed(trades[-50:])):
        original_index = total - 1 - i
        _ttype = t.get("type", "")
        if _ttype == "신규매수":
            t_label, t_color, t_bg, t_border = "신규매수", "#0ea5e9", "#eff6ff", "#bfdbfe"
        elif _ttype == "추가매수" or _ttype == "buy":
            t_label, t_color, t_bg, t_border = "추가매수", "#16a34a", "#f0fdf4", "#bbf7d0"
        elif _ttype == "일부매도":
            t_label, t_color, t_bg, t_border = "일부매도", "#f97316", "#fff7ed", "#fed7aa"
        elif _ttype == "전량매도" or _ttype == "sell":
            t_label, t_color, t_bg, t_border = "전량매도", "#dc2626", "#fef2f2", "#fecaca"
        else:
            t_label, t_color, t_bg, t_border = _ttype, "#64748b", "#f8fafc", "#e2e8f0"
        avg_str  = fmt_krw(t.get("avg", 0))
        amt_str  = fmt_krw(t["amount"])
        qty_str  = (f'{t["qty"]:,.0f}주' if t["qty"] == int(t["qty"])
                    else f'{t["qty"]:,.4f}주')
        _rpnl = t.get("realized_pnl")
        _rpnl_html = ""
        if _rpnl is not None:
            _rc = "#16a34a" if _rpnl >= 0 else "#dc2626"
            _rs = "+" if _rpnl >= 0 else ""
            _rpnl_html = (
                f'<div style="font-size:.73rem;color:{_rc};font-weight:600;margin-top:2px">'
                f'실현손익 {_rs}{fmt_krw(_rpnl)}</div>'
            )
        elif t.get("type") in ("일부매도", "전량매도", "sell"):
            _rpnl_html = (
                '<div style="font-size:.73rem;color:var(--muted);margin-top:2px">'
                '실현손익 미집계 (매도단가 미입력)</div>'
            )
        trade_rows += f'''
    <div style="padding:10px 14px;border-bottom:1px solid var(--border-subtle);
                display:flex;align-items:flex-start;gap:8px">
      <div style="flex:1;min-width:0">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
          <span style="font-size:.78rem;font-weight:700;color:{t_color};
                background:{t_bg};border:1px solid {t_border};
                border-radius:4px;padding:1px 6px">{t_label}</span>
          <span style="font-size:.72rem;color:var(--muted)">{t["date"]} {t["time"]}</span>
        </div>
        <div style="font-size:.85rem;font-weight:700;color:var(--text)">{escape(t["name"])}</div>
        <div style="font-size:.75rem;color:var(--secondary);margin-top:2px">
          {qty_str} · {amt_str}
        </div>
        <div style="font-size:.73rem;color:var(--muted);margin-top:1px">
          평균단가 {avg_str}
        </div>
        {_rpnl_html}
      </div>
      <button
        onclick="deleteTrade({original_index})"
        title="삭제"
        style="flex-shrink:0;background:none;border:1px solid #fecaca;
               border-radius:5px;padding:3px 6px;cursor:pointer;
               font-size:.7rem;color:#dc2626;line-height:1;margin-top:2px">
        🗑️
      </button>
    </div>'''
    if not trade_rows:
        trade_rows = '<div style="text-align:center;padding:32px 0;color:var(--muted);font-size:.82rem">거래 기록이 없습니다</div>'
    trade_panel_html = f'''
<div class="card" style="padding:0;overflow:hidden">
  <div style="padding:14px 16px;border-bottom:1px solid var(--border);
       display:flex;align-items:center;justify-content:space-between">
    <div class="card-title" style="margin-bottom:0">거래 기록</div>
    <button onclick="clearTrades()" title="전체 삭제"
      style="background:none;border:1px solid var(--border);border-radius:6px;
             padding:3px 8px;cursor:pointer;font-size:.72rem;color:var(--muted)">초기화</button>
  </div>
  <div style="max-height:calc(100vh - 200px);overflow-y:auto" id="trade-list">
    {trade_rows}
  </div>
</div>'''

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title_name} · 포트폴리오</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root {{
  --bg:#f1f5f9; --surface:#fff;
  --border:#e2e8f0; --border-subtle:#f1f5f9;
  --text:#0f172a; --secondary:#64748b; --muted:#94a3b8;
  --pos:#16a34a; --neg:#dc2626; --accent:#0ea5e9;
  --shadow:0 1px 3px rgba(0,0,0,.07),0 1px 2px rgba(0,0,0,.04);
  --shadow-md:0 4px 8px rgba(0,0,0,.06),0 2px 4px rgba(0,0,0,.04);
}}
*,*::before,*::after {{ box-sizing:border-box; margin:0; padding:0; }}
body {{
  background:var(--bg);
  color:var(--text);
  font-family:'Noto Sans KR',sans-serif;
  min-height:100vh;
  font-size:14px;
  -webkit-font-smoothing:antialiased;
}}
.topnav {{
  background:var(--surface);
  border-bottom:1px solid var(--border);
  padding:0 28px;
  display:flex;
  align-items:center;
  height:52px;
  position:sticky;
  top:0;
  z-index:100;
  box-shadow:0 1px 0 var(--border);
}}
.brand {{
  font-weight:800;
  font-size:.95rem;
  color:var(--text);
  letter-spacing:-.01em;
  margin-right:24px;
  display:flex;
  align-items:center;
  gap:7px;
  flex-shrink:0;
}}
.brand-dot {{ width:7px; height:7px; border-radius:50%; background:var(--accent); }}
.tab {{
  display:inline-flex;
  align-items:center;
  height:52px;
  padding:0 14px;
  font-size:.85rem;
  font-weight:500;
  color:var(--secondary);
  text-decoration:none;
  border-bottom:2px solid transparent;
  transition:all .15s;
  white-space:nowrap;
}}
.tab:hover {{ color:var(--text); }}
.tab.active {{ color:var(--text); font-weight:700; border-bottom-color:var(--accent); }}
.nav-time {{ margin-left:auto; font-size:.72rem; color:var(--muted); flex-shrink:0; }}
.main {{ max-width:1480px; margin:0 auto; padding:28px 28px 48px; display:grid; grid-template-columns:1fr 300px; gap:20px; align-items:start; }}
@media (max-width:1024px) {{ .main {{ grid-template-columns:1fr 280px; }} }}
@media (max-width:768px)  {{ .main {{ grid-template-columns:1fr !important; }} }}
.overview {{
  background:var(--surface);
  border-radius:14px;
  box-shadow:var(--shadow-md);
  padding:26px 30px;
  margin-bottom:16px;
  display:flex;
  align-items:center;
  gap:0;
  flex-wrap:wrap;
  row-gap:16px;
}}
.ov-main {{ flex-shrink:0; padding-right:30px; border-right:1px solid var(--border); margin-right:30px; }}
.ov-main .ov-label {{ font-size:.68rem; color:var(--muted); text-transform:uppercase; letter-spacing:.1em; margin-bottom:6px; font-weight:600; }}
.ov-main .ov-value {{ font-size:2.1rem; font-weight:700; color:var(--text); letter-spacing:-.03em; line-height:1; }}
.ov-metrics {{ display:flex; gap:0; flex-wrap:wrap; }}
.ov-metric {{ padding:0 26px; border-right:1px solid var(--border); display:flex; flex-direction:column; gap:5px; }}
.ov-metric:last-child {{ border-right:none; }}
.m-label {{ font-size:.68rem; color:var(--muted); text-transform:uppercase; letter-spacing:.08em; font-weight:600; }}
.m-value {{ font-size:1.15rem; font-weight:700; line-height:1; }}
.m-sub {{ font-size:.72rem; color:var(--muted); }}
.charts-grid {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:14px; margin-bottom:16px; }}
@media(max-width:1000px) {{ .charts-grid {{ grid-template-columns:1fr 1fr; }} }}
@media(max-width:640px)  {{ .charts-grid {{ grid-template-columns:1fr; }} }}
.card {{ background:var(--surface); border-radius:14px; box-shadow:var(--shadow); padding:22px; }}
.card-title {{
  font-size:.7rem; font-weight:700; color:var(--secondary);
  text-transform:uppercase; letter-spacing:.12em; margin-bottom:16px;
  display:flex; align-items:center; gap:8px;
}}
.card-title::before {{
  content:""; display:inline-block; width:3px; height:11px;
  background:var(--accent); border-radius:2px; flex-shrink:0;
}}
.table-card {{ background:var(--surface); border-radius:14px; box-shadow:var(--shadow); padding:22px; margin-bottom:16px; overflow-x:auto; }}
.table-header {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:16px; }}
.badge {{ background:#f1f5f9; color:var(--secondary); font-size:.7rem; font-weight:700; padding:3px 10px; border-radius:99px; }}
table {{ width:100%; border-collapse:collapse; min-width:620px; }}
thead th {{ font-size:.7rem; text-transform:uppercase; letter-spacing:.07em; color:var(--muted); font-weight:700; padding:8px 10px; border-bottom:1px solid var(--border); text-align:left; }}
tbody tr {{ border-bottom:1px solid var(--border-subtle); transition:background .1s; }}
tbody tr:last-child {{ border-bottom:none; }}
tbody tr:hover {{ background:#f8fafc; }}
tbody td {{ padding:12px 10px; }}
tbody td:first-child {{ white-space:nowrap; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.footer {{ text-align:center; padding:28px 0 4px; font-size:.65rem; color:#cbd5e1; letter-spacing:.1em; text-transform:uppercase; }}
@keyframes fadeIn {{ from {{ opacity:0; transform:translateY(10px); }} to {{ opacity:1; transform:translateY(0); }} }}
.overview {{ animation:fadeIn .3s ease both; }}
.charts-grid .card:nth-child(1) {{ animation:fadeIn .3s .04s ease both; }}
.charts-grid .card:nth-child(2) {{ animation:fadeIn .3s .08s ease both; }}
.charts-grid .card:nth-child(3) {{ animation:fadeIn .3s .12s ease both; }}
.table-card {{ animation:fadeIn .3s .16s ease both; }}
.modal-overlay {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.35); z-index:300; align-items:center; justify-content:center; }}
.modal-overlay.open {{ display:flex; }}
.modal-box {{ background:#fff; border-radius:16px; padding:28px; width:400px; max-width:92vw; box-shadow:0 20px 60px rgba(0,0,0,.15); }}
.modal-title {{ font-size:1rem; font-weight:700; color:var(--text); margin-bottom:20px; }}
.form-group {{ display:flex; flex-direction:column; gap:5px; margin-bottom:14px; }}
.form-label {{ font-size:.68rem; font-weight:700; color:var(--secondary); text-transform:uppercase; letter-spacing:.08em; }}
.form-input, .form-select {{ border:1px solid var(--border); border-radius:8px; padding:9px 12px; font-size:.88rem; color:var(--text); font-family:inherit; outline:none; width:100%; transition:border-color .15s; }}
.form-input:focus, .form-select:focus {{ border-color:var(--accent); }}
.form-row {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
.modal-actions {{ display:flex; gap:10px; justify-content:flex-end; margin-top:22px; }}
.btn-cancel {{ background:#f1f5f9; border:none; border-radius:8px; padding:8px 18px; cursor:pointer; font-size:.85rem; font-weight:600; color:var(--secondary); }}
.btn-save {{ background:var(--accent); border:none; border-radius:8px; padding:8px 20px; cursor:pointer; font-size:.85rem; font-weight:700; color:#fff; }}
.btn-save:disabled {{ opacity:.6; cursor:not-allowed; }}
.help-wrap {{ position:relative; display:inline-flex; align-items:center; gap:3px; }}
.help-icon {{
  display:inline-flex; align-items:center; justify-content:center;
  width:13px; height:13px; border-radius:50%;
  background:#cbd5e1; color:#fff; font-size:9px; font-weight:700;
  cursor:default; line-height:1; flex-shrink:0;
}}
.help-tip {{
  display:none; position:absolute; bottom:calc(100% + 6px); left:50%;
  transform:translateX(-50%); background:#1e293b; color:#f8fafc;
  font-size:.72rem; line-height:1.5; padding:7px 10px; border-radius:8px;
  white-space:nowrap; z-index:200; pointer-events:none;
  box-shadow:0 4px 12px rgba(0,0,0,.2);
}}
.help-tip::after {{
  content:""; position:absolute; top:100%; left:50%; transform:translateX(-50%);
  border:5px solid transparent; border-top-color:#1e293b;
}}
.help-wrap:hover .help-tip {{ display:block; }}
</style>
</head>
<body>

<nav class="topnav">
  <div class="brand"><div class="brand-dot"></div>PORTFOLIO</div>
  {portfolio_tabs}
  <button id="refreshBtn"
  onclick="(function(){{
    var btn=document.getElementById('refreshBtn');
    btn.disabled=true; btn.textContent='새로고침 중...';
    fetch('/u/{uid}/api/p/{pname_js}/refresh?t={token}', {{method:'POST'}})
      .finally(function(){{ setTimeout(function(){{ location.reload(); }}, 2000); }});
  }})()"
  style="margin-left:auto;padding:0 12px;height:32px;background:#0ea5e9;color:#fff;
         border:none;border-radius:6px;font-size:.8rem;cursor:pointer;flex-shrink:0">
  🔄
</button>
  <div class="nav-time">기준: {today_str}</div>
</nav>

<div class="main">
<div>
  <div class="overview">
    <div class="ov-main">
      <div class="ov-label">총 평가금액</div>
      <div class="ov-value">{eval_disp}</div>
    </div>
    <div class="ov-metrics">
      <div class="ov-metric">
        <div class="m-label"><span class="help-wrap">총 손익<span class="help-icon">?</span><span class="help-tip">현재 주식 평가금액 - 총 매수금액.<br>현금 잔액은 포함되지 않습니다.</span></span></div>
        <div class="m-value" style="color:{pnl_color}">{pnl_sign}{pnl_disp}</div>
        <div class="m-sub" style="color:{pnl_color}">{pnl_sign}{total_pnl_pct:.2f}%</div>
      </div>
      {nav_card}
      <div class="ov-metric">
        <div class="m-label">일일 손익</div>
        <div class="m-value" style="color:{daily_color}">{daily_sign}{daily_disp}</div>
        <div class="m-sub" style="color:{daily_color}">{daily_sign}{daily_pnl_pct:.2f}%</div>
      </div>
      <div class="ov-metric">
        <div class="m-label"><span class="help-wrap">종목 수익률<span class="help-icon">?</span><span class="help-tip">보유 종목의 매수금액 대비 평가금액 상승률.<br>현금·입출금 타이밍은 제외됩니다.</span></span></div>
        <div class="m-value" style="color:{ret_color}">{ret_sign}{total_return:.2f}%</div>
        <div class="m-sub">주식 종목 기준</div>
      </div>
      <div class="ov-metric">
        <div class="m-label">투자 종목</div>
        <div class="m-value" style="color:var(--text)">{stock_count}개</div>
        <div class="m-sub">현금 제외</div>
      </div>
      <div class="ov-metric">
        <div class="m-label">현금 비중</div>
        <div class="m-value" style="color:var(--accent)">{cash_weight:.1f}%</div>
        <div class="m-sub">전체 포트폴리오</div>
      </div>
      <div class="ov-metric">
        <div class="m-label">순 투자원금</div>
        <div class="m-value" style="color:var(--text)">{net_inv_disp}</div>
        <div class="m-sub">총입금 - 총출금</div>
      </div>
      {realized_card}
    </div>
  </div>

  <div class="charts-grid" style="grid-template-columns:1fr 1fr">
    <div class="card">
      <div class="card-title">종목별 비중</div>
      <div style="position:relative;height:220px"><canvas id="weightChart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">국가별 비중</div>
      <div style="position:relative;height:220px"><canvas id="countryChart"></canvas></div>
    </div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div class="card-title">종목별 수익률</div>
    <div style="position:relative;height:{ret_chart_h}px"><canvas id="returnChart"></canvas></div>
  </div>

  {period_html}
  {hist_chart_html}

  <div class="table-card">
    <div class="table-header">
      <div class="card-title" style="margin-bottom:0">전체 포지션</div>
      {add_btn}
    </div>
    <table>
      <thead>
        <tr>
          <th>종목명</th><th class="num">평균단가</th><th class="num">현재가</th>
          <th class="num">일등락</th><th class="num">수익률</th><th class="num">비중</th>
          <th class="num">매수금액</th><th class="num">평가금액</th>{action_th}
        </tr>
      </thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>

  <div class="table-card" style="margin-top:16px">
    <div class="table-header">
      <div class="card-title" style="margin-bottom:0">자금 기록</div>
      <button onclick="openCashflowModal()" style="background:var(--accent);border:none;
        border-radius:8px;padding:5px 14px;cursor:pointer;font-size:.78rem;font-weight:700;color:#fff">
        ＋ 자금 기록
      </button>
    </div>
    <table>
      <thead>
        <tr><th>날짜</th><th>구분</th><th class="num">금액</th><th>메모</th></tr>
      </thead>
      <tbody>{cf_rows}</tbody>
    </table>
  </div>

  <div class="footer">Portfolio Dashboard &middot; {today_str} &middot; 투자 참고용</div>
</div>
<div style="position:sticky;top:68px">
  {trade_panel_html}
</div>
</div>

<!-- 종목 추가/수정 모달 -->
<div class="modal-overlay" id="modal">
  <div class="modal-box">
    <div class="modal-title" id="modal-title">종목 추가</div>
    <div class="form-group" id="row-name">
      <label class="form-label">종목명</label>
      <input id="f-name" class="form-input" type="text" placeholder="예: 삼성전자, AAPL">
    </div>
    <div class="form-group">
      <label class="form-label">국가</label>
      <select id="f-country" class="form-select" onchange="onCountryChange()">
        <option value="KR">🇰🇷 한국</option>
        <option value="US">🇺🇸 미국</option>
      </select>
    </div>
    <div class="form-row" id="row-qty-avg">
      <div class="form-group" style="margin-bottom:0" id="row-qty">
        <label class="form-label">수량</label>
        <input id="f-qty" class="form-input" type="text" inputmode="numeric" placeholder="0"
               oninput="_fmtInput(this,'int'); _onQtyChange();">
      </div>
      <div class="form-group" style="margin-bottom:0">
        <label class="form-label" id="label-avg">평균단가</label>
        <input id="f-avg" class="form-input" type="text" inputmode="decimal" placeholder="0"
               oninput="_fmtInput(this,'dec')">
      </div>
    </div>
    <div class="form-group" id="row-cash" style="display:none">
      <label class="form-label">금액</label>
      <input id="f-cash" class="form-input" type="text" inputmode="decimal" placeholder="0"
             oninput="_fmtInput(this,'dec')">
    </div>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="closeModal()">취소</button>
      <button class="btn-save" id="btn-save" onclick="saveStock()">저장</button>
    </div>
  </div>
</div>

<!-- 새 포트폴리오 모달 -->
<div class="modal-overlay" id="new-ptab-modal">
  <div class="modal-box">
    <div class="modal-title">새 포트폴리오</div>
    <div class="form-group">
      <label class="form-label">이름</label>
      <input id="new-ptab-name" class="form-input" type="text"
        placeholder="예: 성장주, 배당주, 해외주식"
        onkeydown="if(event.key==='Enter') createPortfolio()">
    </div>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="closeNewPortfolioModal()">취소</button>
      <button class="btn-save" onclick="createPortfolio()">만들기</button>
    </div>
  </div>
</div>

<!-- 포트폴리오 이름 변경 모달 -->
<div class="modal-overlay" id="rename-ptab-modal">
  <div class="modal-box">
    <div class="modal-title">이름 변경</div>
    <div class="form-group">
      <label class="form-label">새 이름</label>
      <input id="rename-ptab-name" class="form-input" type="text"
        onkeydown="if(event.key==='Enter') saveRename()">
    </div>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="closeRenameModal()">취소</button>
      <button class="btn-save" onclick="saveRename()">저장</button>
    </div>
  </div>
</div>

<!-- 자금 기록 모달 -->
<div class="modal-overlay" id="cf-modal">
  <div class="modal-box">
    <div class="modal-title">자금 기록 추가</div>
    <div class="form-group">
      <label class="form-label">구분</label>
      <select id="cf-type" class="form-select">
        <option value="in">🟢 입금</option>
        <option value="out">🔴 출금</option>
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">금액 (원)</label>
      <input id="cf-amount" class="form-input" type="number" placeholder="0" min="1" step="any">
    </div>
    <div class="form-group">
      <label class="form-label">메모 (선택)</label>
      <input id="cf-memo" class="form-input" type="text" placeholder="예: 초기 투자, 추가 매수">
    </div>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="closeCashflowModal()">취소</button>
      <button class="btn-save" id="cf-btn-save" onclick="saveCashflow()">저장</button>
    </div>
  </div>
</div>

<script>
const PNAME = "{pname_js}";
const UID   = {uid};
const TOKEN = "{token}";
let _editMode = false, _editName = '';
let _editOrigQty = 0;
let _editOrigAvg = 0;
let _wasSell = false;
let _renamePname = '';

function onCountryChange() {{
  const isCash = document.getElementById('f-country').value === '현금';
  document.getElementById('row-name').style.display    = isCash ? 'none' : '';
  document.getElementById('row-qty-avg').style.display = isCash ? 'none' : '';
  document.getElementById('row-cash').style.display    = isCash ? '' : 'none';
}}

function _fmtInput(el, mode) {{
  const sel = el.selectionStart;
  const before = el.value;
  let raw = before.replace(/[^0-9.]/g, '');
  if (mode === 'int') raw = raw.replace(/\\./g, '');
  const parts = raw.split('.');
  let intPart = parts[0] || '';
  const decPart = parts.length > 1 ? '.' + parts.slice(1).join('') : '';
  intPart = intPart.replace(/\\B(?=(\\d{{3}})+(?!\\d))/g, ',');
  const formatted = intPart + decPart;
  el.value = formatted;
  const diff = formatted.length - before.length;
  el.setSelectionRange(sel + diff, sel + diff);
}}

function _parseNum(id) {{
  return parseFloat(document.getElementById(id).value.replace(/,/g, '')) || 0;
}}

function _onQtyChange() {{
  if (!_editMode) return;
  const newQty  = _parseNum('f-qty');
  const isSell  = newQty < _editOrigQty;
  const label   = document.getElementById('label-avg');
  const avgEl   = document.getElementById('f-avg');
  if (isSell) {{
    label.textContent = '매도 단가';
    avgEl.placeholder = '매도 단가 입력';
    if (_parseNum('f-avg') === _editOrigAvg) {{
      avgEl.value = '';
    }}
  }} else {{
    label.textContent = '평균단가';
    avgEl.placeholder = '0';
    if (!avgEl.value) {{
      avgEl.value = Number(_editOrigAvg).toLocaleString('ko-KR');
    }}
  }}
}}

function openAddModal() {{
  _editMode = false; _editName = '';
  document.getElementById('modal-title').textContent = '종목 추가';
  document.getElementById('f-name').value = '';
  document.getElementById('f-name').disabled = false;
  document.getElementById('f-country').value = 'KR';
  document.getElementById('f-qty').value = '';
  document.getElementById('f-avg').value = '';
  document.getElementById('f-cash').value = '';
  document.getElementById('label-avg').textContent = '평균단가';
  document.getElementById('f-avg').placeholder = '0';
  _editOrigQty = 0;
  _editOrigAvg = 0;
  _wasSell = false;
  onCountryChange();
  document.getElementById('modal').classList.add('open');
}}

function openEditModal(d) {{
  _editMode = true; _editName = d.name;
  _editOrigQty = d.qty;
  _editOrigAvg = d.avg;
  _wasSell = false;
  document.getElementById('modal-title').textContent = '종목 수정';
  document.getElementById('f-name').value = d.name;
  document.getElementById('f-name').disabled = true;
  document.getElementById('f-country').value = d.country;
  document.getElementById('f-qty').value  = Number(d.qty).toLocaleString('ko-KR');
  document.getElementById('f-avg').value  = Number(d.avg).toLocaleString('ko-KR');
  document.getElementById('f-cash').value = d.country === '현금'
    ? Number(d.avg).toLocaleString('ko-KR') : '';
  onCountryChange();
  document.getElementById('modal').classList.add('open');
}}

function closeModal() {{ document.getElementById('modal').classList.remove('open'); }}

async function saveStock() {{
  const btn = document.getElementById('btn-save');
  btn.disabled = true; btn.textContent = '저장 중...';
  const isCash = document.getElementById('f-country').value === '현금';
  const payload = isCash ? {{
    종목명: '현금', 국가: '현금', 수량: 1,
    평단가: _parseNum('f-cash'),
  }} : {{
    종목명: document.getElementById('f-name').value.trim(),
    국가:   document.getElementById('f-country').value,
    수량:   _parseNum('f-qty'),
    평단가: _parseNum('f-avg'),
  }};
  if (!isCash && !payload.종목명) {{ alert('종목명을 입력하세요'); btn.disabled=false; btn.textContent='저장'; return; }}
  try {{
    const res = await fetch(`/u/${{UID}}/api/p/${{PNAME}}/stock?t=${{TOKEN}}`, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(payload),
    }});
    if (res.ok) {{ location.reload(); }}
    else {{ const e = await res.json(); alert('오류: ' + e.error); btn.disabled=false; btn.textContent='저장'; }}
  }} catch(e) {{ alert('네트워크 오류'); btn.disabled=false; btn.textContent='저장'; }}
}}

async function deleteStock(name) {{
  if (!confirm(`"${{name}}" 종목을 삭제할까요?`)) return;
  const res = await fetch(`/u/${{UID}}/api/p/${{PNAME}}/stock/${{encodeURIComponent(name)}}?t=${{TOKEN}}`, {{method:'DELETE'}});
  if (res.ok) {{ location.reload(); }}
  else {{ const e = await res.json(); alert('오류: ' + e.error); }}
}}

async function refreshPrices() {{
  const btn    = document.getElementById('refresh-btn');
  const navBtn = document.getElementById('topnav-refresh-btn');
  if (!btn && !navBtn) return;
  if (btn)    {{ btn.textContent = '조회 중...';      btn.disabled = true; }}
  if (navBtn) {{ navBtn.textContent = '새로고침 중...'; navBtn.disabled = true; }}
  try {{
    const ctrl = new AbortController();
    const tid  = setTimeout(() => ctrl.abort(), 120000);
    const res  = await fetch(`/u/${{UID}}/api/p/${{PNAME}}/refresh?t=${{TOKEN}}`, {{method:'POST', signal: ctrl.signal}});
    clearTimeout(tid);
    if (res.ok) {{ location.reload(); }}
    else {{ let msg = `HTTP ${{res.status}}`; try {{ const e = await res.json(); msg = e.error || msg; }} catch(_) {{}} alert('가격 조회 오류: ' + msg); }}
  }} catch(e) {{
    alert('가격 조회 오류: ' + (e.name === 'AbortError' ? '시간 초과 (120초)' : e.message));
  }} finally {{
    if (btn)    {{ btn.textContent = '🔄 가격 새로고침'; btn.disabled = false; }}
    if (navBtn) {{ navBtn.textContent = '🔄';            navBtn.disabled = false; }}
  }}
}}

function openNewPortfolioModal() {{
  document.getElementById('new-ptab-name').value = '';
  document.getElementById('new-ptab-modal').classList.add('open');
  setTimeout(() => document.getElementById('new-ptab-name').focus(), 50);
}}
function closeNewPortfolioModal() {{
  document.getElementById('new-ptab-modal').classList.remove('open');
}}
async function createPortfolio() {{
  const name = document.getElementById('new-ptab-name').value.trim();
  if (!name) {{ alert('이름을 입력하세요'); return; }}
  const res = await fetch(`/u/${{UID}}/api/portfolios?t=${{TOKEN}}`, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ name }}),
  }});
  if (res.ok) {{
    const d = await res.json();
    location.href = `/u/${{UID}}/p/${{d.pname}}?t=${{TOKEN}}`;
  }} else {{
    const e = await res.json(); alert('오류: ' + e.error);
  }}
}}

function openRenameModal(pname, currentName) {{
  _renamePname = pname;
  document.getElementById('rename-ptab-name').value = currentName;
  document.getElementById('rename-ptab-modal').classList.add('open');
  setTimeout(() => document.getElementById('rename-ptab-name').focus(), 50);
}}
function closeRenameModal() {{
  document.getElementById('rename-ptab-modal').classList.remove('open');
}}
async function saveRename() {{
  const name = document.getElementById('rename-ptab-name').value.trim();
  if (!name) {{ alert('이름을 입력하세요'); return; }}
  const res = await fetch(`/u/${{UID}}/api/portfolios/${{_renamePname}}?t=${{TOKEN}}`, {{
    method: 'PATCH',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ name }}),
  }});
  if (res.ok) {{ location.reload(); }}
  else {{ const e = await res.json(); alert('오류: ' + e.error); }}
}}

async function deletePortfolio(pname) {{
  if (!confirm('이 포트폴리오를 삭제할까요?\\n모든 데이터(종목, 자금기록, 히스토리)가 삭제됩니다.')) return;
  const res = await fetch(`/u/${{UID}}/api/portfolios/${{pname}}?t=${{TOKEN}}`, {{ method: 'DELETE' }});
  if (res.ok) {{
    const d = await res.json();
    location.href = d.redirect;
  }} else {{
    const e = await res.json(); alert('오류: ' + e.error);
  }}
}}

document.getElementById('new-ptab-modal').addEventListener('click', function(e) {{
  if (e.target === this) closeNewPortfolioModal();
}});
document.getElementById('rename-ptab-modal').addEventListener('click', function(e) {{
  if (e.target === this) closeRenameModal();
}});

function openCashflowModal() {{
  document.getElementById('cf-amount').value = '';
  document.getElementById('cf-memo').value   = '';
  document.getElementById('cf-type').value   = 'in';
  document.getElementById('cf-modal').classList.add('open');
}}
function closeCashflowModal() {{
  document.getElementById('cf-modal').classList.remove('open');
}}
async function saveCashflow() {{
  const btn    = document.getElementById('cf-btn-save');
  btn.disabled = true; btn.textContent = '저장 중...';
  const type   = document.getElementById('cf-type').value;
  const amount = parseFloat(document.getElementById('cf-amount').value);
  const memo   = document.getElementById('cf-memo').value.trim();
  if (!amount || amount <= 0) {{
    alert('금액을 입력하세요');
    btn.disabled = false; btn.textContent = '저장';
    return;
  }}
  try {{
    const res = await fetch(`/u/${{UID}}/api/cashflow/${{PNAME}}?t=${{TOKEN}}`, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ type, amount, memo }}),
    }});
    if (res.ok) {{ location.reload(); }}
    else {{
      const e = await res.json();
      alert('오류: ' + e.error);
      btn.disabled = false; btn.textContent = '저장';
    }}
  }} catch(e) {{
    alert('네트워크 오류');
    btn.disabled = false; btn.textContent = '저장';
  }}
}}
async function clearTrades() {{
  if (!confirm("거래 기록을 전체 삭제할까요?")) return;
  const res = await fetch(`/u/${{UID}}/api/trades/${{PNAME}}?t=${{TOKEN}}`, {{method:'DELETE'}});
  if (res.ok) {{ location.reload(); }}
  else {{ alert('오류가 발생했습니다'); }}
}}

async function deleteTrade(index) {{
  if (!confirm("이 거래 기록을 삭제할까요?")) return;
  const res = await fetch(
    `/u/${{UID}}/api/trades/${{PNAME}}/${{index}}?t=${{TOKEN}}`,
    {{method: 'DELETE'}}
  );
  if (res.ok) {{ location.reload(); }}
  else {{ alert('삭제 중 오류가 발생했습니다'); }}
}}

document.getElementById('cf-modal').addEventListener('click', function(e) {{
  if (e.target === this) closeCashflowModal();
}});

try {{
  Chart.defaults.font.family = "'Noto Sans KR',sans-serif";
  Chart.defaults.color = "#94a3b8";
  Chart.defaults.font.size = 11;

  const P = {wp};

  const donutCfg = (labels, data, colors) => ({{
    type: "doughnut",
    data: {{
      labels,
      datasets: [{{ data, backgroundColor: colors, borderWidth: 3, borderColor: "#fff", hoverOffset: 6 }}],
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      cutout: "65%",
      plugins: {{
        legend: {{ position: "bottom", labels: {{ boxWidth: 9, padding: 12, font: {{ size: 11 }}, color: "#64748b" }} }},
        tooltip: {{ callbacks: {{ label: c => ` ${{c.label}}: ${{c.parsed}}%` }} }},
      }},
    }},
  }});

  new Chart(document.getElementById("weightChart"),  donutCfg({wl}, {wd}, P));
  new Chart(document.getElementById("countryChart"), donutCfg({cl}, {cd}, {country_colors}));

  new Chart(document.getElementById("returnChart"), {{
    type: "bar",
    data: {{
      labels: {rl},
      datasets: [{{ label: "수익률(%)", data: {rd}, backgroundColor: {rc}, borderRadius: 4, borderSkipped: false }}],
    }},
    options: {{
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ callbacks: {{ label: c => ` ${{c.parsed.x >= 0 ? "+" : ""}}${{c.parsed.x.toFixed(2)}}%` }} }},
      }},
      scales: {{
        x: {{ grid: {{ color: "#f1f5f9" }}, ticks: {{ color: "#94a3b8", callback: v => (v >= 0 ? "+" : "") + v + "%" }} }},
        y: {{ grid: {{ display: false }}, ticks: {{ color: "#64748b", font: {{ size: 11 }} }} }},
      }},
    }},
  }});

}} catch(e) {{
  console.error("Chart 초기화 오류:", e);
}}
try {{
  {hist_chart_js}
}} catch(e) {{
  console.error("histChart 초기화 오류:", e);
}}
</script>
</body>
</html>"""


def build_combined_html(
    uid: int,
    token: str,
    all_portfolios: dict,
    combined_data: dict = None,
) -> str:
    """
    combined_data=None이면 내부에서 storage 함수를 직접 호출 (하위호환 유지).
    combined_data가 제공되면 {pname: {"cashflows": list, "history": dict}} 형태로 사용.
    """
    today_str = datetime.now().strftime("%Y.%m.%d %H:%M")
    pnames    = list(all_portfolios.keys())

    # ── 포트폴리오별 집계 ──
    combined_stock_eval = 0.0
    combined_total_buy  = 0.0
    combined_net_inv    = 0.0
    portfolio_stats     = []

    for pname, p in all_portfolios.items():
        # combined_data가 제공되면 그걸 사용, 없으면 storage 직접 호출
        if combined_data is not None and pname in combined_data:
            cashflows = combined_data[pname].get("cashflows", [])
        else:
            cashflows = load_cashflow(uid, pname)
        net_inv   = (sum(c["amount"] for c in cashflows if c["type"] == "in")
                   - sum(c["amount"] for c in cashflows if c["type"] == "out"))
        combined_net_inv += net_inv

        df = p.get("df")
        if df is None or len(df) == 0:
            if net_inv > 0:
                portfolio_stats.append({
                    "pname":    pname,
                    "name":     p.get("name", pname),
                    "total_ev": net_inv,
                    "pnl_pct":  0.0,
                    "nav_ret":  None,
                    "ts":       "—",
                    "count":    0,
                })
            continue

        usd_krw_p = 1370.0
        if "USD_KRW" in df.columns and len(df) > 0:
            usd_krw_p = float(df["USD_KRW"].iloc[0])

        s_eval = 0.0
        t_buy  = 0.0
        for _, r in df.iterrows():
            mult  = usd_krw_p if str(r.get("통화", "KRW")).upper() == "USD" else 1.0
            qty   = float(r["수량"]) if pd.notna(r.get("수량")) else 0.0
            avg   = float(r["평단가"])
            cur   = float(r["현재가"]) if pd.notna(r.get("현재가")) else avg
            s_eval += cur * qty * mult
            t_buy  += avg * qty * mult

        cash_p     = max(0.0, net_inv - t_buy) if net_inv > 0 else 0.0
        total_ev_p = s_eval + cash_p
        pnl_pct_p  = (s_eval - t_buy) / t_buy * 100 if t_buy > 0 else 0.0

        if combined_data is not None and pname in combined_data:
            hist_p = combined_data[pname].get("history", {})
        else:
            hist_p = load_history(uid, pname)
        nav_ret_p = None
        if hist_p:
            last_d    = sorted(hist_p.keys())[-1]
            nav_ret_p = hist_p[last_d].get("nav_return")

        combined_stock_eval += s_eval
        combined_total_buy  += t_buy
        portfolio_stats.append({
            "pname":    pname,
            "name":     p.get("name", pname),
            "total_ev": total_ev_p,
            "pnl_pct":  pnl_pct_p,
            "nav_ret":  nav_ret_p,
            "ts":       p["last_update"].strftime("%m/%d %H:%M") if p.get("last_update") else "—",
            "count":    len(df),
        })

    # ── 통합 수치 ──
    combined_cash    = max(0.0, combined_net_inv - combined_total_buy) if combined_net_inv > 0 else 0.0
    combined_total   = combined_stock_eval + combined_cash
    combined_pnl     = combined_stock_eval - combined_total_buy
    combined_pnl_pct = combined_pnl / combined_total_buy * 100 if combined_total_buy > 0 else 0.0
    combined_nav, _  = compute_combined_nav(uid, pnames, combined_total)
    combined_nav_ret = (combined_nav / 1000.0 - 1) * 100

    pnl_sign  = "+" if combined_pnl >= 0 else ""
    pnl_color = "#16a34a" if combined_pnl >= 0 else "#dc2626"
    nav_sign  = "+" if combined_nav_ret >= 0 else ""
    nav_color = "#16a34a" if combined_nav_ret >= 0 else "#dc2626"
    inv_disp  = fmt_krw(combined_net_inv) if combined_net_inv > 0 else "—"

    # ── 탭 / 파이차트 데이터 ──
    portfolio_tabs = _build_portfolio_tabs(all_portfolios, "all", uid=uid, token=token)
    pie_labels = json.dumps([escape(ps["name"]) for ps in portfolio_stats], ensure_ascii=False)
    pie_data   = json.dumps([
        round(ps["total_ev"] / combined_total * 100, 2) if combined_total > 0 else 0
        for ps in portfolio_stats
    ])
    pie_colors = json.dumps([PALETTE[i % len(PALETTE)] for i in range(len(portfolio_stats))])

    # ── 히스토리 차트 데이터 ──
    if combined_data is not None:
        all_dates = sorted(set(
            d for pn in pnames
            for d in combined_data.get(pn, {}).get("history", {}).keys()
        ))
    else:
        all_dates = sorted(set(
            d for pn in pnames for d in load_history(uid, pn).keys()
        ))
    show_hist = len(all_dates) > 1
    hist_dates_js = json.dumps(all_dates)
    if show_hist:
        hist_datasets = []
        for i, pn in enumerate(pnames):
            if combined_data is not None and pn in combined_data:
                hist_p = combined_data[pn].get("history", {})
            else:
                hist_p = load_history(uid, pn)
            nav_series = [hist_p.get(d, {}).get("nav_return") for d in all_dates]
            hist_datasets.append({
                "label":           escape(all_portfolios[pn].get("name", pn)),
                "data":            nav_series,
                "borderColor":     PALETTE[i % len(PALETTE)],
                "backgroundColor": "transparent",
                "tension":         0.3,
                "fill":            False,
                "pointRadius":     3,
                "borderWidth":     2,
                "spanGaps":        True,
            })
        chart_datasets_json = json.dumps(hist_datasets, ensure_ascii=False)
    else:
        chart_datasets_json = "[]"

    # ── 포트폴리오 요약 rows (비중 차트 우측 패널) ──
    stat_rows = ""
    for i, ps in enumerate(portfolio_stats):
        color  = PALETTE[i % len(PALETTE)]
        pnl_c  = "#16a34a" if ps["pnl_pct"] >= 0 else "#dc2626"
        pnl_s  = "+" if ps["pnl_pct"] >= 0 else ""
        weight = round(ps["total_ev"] / combined_total * 100, 1) if combined_total > 0 else 0
        stat_rows += (
            f'<div style="display:flex;align-items:center;gap:10px;padding:6px 0;'
            f'border-bottom:1px solid #f1f5f9">'
            f'<div style="width:10px;height:10px;border-radius:50%;background:{color};flex-shrink:0"></div>'
            f'<div style="flex:1;font-size:.82rem;font-weight:600;color:var(--text)">{escape(ps["name"])}</div>'
            f'<div style="font-size:.78rem;color:{pnl_c};font-weight:600">{pnl_s}{ps["pnl_pct"]:.2f}%</div>'
            f'<div style="font-size:.75rem;color:var(--muted);min-width:36px;text-align:right">{weight:.1f}%</div>'
            f'</div>'
        )

    # ── 포트폴리오 카드 HTML ──
    portfolio_cards = ""
    for i, ps in enumerate(portfolio_stats):
        color  = PALETTE[i % len(PALETTE)]
        pnl_c  = "#16a34a" if ps["pnl_pct"] >= 0 else "#dc2626"
        pnl_s  = "+" if ps["pnl_pct"] >= 0 else ""
        nav_html = ""
        if ps["nav_ret"] is not None:
            nc = "#16a34a" if ps["nav_ret"] >= 0 else "#dc2626"
            ns = "+" if ps["nav_ret"] >= 0 else ""
            nav_html = (
                f'<div style="margin-top:6px;font-size:.78rem;color:{nc};font-weight:600">'
                f'계좌 수익률(NAV): {ns}{ps["nav_ret"]:.2f}%</div>'
            )
        portfolio_cards += (
            f'<div class="card" style="cursor:pointer;border-top:3px solid {color}" '
            f'onclick="location.href=\'/u/{uid}/p/{ps["pname"]}?t={token}\'">'
            f'<div style="font-size:.9rem;font-weight:700;color:var(--text);margin-bottom:4px">{escape(ps["name"])}</div>'
            f'<div style="font-size:.72rem;color:var(--muted);margin-bottom:12px">'
            f'기준: {ps["ts"]} · {ps["count"]}개 종목</div>'
            f'<div style="font-size:1.5rem;font-weight:700;color:var(--text)">{fmt_krw(ps["total_ev"])}</div>'
            f'<div style="margin-top:6px;font-size:.85rem;color:{pnl_c};font-weight:600">'
            f'종목 수익률: {pnl_s}{ps["pnl_pct"]:.2f}%</div>'
            f'{nav_html}'
            f'</div>'
        )

    # ── 히스토리 차트 섹션 ──
    hist_section = ""
    hist_js      = ""
    if show_hist:
        hist_section = (
            '<div class="card" style="margin-bottom:16px">'
            '<div class="card-title">포트폴리오별 수익률 추이</div>'
            '<div style="position:relative;height:240px"><canvas id="combinedHistChart"></canvas></div>'
            '</div>'
        )
        hist_js = f"""
try {{
  const combinedHistChart = new Chart(document.getElementById("combinedHistChart"), {{
    type: "line",
    data: {{
      labels: {hist_dates_js},
      datasets: {chart_datasets_json},
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ position: "top", labels: {{ boxWidth: 9, padding: 10, font: {{ size: 11 }} }} }},
        tooltip: {{
          mode: "index", intersect: false,
          callbacks: {{
            label: function(c) {{
              var v = c.parsed.y;
              return " " + c.dataset.label + ": " + (v == null ? "—" : (v >= 0 ? "+" : "") + v.toFixed(2) + "%");
            }},
          }},
        }},
      }},
      scales: {{
        x: {{ grid: {{ display: false }}, ticks: {{ color: "#94a3b8", font: {{ size: 10 }}, maxTicksLimit: 8 }} }},
        y: {{ grid: {{ color: "#f1f5f9" }}, ticks: {{ color: "#94a3b8", callback: function(v) {{ return (v >= 0 ? "+" : "") + v + "%"; }} }} }},
      }},
    }},
  }});
}} catch(e) {{
  console.error("combinedHistChart 오류:", e);
}}"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>전체 포트폴리오</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root {{
  --bg:#f1f5f9; --surface:#fff;
  --border:#e2e8f0; --border-subtle:#f1f5f9;
  --text:#0f172a; --secondary:#64748b; --muted:#94a3b8;
  --pos:#16a34a; --neg:#dc2626; --accent:#0ea5e9;
  --shadow:0 1px 3px rgba(0,0,0,.07),0 1px 2px rgba(0,0,0,.04);
  --shadow-md:0 4px 8px rgba(0,0,0,.06),0 2px 4px rgba(0,0,0,.04);
}}
*,*::before,*::after {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--text); font-family:'Noto Sans KR',sans-serif; min-height:100vh; font-size:14px; -webkit-font-smoothing:antialiased; }}
.topnav {{ background:var(--surface); border-bottom:1px solid var(--border); padding:0 28px; display:flex; align-items:center; height:52px; position:sticky; top:0; z-index:100; box-shadow:0 1px 0 var(--border); }}
.brand {{ font-weight:800; font-size:.95rem; color:var(--text); letter-spacing:-.01em; margin-right:24px; display:flex; align-items:center; gap:7px; flex-shrink:0; }}
.brand-dot {{ width:7px; height:7px; border-radius:50%; background:var(--accent); }}
.tab {{ display:inline-flex; align-items:center; height:52px; padding:0 14px; font-size:.85rem; font-weight:500; color:var(--secondary); text-decoration:none; border-bottom:2px solid transparent; transition:all .15s; white-space:nowrap; }}
.tab:hover {{ color:var(--text); }}
.tab.active {{ color:var(--text); font-weight:700; border-bottom-color:var(--accent); }}
.nav-time {{ margin-left:auto; font-size:.72rem; color:var(--muted); flex-shrink:0; }}
.main {{ max-width:1160px; margin:0 auto; padding:28px 20px 48px; }}
.overview {{ background:var(--surface); border-radius:14px; box-shadow:var(--shadow-md); padding:26px 30px; margin-bottom:16px; display:flex; align-items:center; gap:0; flex-wrap:wrap; row-gap:16px; animation:fadeIn .3s ease both; }}
.ov-main {{ flex-shrink:0; padding-right:30px; border-right:1px solid var(--border); margin-right:30px; }}
.ov-main .ov-label {{ font-size:.68rem; color:var(--muted); text-transform:uppercase; letter-spacing:.1em; margin-bottom:6px; font-weight:600; }}
.ov-main .ov-value {{ font-size:2.1rem; font-weight:700; color:var(--text); letter-spacing:-.03em; line-height:1; }}
.ov-metrics {{ display:flex; gap:0; flex-wrap:wrap; }}
.ov-metric {{ padding:0 26px; border-right:1px solid var(--border); display:flex; flex-direction:column; gap:5px; }}
.ov-metric:last-child {{ border-right:none; }}
.m-label {{ font-size:.68rem; color:var(--muted); text-transform:uppercase; letter-spacing:.08em; font-weight:600; }}
.m-value {{ font-size:1.15rem; font-weight:700; line-height:1; }}
.m-sub {{ font-size:.72rem; color:var(--muted); }}
.charts-grid {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:14px; margin-bottom:16px; }}
@media(max-width:1000px) {{ .charts-grid {{ grid-template-columns:1fr 1fr; }} }}
@media(max-width:640px)  {{ .charts-grid {{ grid-template-columns:1fr; }} }}
.card {{ background:var(--surface); border-radius:14px; box-shadow:var(--shadow); padding:22px; }}
.card-title {{ font-size:.7rem; font-weight:700; color:var(--secondary); text-transform:uppercase; letter-spacing:.12em; margin-bottom:16px; display:flex; align-items:center; gap:8px; }}
.card-title::before {{ content:""; display:inline-block; width:3px; height:11px; background:var(--accent); border-radius:2px; flex-shrink:0; }}
.footer {{ text-align:center; padding:28px 0 4px; font-size:.65rem; color:#cbd5e1; letter-spacing:.1em; text-transform:uppercase; }}
@keyframes fadeIn {{ from {{ opacity:0; transform:translateY(10px); }} to {{ opacity:1; transform:translateY(0); }} }}
.help-wrap {{ position:relative; display:inline-flex; align-items:center; gap:3px; }}
.help-icon {{ display:inline-flex; align-items:center; justify-content:center; width:13px; height:13px; border-radius:50%; background:#cbd5e1; color:#fff; font-size:9px; font-weight:700; cursor:default; line-height:1; flex-shrink:0; }}
.help-tip {{ display:none; position:absolute; bottom:calc(100% + 6px); left:50%; transform:translateX(-50%); background:#1e293b; color:#f8fafc; font-size:.72rem; line-height:1.5; padding:7px 10px; border-radius:8px; white-space:nowrap; z-index:200; pointer-events:none; box-shadow:0 4px 12px rgba(0,0,0,.2); }}
.help-tip::after {{ content:""; position:absolute; top:100%; left:50%; transform:translateX(-50%); border:5px solid transparent; border-top-color:#1e293b; }}
.help-wrap:hover .help-tip {{ display:block; }}
</style>
</head>
<body>

<nav class="topnav">
  <div class="brand"><div class="brand-dot"></div>PORTFOLIO</div>
  {portfolio_tabs}
  <div class="nav-time">기준: {today_str}</div>
</nav>

<div class="main">
  <div class="overview">
    <div class="ov-main">
      <div class="ov-label">총 평가금액</div>
      <div class="ov-value">{fmt_krw(combined_total)}</div>
    </div>
    <div class="ov-metrics">
      <div class="ov-metric">
        <div class="m-label">총 손익</div>
        <div class="m-value" style="color:{pnl_color}">{pnl_sign}{fmt_krw(combined_pnl)}</div>
        <div class="m-sub" style="color:{pnl_color}">{pnl_sign}{combined_pnl_pct:.2f}%</div>
      </div>
      <div class="ov-metric">
        <div class="m-label"><span class="help-wrap">통합 계좌 수익률<span class="help-icon">?</span><span class="help-tip">모든 포트폴리오 입출금 통합 NAV 기준</span></span></div>
        <div class="m-value" style="color:{nav_color}">{nav_sign}{combined_nav_ret:.2f}%</div>
        <div class="m-sub">입출금 제거 기준</div>
      </div>
      <div class="ov-metric">
        <div class="m-label">순 투자원금</div>
        <div class="m-value" style="color:var(--text)">{inv_disp}</div>
        <div class="m-sub">총입금 - 총출금</div>
      </div>
      <div class="ov-metric">
        <div class="m-label">포트폴리오 수</div>
        <div class="m-value" style="color:var(--text)">{len(portfolio_stats)}개</div>
        <div class="m-sub">데이터 있는 포트폴리오</div>
      </div>
    </div>
  </div>

  <div class="charts-grid" style="grid-template-columns:1fr 1fr">
    <div class="card">
      <div class="card-title">포트폴리오별 비중</div>
      <div style="position:relative;height:220px"><canvas id="pieChart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">포트폴리오 현황</div>
      <div style="padding-top:4px">{stat_rows}</div>
    </div>
  </div>

  {hist_section}

  <div class="charts-grid">
    {portfolio_cards}
  </div>

  <div class="footer">Portfolio Dashboard &middot; {today_str} &middot; 투자 참고용</div>
</div>

<script>
try {{
  Chart.defaults.font.family = "'Noto Sans KR',sans-serif";
  Chart.defaults.color = "#94a3b8";
  Chart.defaults.font.size = 11;

  new Chart(document.getElementById("pieChart"), {{
    type: "doughnut",
    data: {{
      labels: {pie_labels},
      datasets: [{{ data: {pie_data}, backgroundColor: {pie_colors}, borderWidth: 3, borderColor: "#fff", hoverOffset: 6 }}],
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      cutout: "65%",
      plugins: {{
        legend: {{ position: "bottom", labels: {{ boxWidth: 9, padding: 12, font: {{ size: 11 }}, color: "#64748b" }} }},
        tooltip: {{ callbacks: {{ label: c => ` ${{c.label}}: ${{c.parsed}}%` }} }},
      }},
    }},
  }});
}} catch(e) {{
  console.error("pieChart 오류:", e);
}}
{hist_js}
</script>
</body>
</html>"""
