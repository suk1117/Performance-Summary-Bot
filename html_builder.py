"""
html_builder.py
포트폴리오 HTML 인포그래픽 생성 모듈
"""
from __future__ import annotations
import json
import pandas as pd
from datetime import datetime


def _build_sidebar(all_users: dict, current_uid) -> str:
    if not all_users:
        return '<div class="s-empty">유저 없음</div>'
    items = ""
    for uid, u in all_users.items():
        df    = u["df"]
        name  = u.get("name", f"User {uid}")
        valid = df[df["수익률(%)"].notna() & (df["국가"] != "현금")]
        if not valid.empty:
            total     = (valid["비중(%)"] * valid["수익률(%)"]).sum() / valid["비중(%)"].sum()
            ret_str   = f"{'+' if total>=0 else ''}{total:.1f}%"
            ret_class = "s-pos" if total >= 0 else "s-neg"
        else:
            ret_str, ret_class = "—", "s-neu"
        active = "active" if uid == current_uid else ""
        items += (
            f'<a href="/user/{uid}" class="s-item {active}">'
            f'<div class="s-avatar">{name[0].upper()}</div>'
            f'<div class="s-info">'
            f'<div class="s-name">{name}</div>'
            f'<div class="s-ret {ret_class}">{ret_str}</div>'
            f'</div></a>'
        )
    return items


def build_index_html(users: dict) -> str:
    if users:
        first_uid = next(iter(users))
        return f'<meta http-equiv="refresh" content="0;url=/user/{first_uid}">'
    return """<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<style>body{background:#080c14;color:#64748b;font-family:monospace;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
</style></head><body><div>
<div style="font-size:3rem;margin-bottom:16px">📂</div>
<div style="font-size:1.1rem;color:#e2e8f0">대기 중</div>
<div style="margin-top:8px;font-size:.85rem">텔레그램 봇에 .xlsx 파일을 전송하세요</div>
</div></body></html>"""


