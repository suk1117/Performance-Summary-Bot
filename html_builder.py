"""
html_builder.py
포트폴리오 HTML 인포그래픽 생성 모듈
dashboard.py, bot.py 공통으로 사용
"""
from __future__ import annotations
import json
from datetime import datetime
import pandas as pd


def build_html(df: pd.DataFrame) -> str:
    today_str = datetime.now().strftime("%Y.%m.%d %H:%M")

    valid = df[df["수익률(%)"].notna() & (df["국가"] != "현금")]
    total_return = 0.0
    if not valid.empty:
        total_return = (valid["비중(%)"] * valid["수익률(%)"]).sum() / valid["비중(%)"].sum()

    weight_labels = df["종목명"].tolist()
    weight_data   = df["비중(%)"].tolist()

    country_group  = df.groupby("국가")["비중(%)"].sum().reset_index()
    country_labels = country_group["국가"].tolist()
    country_data   = country_group["비중(%)"].tolist()

    ret_df     = df[df["수익률(%)"].notna() & (df["국가"] != "현금")].sort_values("수익률(%)")
    ret_labels = ret_df["종목명"].tolist()
    ret_data   = ret_df["수익률(%)"].tolist()
    ret_colors = ["#FF4560" if v < 0 else "#00E396" for v in ret_data]

    table_rows = ""
    for _, r in df.iterrows():
        ret_val = r["수익률(%)"]
        if pd.isna(ret_val):
            ret_str, ret_class = "—", "neutral"
        elif ret_val > 0:
            ret_str, ret_class = f"+{ret_val:.2f}%", "pos"
        elif ret_val < 0:
            ret_str, ret_class = f"{ret_val:.2f}%", "neg"
        else:
            ret_str, ret_class = "0.00%", "neutral"

        cur_price = r["현재가"]
        cur_str   = f"{cur_price:,.0f}" if pd.notna(cur_price) else "—"
        avg_str   = f"{r['평단가']:,.0f}" if str(r['통화']).upper() == "KRW" else f"{r['평단가']:,.2f}"
        flag      = {"KR": "🇰🇷", "US": "🇺🇸", "현금": "💵"}.get(r["국가"], "🌐")

        table_rows += f"""
        <tr>
          <td><span class="flag">{flag}</span> {r['종목명']}</td>
          <td>{r['티커']}</td>
          <td>{r['국가']}</td>
          <td class="num">{r['비중(%)']:.1f}%</td>
          <td class="num">{avg_str}</td>
          <td class="num">{cur_str}</td>
          <td class="num {ret_class}">{ret_str}</td>
        </tr>"""

    total_class = "pos" if total_return >= 0 else "neg"
    total_sign  = "+" if total_return >= 0 else ""

    wl = json.dumps(weight_labels,  ensure_ascii=False)
    wd = json.dumps(weight_data)
    cl = json.dumps(country_labels, ensure_ascii=False)
    cd = json.dumps(country_data)
    rl = json.dumps(ret_labels,     ensure_ascii=False)
    rd = json.dumps(ret_data)
    rc = json.dumps(ret_colors)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>포트폴리오 대시보드</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:#080c14;--surface:#0d1526;--surface2:#121d35;--border:#1e2d4a;
    --accent:#00d4ff;--pos:#00e396;--neg:#ff4560;--text:#e2e8f0;--muted:#64748b;
    --font-display:'Syne',sans-serif;--font-mono:'DM Mono',monospace;
  }}
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:var(--font-mono);
    min-height:100vh;padding:32px 24px;
    background-image:radial-gradient(ellipse 80% 50% at 50% -20%,rgba(0,212,255,.06),transparent),
      radial-gradient(ellipse 60% 40% at 80% 100%,rgba(123,94,167,.05),transparent)}}
  .header{{display:flex;justify-content:space-between;align-items:flex-end;
    margin-bottom:36px;padding-bottom:20px;border-bottom:1px solid var(--border)}}
  .header h1{{font-family:var(--font-display);font-size:2rem;font-weight:800;
    letter-spacing:-.02em;color:#fff}}
  .header h1 span{{color:var(--accent)}}
  .header .meta{{font-size:.75rem;color:var(--muted);text-align:right;line-height:1.8}}
  .banner{{background:var(--surface);border:1px solid var(--border);border-radius:16px;
    padding:24px 32px;margin-bottom:28px;display:flex;align-items:center;gap:32px;
    position:relative;overflow:hidden}}
  .banner::before{{content:"";position:absolute;inset:0;
    background:linear-gradient(90deg,rgba(0,212,255,.04) 0%,transparent 60%);pointer-events:none}}
  .banner-label{{font-size:.8rem;color:var(--muted);text-transform:uppercase;
    letter-spacing:.12em;margin-bottom:4px}}
  .banner-value{{font-family:var(--font-display);font-size:3rem;font-weight:800;
    letter-spacing:-.03em;line-height:1}}
  .banner-value.pos{{color:var(--pos)}}.banner-value.neg{{color:var(--neg)}}
  .banner-divider{{width:1px;height:56px;background:var(--border)}}
  .grid-3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin-bottom:20px}}
  @media(max-width:900px){{.grid-3{{grid-template-columns:1fr}}}}
  .card{{background:var(--surface);border:1px solid var(--border);border-radius:16px;
    padding:24px;transition:border-color .2s}}
  .card:hover{{border-color:rgba(0,212,255,.3)}}
  .card-title{{font-size:.72rem;color:var(--muted);text-transform:uppercase;
    letter-spacing:.14em;margin-bottom:20px;display:flex;align-items:center;gap:8px}}
  .card-title::before{{content:"";display:inline-block;width:3px;height:12px;
    background:var(--accent);border-radius:2px}}
  .chart-wrap{{position:relative;width:100%;height:240px;display:flex;
    align-items:center;justify-content:center}}
  .table-card{{background:var(--surface);border:1px solid var(--border);border-radius:16px;
    padding:24px;margin-bottom:20px;overflow-x:auto}}
  table{{width:100%;border-collapse:collapse;font-size:.85rem}}
  thead th{{font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);
    padding:10px 14px;border-bottom:1px solid var(--border);text-align:left;font-weight:500}}
  tbody tr{{border-bottom:1px solid rgba(30,45,74,.5);transition:background .15s}}
  tbody tr:hover{{background:var(--surface2)}}
  tbody td{{padding:12px 14px;color:var(--text)}}
  .num{{text-align:right;font-variant-numeric:tabular-nums}}
  .pos{{color:var(--pos)}}.neg{{color:var(--neg)}}.neutral{{color:var(--muted)}}
  .flag{{font-size:1.1em}}
  .refresh-btn{{
    position:fixed;bottom:28px;right:28px;
    background:var(--accent);color:#080c14;
    border:none;border-radius:50px;padding:12px 22px;
    font-family:var(--font-mono);font-size:.85rem;font-weight:700;
    cursor:pointer;box-shadow:0 4px 20px rgba(0,212,255,.35);
    transition:transform .15s,box-shadow .15s;
  }}
  .refresh-btn:hover{{transform:translateY(-2px);box-shadow:0 6px 28px rgba(0,212,255,.5)}}
  .footer{{text-align:center;margin-top:40px;font-size:.72rem;color:var(--muted);letter-spacing:.06em}}
  @keyframes fadeUp{{from{{opacity:0;transform:translateY(18px)}}to{{opacity:1;transform:translateY(0)}}}}
  .card,.banner,.table-card{{animation:fadeUp .5s ease both}}
  .grid-3 .card:nth-child(1){{animation-delay:.05s}}
  .grid-3 .card:nth-child(2){{animation-delay:.10s}}
  .grid-3 .card:nth-child(3){{animation-delay:.15s}}
