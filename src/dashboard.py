import hashlib
import html
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.scraper import extract_staff_mark

JST = timezone(timedelta(hours=9))

GATE_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="robots" content="noindex, nofollow">
<title>出品トラッキングダッシュボード</title>
<style>
  body{{margin:0;background:#0B1220;color:#E8EDF7;font-family:'Segoe UI',Arial,sans-serif;}}
  #gate{{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;gap:12px;}}
  #gate input{{background:#0F1830;border:1px solid #233047;color:#E8EDF7;border-radius:6px;padding:10px 14px;font-size:14px;width:220px;}}
  #gate button{{background:#4C8DFF;border:none;color:white;border-radius:6px;padding:10px 18px;font-size:14px;cursor:pointer;}}
  #gate .err{{color:#F87171;font-size:12px;height:16px;}}
</style>
</head>
<body>
<div id="gate">
  <div>このページはパスワードで保護されています</div>
  <input type="password" id="gate-pw" placeholder="パスワード" autofocus>
  <button onclick="tryUnlock()">開く</button>
  <div class="err" id="gate-err"></div>
</div>
<iframe id="content" style="display:none;position:fixed;top:0;left:0;width:100%;height:100vh;border:none;" srcdoc="{content}"></iframe>
<script>
async function sha256(msg) {{
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(msg));
  return Array.from(new Uint8Array(buf)).map(b=>b.toString(16).padStart(2,'0')).join('');
}}
const HASH = "{password_hash}";
function unlock(){{
  document.getElementById('gate').style.display='none';
  document.getElementById('content').style.display='block';
}}
async function tryUnlock(){{
  const pw = document.getElementById('gate-pw').value;
  if(await sha256(pw) === HASH){{
    sessionStorage.setItem('unlocked','1');
    unlock();
  }} else {{
    document.getElementById('gate-err').textContent = 'パスワードが違います';
  }}
}}
document.getElementById('gate-pw').addEventListener('keydown', e=>{{ if(e.key==='Enter') tryUnlock(); }});
if(sessionStorage.getItem('unlocked')==='1'){{ unlock(); }}
</script>
</body>
</html>
"""

ACCOUNTS = ["さーぱす", "サーパス", "surpass"]
ACC_CLASS = {"さーぱす": "acc-a", "サーパス": "acc-b", "surpass": "acc-c"}

TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>出品トラッキングダッシュボード</title>
<style>
  :root{{
    --bg:#0B1220; --panel:#111A2E; --panel2:#0F1830; --border:#233047;
    --text:#E8EDF7; --sub:#8B98B3; --accent:#4C8DFF; --good:#34D399; --bad:#F87171; --warn:#FBBF24;
  }}
  *{{box-sizing:border-box;}}
  body{{margin:0;background:var(--bg);}}
  .wrap{{font-family:'Segoe UI',Arial,sans-serif;background:var(--bg);color:var(--text);padding:22px;border-radius:12px;}}
  .head{{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:16px;flex-wrap:wrap;gap:10px;}}
  .head h1{{font-size:19px;margin:0 0 4px;font-weight:700;letter-spacing:.2px;}}
  .head p{{margin:0;color:var(--sub);font-size:12.5px;}}
  .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:14px;}}
  .card{{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:12px 14px;}}
  .card .n{{font-size:22px;font-weight:700;}}
  .card .l{{font-size:11px;color:var(--sub);margin-top:2px;}}
  .good{{color:var(--good);}} .bad{{color:var(--bad);}} .warn{{color:var(--warn);}}
  .accrow{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:16px;}}
  .acard{{background:var(--panel2);border:1px solid var(--border);border-radius:10px;padding:10px 12px;}}
  .acard .an{{font-size:13px;font-weight:700;}}
  .acard .av{{font-size:11px;color:var(--sub);margin-top:3px;}}
  .controls{{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;}}
  select,input{{background:var(--panel2);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:6px 10px;font-size:12.5px;}}
  table{{width:100%;border-collapse:collapse;background:var(--panel);border-radius:10px;overflow:hidden;font-size:12px;}}
  th{{background:var(--panel2);color:var(--sub);text-align:left;padding:9px 10px;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.4px;border-bottom:1px solid var(--border);}}
  td{{padding:8px 10px;border-bottom:1px solid var(--border);vertical-align:middle;}}
  tr:hover td{{background:#152242;}}
  tr.row-nobid td{{background:rgba(248,113,113,.06);}}
  tr.row-new td{{background:rgba(76,141,255,.08);}}
  .badge{{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap;}}
  .b-ari{{background:rgba(52,211,153,.15);color:var(--good);}}
  .b-nashi{{background:rgba(248,113,113,.15);color:var(--bad);}}
  .b-active{{background:rgba(76,141,255,.15);color:var(--accent);}}
  .b-end{{background:rgba(139,152,179,.15);color:var(--sub);}}
  .acc-a{{background:rgba(76,141,255,.15);color:#7FA8FF;}}
  .acc-b{{background:rgba(251,191,36,.15);color:var(--warn);}}
  .acc-c{{background:rgba(52,211,153,.15);color:var(--good);}}
  .acc-x{{background:rgba(248,113,113,.15);color:var(--bad);}}
  .b-mark{{background:rgba(139,152,179,.15);color:var(--text);font-size:13px;}}
  .b-trade-wait{{background:rgba(248,113,113,.15);color:var(--bad);}}
  .b-trade-ship{{background:rgba(251,191,36,.15);color:var(--warn);}}
  .b-trade-shipped{{background:rgba(76,141,255,.15);color:var(--accent);}}
  .b-trade-complete{{background:rgba(52,211,153,.15);color:var(--good);}}
  .b-trade-none{{background:rgba(139,152,179,.15);color:var(--sub);}}
  .b-trade-error{{background:rgba(248,113,113,.3);color:#fff;font-weight:700;}}
  .markrow{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-bottom:16px;}}
  .mcard{{background:var(--panel2);border:1px solid var(--border);border-radius:10px;padding:8px 10px;}}
  .mcard .mn{{font-size:13px;font-weight:700;}}
  .mcard .mv{{font-size:11px;color:var(--sub);margin-top:2px;}}
  a{{color:var(--accent);text-decoration:none;}}
  a:hover{{text-decoration:underline;}}
  .idcell{{font-family:monospace;color:var(--sub);font-size:11px;}}
  .name{{max-width:280px;}}
  .note{{font-size:11px;color:var(--sub);margin-top:10px;}}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div>
      <h1>出品トラッキングダッシュボード</h1>
      <p>最終確認：{generated_at} 時点 ／ 全{total}件 ／ 3アカウント運用</p>
    </div>
  </div>

  <div class="cards" id="cards"></div>
  <div class="accrow" id="accCards"></div>
  <div class="markrow" id="markCards"></div>

  <div class="controls">
    <select id="fDay"><option value="">全日程</option></select>
    <select id="fAcc"><option value="">全アカウント</option></select>
    <select id="fMark"><option value="">全記号（担当者）</option></select>
    <select id="fBid"><option value="">入札 全て</option><option value="あり">入札あり</option><option value="なし">入札なし</option></select>
    <select id="fStatus"><option value="">状態 全て</option><option value="出品中">出品中</option><option value="終了">終了</option></select>
    <select id="fTrade"><option value="">取引状況 全て</option><option value="ADDRESS_INPUTING">入金待ち</option><option value="PREPARATION_FOR_SHIPMENT">発送待ち(要対応)</option><option value="SHIPPING">受け取り待ち</option><option value="COMPLETE">着金済み</option><option value="ERROR">要確認(エラー)</option></select>
    <input id="fSearch" placeholder="商品名/IDで検索..." />
  </div>

  <table>
    <thead>
      <tr><th>出品日</th><th>アカウント</th><th>記号</th><th>ID</th><th>商品名</th><th>現在価格</th><th>入札</th><th>終了日時</th><th>状態</th><th>落札金額</th><th>取引状況</th></tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
  <div class="note">※入札なしの行はうっすら赤、当日出品（新規）の行はうっすら青でハイライトしています。「記号」は商品名先頭の記号（現場担当者の識別記号）。「取引状況」は落札後の入金・発送・受け取り連絡の進捗です(ログイン取得できたアカウントのみ)。</div>
</div>

<script>
const DATA = {data_json};
const ACC_CLASS = {acc_class_json};
const LATEST_DAY = {latest_day_json};

const daySel = document.getElementById('fDay');
[...new Set(DATA.map(d=>d.day))].sort().forEach(d=>{{
  const o=document.createElement('option'); o.value=d; o.textContent=d; daySel.appendChild(o);
}});
const accSel = document.getElementById('fAcc');
[...new Set(DATA.map(d=>d.account))].forEach(a=>{{
  const o=document.createElement('option'); o.value=a; o.textContent=a; accSel.appendChild(o);
}});
const markSel = document.getElementById('fMark');
[...new Set(DATA.map(d=>d.mark))].sort().forEach(m=>{{
  const o=document.createElement('option'); o.value=m; o.textContent=m; markSel.appendChild(o);
}});

function accBadgeClass(a){{ return ACC_CLASS[a] || 'acc-x'; }}

function renderCards(rows){{
  const total = rows.length;
  const withBid = rows.filter(r=>r.bids>0).length;
  const rate = total? ((withBid/total)*100).toFixed(1):"0.0";
  const totalBids = rows.reduce((a,r)=>a+r.bids,0);
  const ended = rows.filter(r=>r.status==="終了").length;
  document.getElementById('cards').innerHTML = `
    <div class="card"><div class="n">${{total}}</div><div class="l">表示中の出品数</div></div>
    <div class="card"><div class="n good">${{withBid}}</div><div class="l">入札あり件数</div></div>
    <div class="card"><div class="n warn">${{rate}}%</div><div class="l">入札率</div></div>
    <div class="card"><div class="n">${{totalBids}}</div><div class="l">合計入札件数</div></div>
    <div class="card"><div class="n">${{ended}}</div><div class="l">終了済み件数</div></div>
  `;
  const accs = [...new Set(DATA.map(d=>d.account))];
  document.getElementById('accCards').innerHTML = accs.map(a=>{{
    const sub = DATA.filter(r=>r.account===a);
    const bid = sub.filter(r=>r.bids>0).length;
    const rt = sub.length? ((bid/sub.length)*100).toFixed(0):"0";
    return `<div class="acard"><div class="an"><span class="badge ${{accBadgeClass(a)}}">${{a}}</span></div><div class="av">${{sub.length}}件 ／ 入札率${{rt}}%</div></div>`;
  }}).join('');
  const marks = [...new Set(DATA.map(d=>d.mark))].sort();
  document.getElementById('markCards').innerHTML = marks.map(m=>{{
    const sub = DATA.filter(r=>r.mark===m);
    const bid = sub.filter(r=>r.bids>0).length;
    const rt = sub.length? ((bid/sub.length)*100).toFixed(0):"0";
    return `<div class="mcard"><div class="mn">${{m}}</div><div class="mv">${{sub.length}}件 ／ 入札率${{rt}}%</div></div>`;
  }}).join('');
}}

const TRADE_LABELS = {{
  ADDRESS_INPUTING: '落札者からの連絡待ちです(入金待ち)',
  PREPARATION_FOR_SHIPMENT: '発送をしてください(発送待ち・要対応)',
  SHIPPING: '発送完了しました(受け取り待ち)',
  COMPLETE: '受け取り連絡がされました(着金)',
}};
const TRADE_CLASSES = {{
  ADDRESS_INPUTING: 'b-trade-wait', PREPARATION_FOR_SHIPMENT: 'b-trade-ship',
  SHIPPING: 'b-trade-shipped', COMPLETE: 'b-trade-complete',
}};
const TRADE_ERROR_LABEL = '取引状況を確認してください(要確認)';
function tradeLabel(r){{
  if(!r.tradeProgress) return '-';
  return TRADE_LABELS[r.tradeProgress] || TRADE_ERROR_LABEL;
}}
function tradeClass(r){{
  if(!r.tradeProgress) return 'b-trade-none';
  return TRADE_CLASSES[r.tradeProgress] || 'b-trade-error';
}}

function renderTable(){{
  const dv=daySel.value, av=accSel.value, mv=markSel.value, bv=document.getElementById('fBid').value,
        sv=document.getElementById('fStatus').value,
        tv=document.getElementById('fTrade').value,
        q=document.getElementById('fSearch').value.trim();
  const rows = DATA.filter(r=>{{
    if(dv && r.day!==dv) return false;
    if(av && r.account!==av) return false;
    if(mv && r.mark!==mv) return false;
    if(bv==="あり" && r.bids<=0) return false;
    if(bv==="なし" && r.bids>0) return false;
    if(sv && r.status!==sv) return false;
    if(tv==="ERROR" && !(r.tradeProgress && !TRADE_LABELS[r.tradeProgress])) return false;
    if(tv && tv!=="ERROR" && r.tradeProgress!==tv) return false;
    if(q && !(r.name.includes(q)||r.id.includes(q))) return false;
    return true;
  }});
  renderCards(rows);
  document.getElementById('tbody').innerHTML = rows.map(r=>{{
    const rowClass = r.bids<=0 ? 'row-nobid' : (r.day===LATEST_DAY ? 'row-new' : '');
    return `
    <tr class="${{rowClass}}">
      <td>${{r.day||'-'}}</td>
      <td><span class="badge ${{accBadgeClass(r.account)}}">${{r.account}}</span></td>
      <td><span class="badge b-mark">${{r.mark}}</span></td>
      <td class="idcell"><a href="https://auctions.yahoo.co.jp/jp/auction/${{r.id}}" target="_blank">${{r.id}}</a></td>
      <td class="name">${{r.name}}</td>
      <td>${{r.price!==null? '¥'+r.price.toLocaleString() : '-'}}</td>
      <td><span class="badge ${{r.bids>0?'b-ari':'b-nashi'}}">${{r.bids>0?'あり('+r.bids+')':'なし'}}</span></td>
      <td>${{r.end||'-'}}</td>
      <td><span class="badge ${{r.status==='出品中'?'b-active':'b-end'}}">${{r.status}}</span></td>
      <td>${{r.final!==null? '¥'+r.final.toLocaleString() : '-'}}</td>
      <td><span class="badge ${{tradeClass(r)}}">${{tradeLabel(r)}}</span></td>
    </tr>
  `;}}).join('');
}}

['fDay','fAcc','fMark','fBid','fStatus','fTrade'].forEach(id=>document.getElementById(id).addEventListener('change',renderTable));
document.getElementById('fSearch').addEventListener('input',renderTable);
renderTable();
</script>
</body>
</html>
"""


def _row_to_data(row) -> dict:
    return {
        "day": row["listed_date"],
        "account": row["account_name"],
        "id": row["auction_id"],
        "name": row["title"],
        "price": row["current_price"],
        "bids": row["bid_count"] or 0,
        "end": row["end_datetime"],
        "status": row["status"],
        "final": row["final_price"],
        "source": row["source"],
        "mark": extract_staff_mark(row["title"]) or "(なし)",
        "tradeProgress": row["trade_progress"],
        "tradeMessage": row["trade_message"],
    }


def render_html(rows) -> str:
    data = [_row_to_data(r) for r in rows]
    latest_day = max((d["day"] for d in data if d["day"]), default="")
    return TEMPLATE.format(
        generated_at=datetime.now(JST).strftime("%Y/%m/%d %H:%M"),
        total=len(data),
        data_json=json.dumps(data, ensure_ascii=False),
        acc_class_json=json.dumps(ACC_CLASS, ensure_ascii=False),
        latest_day_json=json.dumps(latest_day, ensure_ascii=False),
    )


def wrap_with_password_gate(page_html: str, password: str) -> str:
    password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return GATE_TEMPLATE.format(content=html.escape(page_html, quote=True), password_hash=password_hash)


def render(rows, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_html(rows), encoding="utf-8")
    print(f"ダッシュボードを生成しました: {output_path}")
