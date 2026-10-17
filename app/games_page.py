CASE_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Северо-Юг · Кейсы</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--bg:#0f1117;--card:#171a23;--line:#252a38;--ink:#e8ebf2;--muted:#8b93a7}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--ink);min-height:100vh;padding-bottom:110px}
header{position:sticky;top:0;z-index:5;background:rgba(15,17,23,.94);border-bottom:1px solid var(--line);padding:14px 16px;display:flex;align-items:baseline;justify-content:space-between}
h1{margin:0;font-size:19px}
.wallet{font-weight:700;font-size:15px;background:#1e2140;color:#c7c9ff;border-radius:999px;padding:7px 14px}
main{padding:16px 0 0}
.reelwrap{position:relative;overflow:hidden;padding:14px 0;background:#12141c;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.reel{display:flex;gap:8px;will-change:transform}
.tile{flex:0 0 96px;width:96px;height:118px;border-radius:12px;background:#1b1f2b;border:2px solid #334155;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px}
.tile .emoji{font-size:26px;line-height:1}
.tile .tname{font-size:11px;text-align:center;padding:0 4px;color:#e5e7eb;max-height:28px;overflow:hidden}
.tile .tpoints{font-size:11px;color:var(--muted)}
.marker{position:absolute;left:50%;top:0;bottom:0;width:2px;background:#f59e0b;box-shadow:0 0 12px #f59e0b;z-index:3}
.result{margin:16px;padding:14px;border-radius:14px;background:var(--card);border:1px solid var(--line);font-size:14px;line-height:1.5;min-height:56px;display:flex;align-items:center;justify-content:center;text-align:center}
.open{margin:0 16px;width:calc(100% - 32px);border:0;border-radius:14px;padding:16px;font-size:16px;font-weight:700;color:#fff;background:linear-gradient(135deg,#f59e0b,#b45309)}
.open:disabled{opacity:.45}
.legend{margin:14px 16px 0;font-size:12px;color:var(--muted);line-height:1.7}
#toast{position:fixed;left:14px;right:14px;bottom:18px;background:#232838;color:#fff;border-radius:12px;padding:14px 16px;font-size:14px;transform:translateY(150%);transition:.26s;z-index:9}
#toast.on{transform:translateY(0)}
#toast.bad{background:#b91c1c}
</style>
</head>
<body>
<header><h1>📦 Кейсы</h1><div class="wallet">📦 <span id="cases">…</span></div></header>
<main>
  <div class="reelwrap"><div class="marker"></div><div class="reel" id="reel"></div></div>
  <div class="result" id="result">Жми «Открыть кейс» — лента закрутится.</div>
  <button class="open" id="open">Открыть кейс</button>
  <div class="legend">
    Шансы кейса: 🟣 эпик 60% · 🔴 миф 28% · 🟡 легенда 8% · ⚫ секрет 1.5% · 💎 ультима 1.5% · 🌈 ульта 1%.
    Внутри редкости все карты равновероятны.
  </div>
</main>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type":"application/json"};
let pool = [], cases = 0, spinning = false, filled = false;
const TILE = 96, GAP = 8, STEP = TILE + GAP;
const reel = document.getElementById("reel");
const result = document.getElementById("result");
const openBtn = document.getElementById("open");
function money(n){ return String(Math.round(Number(n)||0)).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
function toast(t,k){ var el=document.getElementById("toast"); el.textContent=t; el.className="on "+(k||""); clearTimeout(el._t); el._t=setTimeout(function(){el.className="";},3200); }
function tile(card){
  var c = card.color || "#334155";
  return '<div class="tile" style="border-color:'+c+'">'+
    '<div class="emoji">'+card.emoji+'</div>'+
    '<div class="tname">'+card.name+'</div>'+
    '<div class="tpoints">'+money(card.points)+'</div></div>';
}
function randomCard(){ return pool[Math.floor(Math.random()*pool.length)] || {name:"?",emoji:"?",points:0,color:"#334155"}; }
function fillReel(win){
  var n = 60, target = 54, html = "";
  for(var i=0;i<n;i++){ html += tile(i===target && win ? win : randomCard()); }
  reel.innerHTML = html;
  return target;
}
function spinTo(target){
  var center = window.innerWidth / 2;
  var jitter = (Math.random()*40) - 20;
  var offset = target*STEP + TILE/2 - center + jitter;
  reel.style.transition = "transform 5s cubic-bezier(.12,.72,.06,1)";
  reel.style.transform = "translateX(" + (-offset) + "px)";
}
async function open(){
  if(spinning) return;
  spinning = true; openBtn.disabled = true;
  result.textContent = "Крутим...";
  try{
    var r = await fetch("/api/case/open", {method:"POST", headers, body:"{}"});
    var d = await r.json();
    if(d.error){ toast(d.error,"bad"); spinning=false; openBtn.disabled = cases<=0; return; }
    var target = fillReel(d.card);
    reel.style.transition = "none"; reel.style.transform = "translateX(0)";
    void reel.offsetWidth;
    spinTo(target);
    cases = d.cases;
    document.getElementById("cases").textContent = cases;
    setTimeout(function(){
      result.innerHTML = "\uD83C\uDF89 <b>"+d.card.name+"</b> \u00b7 "+d.card.rarity_title+
        " \u00b7 +"+money(d.card.points)+" \u043e\u0447\u043a." + (d.is_new ? " \u00b7 <b>\u041d\u041e\u0412\u0410\u042f!</b>" : "");
      spinning = false;
      openBtn.disabled = cases <= 0;
      if(cases <= 0) openBtn.textContent = "\u041a\u0435\u0439\u0441\u043e\u0432 \u0431\u043e\u043b\u044c\u0448\u0435 \u043d\u0435\u0442";
    }, 5200);
  }catch(e){ toast("\u0421\u0432\u044f\u0437\u044c \u043f\u043e\u0442\u0435\u0440\u044f\u043b\u0430\u0441\u044c","bad"); spinning=false; openBtn.disabled=cases<=0; }
}
async function load(){
  try{
    var r = await fetch("/api/case", {headers});
    var d = await r.json();
    if(d.error){ result.textContent = d.error; return; }
    pool = d.pool || []; cases = d.cases || 0;
    document.getElementById("cases").textContent = cases;
    if(!filled){ fillReel(null); filled = true; }
    openBtn.disabled = cases <= 0;
    if(cases <= 0) openBtn.textContent = "\u041a\u0435\u0439\u0441\u043e\u0432 \u043d\u0435\u0442 \u2014 \u043a\u0440\u0443\u0442\u0438 \u0440\u0443\u043b\u0435\u0442\u043a\u0443";
  }catch(e){ result.textContent = "\u041d\u0435 \u0441\u043c\u043e\u0433 \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u043a\u0435\u0439\u0441\u044b"; }
}
openBtn.onclick = open;
if(tg){ tg.ready(); tg.expand(); }
load();
</script>
</body>
</html>
"""


ROULETTE_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Северо-Юг · Рулетка</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--bg:#0f1117;--card:#171a23;--line:#252a38;--ink:#e8ebf2;--muted:#8b93a7}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--ink);min-height:100vh;padding-bottom:110px}
header{position:sticky;top:0;z-index:5;background:rgba(15,17,23,.94);border-bottom:1px solid var(--line);padding:14px 16px;display:flex;align-items:baseline;justify-content:space-between}
h1{margin:0;font-size:19px}
.wallet{font-weight:700;font-size:15px;background:#1e2140;color:#c7c9ff;border-radius:999px;padding:7px 14px}
main{padding:18px 16px 0;display:flex;flex-direction:column;align-items:center}
.stage{position:relative;display:inline-block;padding-top:14px}
.pointer{position:absolute;left:50%;top:0;transform:translateX(-50%);width:0;height:0;border-left:10px solid transparent;border-right:10px solid transparent;border-top:18px solid #f59e0b;z-index:4;filter:drop-shadow(0 0 6px #f59e0b)}
canvas{display:block;border-radius:50%;box-shadow:0 0 0 4px #1b1f2b, 0 10px 30px rgba(0,0,0,.5)}
.result{margin-top:18px;width:100%;padding:14px;border-radius:14px;background:var(--card);border:1px solid var(--line);font-size:15px;line-height:1.5;min-height:56px;display:flex;align-items:center;justify-content:center;text-align:center}
.sp{display:flex;justify-content:space-between;width:100%;margin-top:10px;font-size:13px;color:var(--muted)}
.spin{margin-top:16px;width:100%;border:0;border-radius:14px;padding:16px;font-size:16px;font-weight:700;color:#fff;background:linear-gradient(135deg,#dc2626,#7f1d1d)}
.spin:disabled{opacity:.45}
#toast{position:fixed;left:14px;right:14px;bottom:18px;background:#232838;color:#fff;border-radius:12px;padding:14px 16px;font-size:14px;transform:translateY(150%);transition:.26s;z-index:9}
#toast.on{transform:translateY(0)}
#toast.bad{background:#b91c1c}
</style>
</head>
<body>
<header><h1>🎡 Рулетка</h1><div class="wallet">🎟 <span id="spins">…</span></div></header>
<main>
  <div class="stage"><div class="pointer"></div><canvas id="wheel"></canvas></div>
  <div class="result" id="result">Жми «Крутить» — колесо завертится.</div>
  <div class="sp"><span>Баланс: <b id="balance">…</b></span><span id="reset"></span></div>
  <button class="spin" id="spin">Крутить</button>
</main>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type":"application/json"};
let segments = [], currentRot = 0, spinning = false, spinsLeft = 0;
const canvas = document.getElementById("wheel");
const result = document.getElementById("result");
const spinBtn = document.getElementById("spin");
function money(n){ return String(Math.round(Number(n)||0)).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
function toast(t,k){ var el=document.getElementById("toast"); el.textContent=t; el.className="on "+(k||""); clearTimeout(el._t); el._t=setTimeout(function(){el.className="";},3200); }
function draw(segs){
  var size = Math.min(300, window.innerWidth - 80);
  var dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(size*dpr); canvas.height = Math.round(size*dpr);
  canvas.style.width = size+"px"; canvas.style.height = size+"px";
  var ctx = canvas.getContext("2d");
  ctx.setTransform(dpr,0,0,dpr,0,0);
  var cx = size/2, cy = size/2, R = size/2 - 3;
  var angle = -Math.PI/2;
  segs.forEach(function(s){
    var a = s.angle * Math.PI/180;
    ctx.beginPath(); ctx.moveTo(cx,cy); ctx.arc(cx,cy,R,angle,angle+a); ctx.closePath();
    ctx.fillStyle = s.color; ctx.fill();
    ctx.strokeStyle = "rgba(0,0,0,.4)"; ctx.lineWidth = 1; ctx.stroke();
    ctx.save(); ctx.translate(cx,cy); ctx.rotate(angle + a/2);
    ctx.textAlign = "right"; ctx.textBaseline = "middle";
    ctx.fillStyle = "#fff"; ctx.font = "bold 11px sans-serif";
    ctx.fillText(s.label, R - 10, 0);
    ctx.restore();
    angle += a;
  });
  ctx.beginPath(); ctx.arc(cx,cy,11,0,Math.PI*2); ctx.fillStyle="#0f1117"; ctx.fill();
  ctx.strokeStyle="#f59e0b"; ctx.lineWidth=2; ctx.stroke();
}
function prep(segs){
  var acc = 0;
  segs.forEach(function(s){ s.start = acc; s.mid = acc + s.angle/2; acc += s.angle; });
  segments = segs;
  draw(segs);
}
function spinTo(index){
  var mid = segments[index] ? segments[index].mid : 0;
  var want = (360 - mid) % 360;
  var cur = ((currentRot % 360) + 360) % 360;
  var delta = (want - cur + 360) % 360;
  var turns = 6 + Math.floor(Math.random()*3);
  currentRot += turns*360 + delta;
  canvas.style.transition = "transform 5.5s cubic-bezier(.14,.74,.06,1)";
  canvas.style.transform = "rotate(" + currentRot + "deg)";
}
async function spin(){
  if(spinning) return;
  spinning = true; spinBtn.disabled = true;
  result.textContent = "Крутим...";
  try{
    var r = await fetch("/api/roulette/spin", {method:"POST", headers, body:"{}"});
    var d = await r.json();
    if(d.error){ toast(d.error,"bad"); spinning=false; spinBtn.disabled=spinsLeft<=0; return; }
    spinTo(d.index);
    setTimeout(function(){
      result.innerHTML = d.prize_label;
      spinsLeft = d.spins_left;
      document.getElementById("spins").textContent = spinsLeft;
      document.getElementById("balance").textContent = money(d.balance);
      spinning = false;
      spinBtn.disabled = spinsLeft <= 0;
      if(spinsLeft <= 0) spinBtn.textContent = "\u0421\u043f\u0438\u043d\u044b \u043a\u043e\u043d\u0447\u0438\u043b\u0438\u0441\u044c";
    }, 5700);
  }catch(e){ toast("\u0421\u0432\u044f\u0437\u044c \u043f\u043e\u0442\u0435\u0440\u044f\u043b\u0430\u0441\u044c","bad"); spinning=false; spinBtn.disabled=spinsLeft<=0; }
}
async function load(){
  try{
    var r = await fetch("/api/roulette", {headers});
    var d = await r.json();
    if(d.error){ result.textContent = d.error; return; }
    prep(d.segments || []);
    spinsLeft = d.spins_left || 0;
    document.getElementById("spins").textContent = spinsLeft;
    document.getElementById("balance").textContent = money(d.balance);
    document.getElementById("reset").textContent = d.reset_text || "";
    spinBtn.disabled = spinsLeft <= 0;
    if(spinsLeft <= 0) spinBtn.textContent = "\u0421\u043f\u0438\u043d\u044b \u043a\u043e\u043d\u0447\u0438\u043b\u0438\u0441\u044c";
  }catch(e){ result.textContent = "\u041d\u0435 \u0441\u043c\u043e\u0433 \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0440\u0443\u043b\u0435\u0442\u043a\u0443"; }
}
spinBtn.onclick = spin;
if(tg){ tg.ready(); tg.expand(); }
load();
</script>
</body>
</html>
"""