</style>
</head>
<body>

<div class="header">
  <h1>포트폴리오 <span>대시보드</span></h1>
  <div class="meta">
    <div>기준일: {today_str}</div>
    <div>종목 수: {len(df)}개</div>
  </div>
</div>

<div class="banner">
  <div>
    <div class="banner-label">가중 평균 수익률</div>
    <div class="banner-value {total_class}">{total_sign}{total_return:.2f}%</div>
  </div>
  <div class="banner-divider"></div>
  <div>
    <div class="banner-label">전체 포지션</div>
    <div style="font-family:var(--font-display);font-size:1.8rem;font-weight:700;color:#fff">{len(df)}개 종목</div>
  </div>
  <div class="banner-divider"></div>
  <div>
    <div class="banner-label">현금 비중</div>
    <div style="font-family:var(--font-display);font-size:1.8rem;font-weight:700;color:var(--accent)">
      {df[df['국가']=='현금']['비중(%)'].sum():.1f}%
    </div>
  </div>
</div>

<div class="grid-3">
  <div class="card">
    <div class="card-title">종목별 비중</div>
    <div class="chart-wrap"><canvas id="weightChart"></canvas></div>
  </div>
  <div class="card">
    <div class="card-title">국가별 비중</div>
    <div class="chart-wrap"><canvas id="countryChart"></canvas></div>
  </div>
  <div class="card">
    <div class="card-title">종목별 수익률 (%)</div>
    <div class="chart-wrap"><canvas id="returnChart"></canvas></div>
  </div>