def build_user_html(
    df: pd.DataFrame,
    display_name: str = "",
    all_users: dict = None,
    current_uid=None,
) -> str:
    today_str = datetime.now().strftime("%Y.%m.%d %H:%M")
    all_users = all_users or {}
    sidebar   = _build_sidebar(all_users, current_uid)

    # ── 수익률 계산 ──
    valid = df[df["수익률(%)"].notna() & (df["국가"] != "현금")]
    total_return = (
        (valid["비중(%)"] * valid["수익률(%)"]).sum() / valid["비중(%)"].sum()
        if not valid.empty else 0.0
    )

    # ── 차트 데이터 ──
    wl = json.dumps(df["종목명"].tolist(), ensure_ascii=False)
    wd = json.dumps(df["비중(%)"].tolist())

    cg = df.groupby("국가")["비중(%)"].sum().reset_index()
    cl = json.dumps(cg["국가"].tolist(), ensure_ascii=False)
    cd = json.dumps(cg["비중(%)"].tolist())

    # 수익률 차트: 수직 막대 (높은 값이 왼쪽)
    ret_df = (
        df[df["수익률(%)"].notna() & (df["국가"] != "현금")]
        .sort_values("수익률(%)", ascending=True)   # 낮→높 = 왼→오
    )
    rl = json.dumps(ret_df["종목명"].tolist(), ensure_ascii=False)
    rd = json.dumps(ret_df["수익률(%)"].tolist())
    # 수익률 차트 색상: 종목별 비중 도넛과 동일한 팔레트
    PALETTE = ["#00d4ff","#7b5ea7","#00e396","#ff4560","#feb019","#775dd0","#3f51b5","#03a9f4","#4caf50","#f9ce1d"]
    name_to_idx = {name: i for i, name in enumerate(df["종목명"].tolist())}
    rc = json.dumps([PALETTE[name_to_idx.get(n, 0) % len(PALETTE)] for n in ret_df["종목명"].tolist()])
    ret_count = len(ret_df)

    # ── 매수/평가금액 ──
    usd_krw = float(df["USD_KRW"].iloc[0]) if "USD_KRW" in df.columns else 1370.0
    total_buy = total_eval = 0.0
    table_rows = ""
    for _, r in df.iterrows():
        ret_val  = r["수익률(%)"]
        cur_price = r.get("현재가")
        avg      = float(r["평단가"])
        weight   = float(r["비중(%)"])
        currency = str(r["통화"]).upper()
        flag     = {"KR": "🇰🇷", "US": "🇺🇸", "현금": "💵"}.get(r["국가"], "🌐")

        # 수익률 셀
        if pd.isna(ret_val):
            ret_str, ret_class = "조회실패", "neutral"
        elif ret_val > 0:
            ret_str, ret_class = f"+{ret_val:.2f}%", "pos"
        elif ret_val < 0:
            ret_str, ret_class = f"{ret_val:.2f}%", "neg"
        else:
            ret_str, ret_class = "0.00%", "neutral"

        # 가격 표시
        cur_str = f"{cur_price:,.0f}" if pd.notna(cur_price) else "—"
        avg_str = f"{avg:,.0f}" if currency == "KRW" else f"{avg:,.2f}"

        # 매수/평가금액 (원화 환산)
        multiplier = usd_krw if currency == "USD" else 1.0
        buy_krw  = avg * multiplier * (weight / 100)
        total_buy += buy_krw
        if pd.notna(cur_price):
            eval_krw = float(cur_price) * multiplier * (weight / 100)
            total_eval += eval_krw
            eval_str = f"₩{eval_krw:,.0f}" if currency == "KRW" else f"${float(cur_price)*weight/100:,.2f}"
        else:
            eval_str = "—"

        buy_str = f"₩{buy_krw:,.0f}" if currency == "KRW" else f"${avg*weight/100:,.2f}"

        table_rows += (
            f"<tr>"
            f"<td><span class='flag'>{flag}</span> {r['종목명']}</td>"
            f"<td>{r['국가']}</td>"
            f"<td class='num'>{weight:.1f}%</td>"
            f"<td class='num'>{avg_str}</td>"
            f"<td class='num'>{cur_str}</td>"
            f"<td class='num {ret_class}'>{ret_str}</td>"
            f"<td class='num'>{buy_str}</td>"
            f"<td class='num'>{eval_str}</td>"
            f"</tr>"
        )

    total_class = "pos" if total_return >= 0 else "neg"
    total_sign  = "+" if total_return >= 0 else ""
    cash_weight = df[df["국가"] == "현금"]["비중(%)"].sum()
    title_name  = display_name or "포트폴리오"

    buy_disp  = f"₩{total_buy/10000:,.0f}만" if total_buy >= 10000 else f"₩{total_buy:,.0f}"
    eval_disp = f"₩{total_eval/10000:,.0f}만" if total_eval >= 10000 else f"₩{total_eval:,.0f}"

    # 수익률 차트 높이: 종목당 60px, 최소 160px
    ret_chart_h = max(160, ret_count * 60)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title_name} · 포트폴리오</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{{
  --bg:#080c14;--surface:#0d1526;--surface2:#121d35;--border:#1e2d4a;
  --accent:#38bdf8;--pos:#4ade80;--neg:#f87171;--text:#f1f5f9;--muted:#94a3b8;
  --sw:180px;
  --font-d:'Syne',sans-serif;--font-m:'DM Mono',monospace;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{
  background:var(--bg);color:var(--text);font-family:var(--font-m);
  min-height:100vh;display:flex;flex-direction:row;
  background-image:
    radial-gradient(ellipse 80% 50% at 50% -20%,rgba(0,212,255,.05),transparent),
    radial-gradient(ellipse 60% 40% at 80% 100%,rgba(123,94,167,.04),transparent);
}}

/* ── 사이드바 ── */
.sidebar{{
  width:var(--sw);min-width:var(--sw);flex-shrink:0;
  background:rgba(13,21,38,.98);border-right:1px solid var(--border);
  display:flex;flex-direction:column;padding:16px 10px;gap:4px;
  position:sticky;top:0;height:100vh;overflow-y:auto;z-index:10;
}}
.s-label{{
  font-size:.62rem;color:var(--muted);text-transform:uppercase;
  letter-spacing:.14em;padding:0 8px 12px;border-bottom:1px solid var(--border);
  margin-bottom:6px;font-family:var(--font-d);
}}
.s-item{{
  display:flex;align-items:center;gap:8px;padding:8px 9px;
  border-radius:9px;text-decoration:none;color:inherit;
  border:1px solid transparent;transition:all .15s;
}}
.s-item:hover{{background:var(--surface2);border-color:var(--border);}}
.s-item.active{{background:var(--surface);border-color:var(--accent);}}
.s-avatar{{
  width:26px;height:26px;border-radius:50%;flex-shrink:0;
  background:linear-gradient(135deg,#7b5ea7,#3f51b5);
  display:flex;align-items:center;justify-content:center;
  font-family:var(--font-d);font-weight:800;font-size:.75rem;color:#fff;
}}
.s-item.active .s-avatar{{background:linear-gradient(135deg,var(--accent),#00e396);}}
.s-info{{min-width:0;}}
.s-name{{font-size:.82rem;color:#e2e8f0;font-weight:600;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.s-ret{{font-size:.76rem;font-family:var(--font-d);font-weight:700;}}
.s-pos{{color:var(--pos);}} .s-neg{{color:var(--neg);}} .s-neu{{color:var(--muted);}}
.s-empty{{font-size:.72rem;color:var(--muted);padding:6px 9px;}}

/* ── 메인 ── */
.main{{flex:1;min-width:0;padding:24px 24px 48px;overflow-y:auto;}}
.header{{
  display:flex;justify-content:space-between;align-items:center;
  margin-bottom:20px;padding-bottom:16px;border-bottom:1px solid var(--border);
}}
.header h1{{font-family:var(--font-d);font-size:1.5rem;font-weight:800;
  letter-spacing:-.02em;color:#f8fafc;}}
.header h1 span{{color:var(--accent);}}
.header .meta{{font-size:.7rem;color:var(--muted);text-align:right;line-height:1.9;}}

/* ── 배너 ── */
.banner{{
  background:var(--surface);border:1px solid var(--border);border-radius:14px;
  padding:18px 24px;margin-bottom:20px;display:flex;align-items:center;
  gap:24px;flex-wrap:wrap;position:relative;overflow:hidden;
}}
.banner::before{{content:"";position:absolute;inset:0;
  background:linear-gradient(90deg,rgba(0,212,255,.04),transparent 60%);pointer-events:none;}}
.banner-item{{display:flex;flex-direction:column;gap:4px;}}
.banner-label{{font-size:.75rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em;}}
.banner-value{{font-family:var(--font-d);font-size:1.6rem;font-weight:800;
  letter-spacing:-.03em;line-height:1;}}
.banner-value.pos{{color:var(--pos);}} .banner-value.neg{{color:var(--neg);}}
.banner-sub{{font-family:var(--font-d);font-size:1.3rem;font-weight:700;color:#f1f5f9;}}
.banner-sub.accent{{color:var(--accent);}}
.b-div{{width:1px;height:44px;background:var(--border);flex-shrink:0;}}

/* ── 차트 그리드 ── */
.grid-3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-bottom:14px;}}
@media(max-width:1100px){{.grid-3{{grid-template-columns:1fr 1fr;}}}}
@media(max-width:700px){{.grid-3{{grid-template-columns:1fr;}}}}

.card{{
  background:var(--surface);border:1px solid var(--border);border-radius:13px;
  padding:18px;transition:border-color .2s;
}}
.card:hover{{border-color:rgba(0,212,255,.3);}}
.card-title{{
  font-size:.78rem;color:#94a3b8;text-transform:uppercase;
  letter-spacing:.10em;margin-bottom:14px;display:flex;align-items:center;gap:7px;
}}
.card-title::before{{content:"";display:inline-block;width:3px;height:10px;
  background:var(--accent);border-radius:2px;}}

/* ── 테이블 ── */
.table-card{{
  background:var(--surface);border:1px solid var(--border);
  border-radius:13px;padding:18px;margin-bottom:14px;overflow-x:auto;
}}
table{{width:100%;border-collapse:collapse;font-size:.88rem;}}
thead th{{
  font-size:.75rem;text-transform:uppercase;letter-spacing:.06em;color:#cbd5e1;
  padding:10px 11px;border-bottom:1px solid var(--border);text-align:left;font-weight:600;
}}
tbody tr{{border-bottom:1px solid rgba(30,45,74,.5);transition:background .12s;}}
tbody tr:hover{{background:var(--surface2);}}
tbody td{{padding:12px 11px;color:#f1f5f9;}}
.num{{text-align:right;font-variant-numeric:tabular-nums;}}
.pos{{color:var(--pos);}} .neg{{color:var(--neg);}} .neutral{{color:var(--muted);}}
.flag{{font-size:1em;}}
.footer{{text-align:center;margin-top:28px;font-size:.65rem;color:var(--muted);letter-spacing:.06em;}}

@keyframes fadeUp{{from{{opacity:0;transform:translateY(14px)}}to{{opacity:1;transform:translateY(0)}}}}
.card,.banner,.table-card{{animation:fadeUp .4s ease both;}}
.grid-3 .card:nth-child(1){{animation-delay:.03s;}}
.grid-3 .card:nth-child(2){{animation-delay:.07s;}}
.grid-3 .card:nth-child(3){{animation-delay:.12s;}}
</style>
</head>
<body>

<!-- ── 사이드바 ── -->
<nav class="sidebar">
  <div class="s-label">👤 유저 선택</div>
  {sidebar}
</nav>

<!-- ── 메인 ── -->
<div class="main">
  <div class="header">
    <h1><span>{title_name}</span>의 포트폴리오</h1>
    <div class="meta">
      <div>기준일: {today_str}</div>
      <div>종목 수: {len(df)}개</div>
    </div>
  </div>

  <div class="banner">
    <div class="banner-item">
      <div class="banner-label">가중 평균 수익률</div>
      <div class="banner-value {total_class}">{total_sign}{total_return:.2f}%</div>
    </div>
    <div class="b-div"></div>
    <div class="banner-item">
      <div class="banner-label">전체 포지션</div>
      <div class="banner-sub">{len(df)}개 종목</div>
    </div>
    <div class="b-div"></div>
    <div class="banner-item">
      <div class="banner-label">현금 비중</div>
      <div class="banner-sub accent">{cash_weight:.1f}%</div>
    </div>
    <div class="b-div"></div>
    <div class="banner-item">
      <div class="banner-label">총 매수금액</div>
      <div class="banner-sub">{buy_disp}</div>
    </div>
    <div class="b-div"></div>
    <div class="banner-item">
      <div class="banner-label">총 평가금액</div>
      <div class="banner-sub accent">{eval_disp}</div>
    </div>
  </div>

  <div class="grid-3">
    <div class="card">
      <div class="card-title">종목별 비중</div>
      <div style="position:relative;width:100%;height:220px">
        <canvas id="weightChart"></canvas>
      </div>
    </div>
    <div class="card">
      <div class="card-title">국가별 비중</div>
      <div style="position:relative;width:100%;height:220px">
        <canvas id="countryChart"></canvas>
      </div>
    </div>
    <div class="card">
      <div class="card-title">종목별 수익률 (%)</div>
      <div style="position:relative;width:100%;height:{ret_chart_h}px">
        <canvas id="returnChart"></canvas>
      </div>
    </div>
  </div>

  <div class="table-card">
    <div class="card-title">전체 포지션</div>
    <table>
      <thead><tr>
        <th>종목명</th><th>국가</th>
        <th style="text-align:right">비중</th>
        <th style="text-align:right">평단가</th>
        <th style="text-align:right">현재가</th>
        <th style="text-align:right">수익률</th>
        <th style="text-align:right">매수금액</th>
        <th style="text-align:right">평가금액</th>
      </tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>

  <div class="footer">PORTFOLIO DASHBOARD · {today_str} · 투자 참고용</div>
</div>

<script>
Chart.defaults.color = "#cbd5e1";
Chart.defaults.font.size = 12;
Chart.defaults.font.family = "'DM Mono',monospace";
const P = ["#00d4ff","#7b5ea7","#00e396","#ff4560","#feb019","#775dd0","#3f51b5","#03a9f4","#4caf50","#f9ce1d"];

// 종목별 비중 도넛
new Chart(document.getElementById("weightChart"), {{
  type: "doughnut",
  data: {{
    labels: {wl},
    datasets: [{{ data: {wd}, backgroundColor: P, borderWidth: 2, borderColor: "#0d1526", hoverOffset: 8 }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false, cutout: "62%",
    plugins: {{
      legend: {{ position: "bottom", labels: {{ boxWidth: 10, padding: 10, font: {{ size: 10 }} }} }},
      tooltip: {{ callbacks: {{ label: c => ` ${{c.label}}: ${{c.parsed}}%` }} }}
    }}
  }}
}});

// 국가별 비중 도넛
new Chart(document.getElementById("countryChart"), {{
  type: "doughnut",
  data: {{
    labels: {cl},
    datasets: [{{ data: {cd}, backgroundColor: ["#00d4ff","#7b5ea7","#00e396","#ff4560"], borderWidth: 2, borderColor: "#0d1526", hoverOffset: 8 }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false, cutout: "62%",
    plugins: {{
      legend: {{ position: "bottom", labels: {{ boxWidth: 10, padding: 10, font: {{ size: 11 }} }} }},
      tooltip: {{ callbacks: {{ label: c => ` ${{c.label}}: ${{c.parsed}}%` }} }}
    }}
  }}
}});

// 종목별 수익률 — 수직 막대 (아래→위)
new Chart(document.getElementById("returnChart"), {{
  type: "bar",
  data: {{
    labels: {rl},
    datasets: [{{
      label: "수익률(%)",
      data: {rd},
      backgroundColor: {rc},
      borderRadius: {{ topLeft: 4, topRight: 4 }},
      borderSkipped: "bottom"
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: c => ` ${{c.parsed.y >= 0 ? "+" : ""}}${{c.parsed.y.toFixed(2)}}%` }} }}
    }},
    scales: {{
      x: {{
        grid: {{ display: false }},
        ticks: {{ font: {{ size: 10 }} }}
      }},
      y: {{
        grid: {{ color: "rgba(30,45,74,.8)" }},
        ticks: {{ callback: v => (v >= 0 ? "+" : "") + v + "%" }}
      }}
    }}
  }}
}});
</script>
</body>
</html>"""


def build_html(df: pd.DataFrame) -> str:
    return build_user_html(df)
