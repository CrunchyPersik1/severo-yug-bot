CASE_PAGE = r"""<!doctype html>
"""
CASE_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>Северо-Юг · Кейсы</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:#0f1117;color:#e8ebf2;min-height:100vh;padding-bottom:100px}
header{position:sticky;top:0;z-index:5;background:rgba(15,17,23,.94);
  border-bottom:1px solid #252a38;padding:14px 16px;display:flex;
  align-items:baseline;justify-content:space-between}
h1{margin:0;font-size:19px}
.wallet{font-weight:700;font-size:15px;background:#1e2140;color:#c7c9ff;
  border-radius:999px;padding:7px 14px}
main{padding:16px 0 0}
.pick{display:flex;gap:10px;margin:0 16px}
.ptile{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;
  background:#1b1f2b;border:2px solid #334155;border-radius:15px;padding:16px 8px;
  color:#e8ebf2;font-family:inherit;transition:.15s}
.ptile:active{transform:scale(.97)}
.ptile.on{border-color:#f59e0b;background:#26233a}
.ptile .pe{font-size:27px;line-height:1}
.ptile .pn{font-size:13.5px;font-weight:800}
.ptile .pc{font-size:11.5px;color:#8b93a7}
.ptile.on .pc{color:#f6c94a}
.hint{margin:14px 16px 0;font-size:12.5px;color:#8b93a7;text-align:center;line-height:1.5}
#play{display:none;margin-top:14px}
.reelwrap{position:relative;overflow:hidden;padding:14px 0;background:#12141c;
  border-top:1px solid #252a38;border-bottom:1px solid #252a38;--tw:96px;--th:118px}
.reelwrap.mini{padding:5px 0;--tw:62px;--th:74px}
.reelwrap.mini + .reelwrap.mini{border-top:0}
.reel{display:flex;gap:8px;will-change:transform}
.tile{flex:0 0 var(--tw);width:var(--tw);height:var(--th);border-radius:12px;
  background:#1b1f2b;border:2px solid #334155;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:4px;overflow:hidden}
.tile .emoji{font-size:calc(var(--tw)*.27);line-height:1}
.tile .tname{font-size:11px;text-align:center;padding:0 4px;color:#e5e7eb;
  max-height:28px;overflow:hidden}
.tile .tpoints{font-size:11px;color:#8b93a7}
.reelwrap.mini .tile{border-radius:9px;gap:2px}
.reelwrap.mini .tile .tname{font-size:7.5px;max-height:18px;padding:0 2px;line-height:1.15}
.reelwrap.mini .tile .tpoints{font-size:8px}
.marker{position:absolute;left:50%;top:0;bottom:0;width:2px;background:#f59e0b;
  box-shadow:0 0 12px #f59e0b;z-index:3}
.result{margin:16px;padding:14px;border-radius:14px;background:#171a23;
  border:1px solid #252a38;font-size:14px;line-height:1.6;min-height:56px;
  display:flex;align-items:center;justify-content:center;text-align:center}
.howmany{display:flex;gap:8px;margin:12px 16px 0}
.howmany button{flex:1;border:1px solid #252a38;background:transparent;color:#8b93a7;
  border-radius:11px;padding:11px 0;font-size:13px;font-weight:800;font-family:inherit}
.howmany button.on{background:#f59e0b;color:#1a1205;border-color:transparent}
.open{margin:12px 16px 0;width:calc(100% - 32px);border:0;border-radius:14px;
  padding:16px;font-size:16px;font-weight:800;color:#fff;
  background:linear-gradient(135deg,#f59e0b,#b45309);font-family:inherit}
.open:disabled{opacity:.45}
.legend{margin:14px 16px 0;font-size:12px;color:#8b93a7;line-height:1.7}
#toast{position:fixed;left:14px;right:14px;bottom:18px;background:#232838;color:#fff;
  border-radius:12px;padding:14px 16px;font-size:14px;transform:translateY(150%);
  transition:.26s;z-index:9}
#toast.on{transform:translateY(0)}
#toast.bad{background:#b91c1c}
</style>
</head>
<body>
<header><h1>📦 Кейсы</h1><div class="wallet">📦 <span id="total">…</span></div></header>
<main>
  <div class="pick" id="pick">
    <button class="ptile" data-k="g">
      <span class="pe">🧩</span><span class="pn">7Г класс</span>
      <span class="pc" id="cntG">…</span>
    </button>
    <button class="ptile" data-k="d">
      <span class="pe">🏫</span><span class="pn">7Д класс</span>
      <span class="pc" id="cntD">…</span>
    </button>
  </div>
  <div class="hint" id="hint">Выбери кейс — потом откроется лента</div>

  <div id="play">
    <div id="reels"><div class="reelwrap"><div class="marker"></div><div class="reel"></div></div></div>
    <div class="result" id="result">Жми «Открыть кейс» — лента закрутится.</div>
    <div class="howmany" id="howmany">
      <button data-n="1" class="on">1</button>
      <button data-n="3">3</button>
      <button data-n="5">5</button>
      <button data-n="10">10</button>
    </div>
    <button class="open" id="open" disabled>Сначала выбери кейс</button>
  </div>

  <div class="legend">
    🧩 <b>7Г</b> — обычная коллекция. 🏫 <b>7Д</b> — второй класс, только из кейса
    и слова «западо-восток». Шансы сверху редкости низкие.
  </div>
</main>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type": "application/json"};
const GAP = 8;
let pool = [], poolD = [], countG = 0, countD = 0;
let kind = null, howMany = 1, spinning = false;
const reels = document.getElementById("reels");
const result = document.getElementById("result");
const openBtn = document.getElementById("open");
const hint = document.getElementById("hint");

function money(n){
  return String(Math.round(Number(n) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}
function toast(t, k){
  const el = document.getElementById("toast");
  el.textContent = t; el.className = "on " + (k || "");
  clearTimeout(el._t); el._t = setTimeout(function(){ el.className = ""; }, 3200);
}
function tile(card){
  const c = card.color || "#334155";
  return '<div class="tile" style="border-color:' + c + '">' +
    '<div class="emoji">' + card.emoji + '</div>' +
    '<div class="tname">' + card.name + '</div>' +
    '<div class="tpoints">' + money(card.price || card.points) + '</div></div>';
}
function source(){ return kind === "d" ? poolD : pool; }
function left(){ return kind === "d" ? countD : countG; }
function randomOf(src){
  return src[Math.floor(Math.random() * src.length)] ||
    {name: "?", emoji: "?", points: 0, price: 0, color: "#334155"};
}
function makeReel(win, mini, src){
  const wrap = document.createElement("div");
  wrap.className = "reelwrap" + (mini ? " mini" : "");
  const marker = document.createElement("div");
  marker.className = "marker";
  const el = document.createElement("div");
  el.className = "reel";
  wrap.appendChild(marker);
  wrap.appendChild(el);
  reels.appendChild(wrap);
  const tw = mini ? 62 : 96;
  const total = mini ? 34 : 60;
  const target = mini ? 28 : 54;
  let html = "";
  for (let i = 0; i < total; i++) {
    html += tile(i === target && win ? win : randomOf(src));
  }
  el.innerHTML = html;
  return {el: el, target: target, step: tw + GAP, tw: tw};
}
function spinOne(item){
  const center = window.innerWidth / 2;
  const jitter = (Math.random() * 40) - 20;
  const offset = item.target * item.step + item.tw / 2 - center + jitter;
  setTimeout(function(){
    item.el.style.transition = "transform 4.2s cubic-bezier(.12,.72,.06,1)";
    item.el.style.transform = "translateX(" + (-offset) + "px)";
  }, 30);
}
function sync(){
  const l = left();
  openBtn.disabled = spinning || !kind || l <= 0;
  openBtn.textContent = !kind ? "Сначала выбери кейс"
    : l <= 0 ? (kind === "d" ? "Кейсов 7Д нет" : "Кейсов 7Г нет")
    : (howMany > 1 ? "Открыть " + howMany + " кейсов" : "Открыть кейс");
}
function updateCounts(g, d){
  countG = g; countD = d;
  document.getElementById("cntG").textContent = g + " шт.";
  document.getElementById("cntD").textContent = d + " шт.";
  document.getElementById("total").textContent = g + d;
  sync();
}
function choose(k){
  if (spinning) return;
  kind = k;
  document.querySelectorAll("#pick [data-k]").forEach(function(x){
    x.className = "ptile" + (x.dataset.k === k ? " on" : "");
  });
  document.getElementById("play").style.display = "block";
  hint.style.display = "none";
  reels.innerHTML = "";
  makeReel(null, false, source());
  sync();
}
async function open(){
  if (spinning || !kind) return;
  spinning = true; sync();
  result.textContent = "Крутим…";
  try{
    const r = await fetch("/api/case/open_many", {
      method: "POST", headers,
      body: JSON.stringify({count: howMany, kind: kind}),
    });
    const d = await r.json();
    if (d.error){ toast(d.error, "bad"); spinning = false; sync(); return; }
    reels.innerHTML = "";
    const mini = d.cards.length > 1;
    const src = source();
    const items = d.cards.map(function(c){ return makeReel(c, mini, src); });
    void reels.offsetWidth;
    items.forEach(spinOne);
    updateCounts(d.count_g || 0, d.count_d || 0);
    setTimeout(function(){
      result.innerHTML = d.cards.map(function(c){
        return "🎉 <b>" + c.name + "</b> · " + c.rarity_title +
          " · +" + money(c.points) + " очк." +
          (c.is_new ? " · <b>НОВАЯ!</b>" : "");
      }).join("<br>");
      spinning = false;
      sync();
    }, 4600);
  }catch(e){
    toast("Связь потерялась", "bad");
    spinning = false; sync();
  }
}
async function load(){
  try{
    const r = await fetch("/api/case", {headers});
    const d = await r.json();
    if (d.error){ hint.textContent = d.error; return; }
    pool = d.pool || [];
    poolD = d.pool_d || [];
    updateCounts(d.count_g || 0, d.count_d || 0);
  }catch(e){
    hint.textContent = "Не смог загрузить кейсы";
  }
}
document.querySelectorAll("#pick [data-k]").forEach(function(b){
  b.onclick = function(){ choose(b.dataset.k); };
});
document.querySelectorAll("#howmany [data-n]").forEach(function(b){
  b.onclick = function(){
    if (spinning) return;
    howMany = parseInt(b.dataset.n, 10) || 1;
    document.querySelectorAll("#howmany [data-n]").forEach(function(x){
      x.className = x === b ? "on" : "";
    });
    sync();
  };
});
openBtn.onclick = open;
if (tg){ tg.ready(); tg.expand(); }
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