</div>

<div class="table-card">
  <div class="card-title">전체 포지션</div>
  <table>
    <thead>
      <tr>
        <th>종목명</th><th>티커</th><th>국가</th>
        <th style="text-align:right">비중</th>
        <th style="text-align:right">평단가</th>
        <th style="text-align:right">현재가</th>
        <th style="text-align:right">수익률</th>
      </tr>
    </thead>
    <tbody>{table_rows}</tbody>
  </table>
</div>

<button class="refresh-btn" onclick="location.reload()">↻ 새로고침</button>
<div class="footer">PORTFOLIO DASHBOARD · {today_str} · 투자 참고용</div>

<script>
Chart.defaults.color="#64748b";
Chart.defaults.font.family="'DM Mono',monospace";
const PAL=["#00d4ff","#7b5ea7","#00e396","#ff4560","#feb019","#775dd0","#3f51b5","#03a9f4","#4caf50","#f9ce1d","#ff9800","#33b2df"];

new Chart(document.getElementById("weightChart"),{{
  type:"doughnut",
  data:{{labels:{wl},datasets:[{{data:{wd},backgroundColor:PAL,borderWidth:2,borderColor:"#0d1526",hoverOffset:8}}]}},
  options:{{responsive:true,maintainAspectRatio:false,cutout:"62%",
    plugins:{{legend:{{position:"right",labels:{{boxWidth:12,padding:14,font:{{size:11}}}}}},
      tooltip:{{callbacks:{{label:ctx=>` ${{ctx.label}}: ${{ctx.parsed}}%`}}}}}}}}
}});

new Chart(document.getElementById("countryChart"),{{
  type:"doughnut",
  data:{{labels:{cl},datasets:[{{data:{cd},backgroundColor:["#00d4ff","#7b5ea7","#00e396","#ff4560"],borderWidth:2,borderColor:"#0d1526",hoverOffset:8}}]}},
  options:{{responsive:true,maintainAspectRatio:false,cutout:"62%",
    plugins:{{legend:{{position:"right",labels:{{boxWidth:12,padding:14,font:{{size:12}}}}}},
      tooltip:{{callbacks:{{label:ctx=>` ${{ctx.label}}: ${{ctx.parsed}}%`}}}}}}}}
}});

new Chart(document.getElementById("returnChart"),{{
  type:"bar",
  data:{{labels:{rl},datasets:[{{label:"수익률(%)",data:{rd},backgroundColor:{rc},borderRadius:4,borderSkipped:false}}]}},
  options:{{indexAxis:"y",responsive:true,maintainAspectRatio:false,
    plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{ctx.parsed.x>=0?"+":""}}${{ctx.parsed.x.toFixed(2)}}%`}}}}}},
    scales:{{
      x:{{grid:{{color:"rgba(30,45,74,.8)"}},ticks:{{callback:v=>(v>=0?"+":"")+v+"%"}}}},
      y:{{grid:{{display:false}},ticks:{{font:{{size:11}}}}}}
    }}}}
}});
</script>
</body>
</html>"""
