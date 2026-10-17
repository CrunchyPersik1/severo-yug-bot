

@router.get("/roulette_table", response_class=HTMLResponse)
async def roulette_table_page() -> HTMLResponse:
    return HTMLResponse(inject(ROULETTE_TABLE_PAGE))


ROULETTE_TABLE_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>Северо-Юг · Рулетка</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--red:#c0392b;--black:#17181c;--green:#1e8a4c;--up:#3fae6a;--down:#d8434a}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;overscroll-behavior:none}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--ink);min-height:100vh;padding:14px 0 26px}
.wrap{max-width:520px;margin:0 auto;padding:0 14px}
.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.head .b{background:var(--panel);border:1px solid var(--line);border-radius:999px;
  padding:8px 14px;font-size:13px;font-weight:800}
.head .b.bal{color:var(--acc2)}

.stage{display:flex;justify-content:center;margin:6px 0 10px}
.rw{position:relative;width:330px;height:330px;max-width:88vw;max-height:88vw;
  border-radius:50%;padding:11px;
  background:linear-gradient(160deg,#3a2d1e,#1a1410 55%,#2a2016);
  box-shadow:0 18px 44px rgba(0,0,0,.55),inset 0 1px 0 rgba(255,255,255,.09)}
.wheel{position:absolute;inset:11px;border-radius:50%;
  transition:transform 6.4s cubic-bezier(.08,.6,.03,1);
  box-shadow:inset 0 0 0 4px #241c14,inset 0 0 34px rgba(0,0,0,.7)}
.num{position:absolute;top:50%;left:50%;width:18px;height:18px;margin:-9px 0 0 -9px;
  font-size:9.5px;font-weight:900;color:#fff;display:flex;align-items:center;justify-content:center;
  text-shadow:0 1px 2px rgba(0,0,0,.8)}
.ballwrap{position:absolute;inset:11px;pointer-events:none;
  transition:transform 6.9s cubic-bezier(.11,.55,.05,1);z-index:6}
.ball{position:absolute;top:3px;left:50%;width:17px;height:17px;margin-left:-8.5px;border-radius:50%;
  background:radial-gradient(circle at 34% 28%,#ffffff,#c3c8d0 60%,#8b9099);
  box-shadow:0 3px 9px rgba(0,0,0,.75),inset -2px -2px 4px rgba(0,0,0,.25)}
.hub{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
  width:36%;height:36%;border-radius:50%;z-index:5;
  background:radial-gradient(circle at 50% 26%,var(--panel2),var(--panel));
  border:1px solid var(--line);display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:2px;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.07),0 8px 22px rgba(0,0,0,.5)}
.hub .n{font-size:36px;font-weight:900;letter-spacing:-1.5px;line-height:1}
.hub .c{font-size:10px;letter-spacing:1.4px;text-transform:uppercase;font-weight:800;color:var(--muted)}

.res{text-align:center;font-size:15px;font-weight:900;min-height:22px;letter-spacing:.3px}
.res.win{color:var(--up)} .res.lose{color:var(--down)}
.prev{display:flex;gap:5px;overflow-x:auto;justify-content:flex-start;margin:9px 0 4px;
  scrollbar-width:none;min-height:26px}
.prev::-webkit-scrollbar{display:none}
.prev b{flex:0 0 auto;width:26px;height:26px;border-radius:8px;display:flex;align-items:center;
  justify-content:center;font-size:11px;font-weight:900;color:#fff}

.block{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px;margin-bottom:11px}
.block .t{font-size:10.5px;letter-spacing:1.3px;text-transform:uppercase;color:var(--muted);font-weight:800;margin-bottom:9px}
.bets{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}
.ch{border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:11px;
  padding:12px 6px;font-size:13px;font-weight:800;line-height:1.25}
.ch small{display:block;font-size:10px;font-weight:700;opacity:.7;margin-top:2px}
.ch.on{border-color:var(--acc);background:var(--panel2);box-shadow:0 0 0 1px var(--acc) inset}
.ch.r{color:#ef6a5a} .ch.b{color:#cfd4dc} .ch.g{color:#4fc98a}
.bets4{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}
.bt{border:1px solid var(--line);background:transparent;color:var(--muted);border-radius:11px;
  padding:11px 4px;font-size:13px;font-weight:800}
.bt.on{background:var(--acc);color:var(--acc-ink);border-color:transparent}
.custom{display:flex;gap:7px;margin-top:8px}
.custom input{flex:1;background:var(--panel2);border:1px solid var(--line);border-radius:11px;
  color:var(--ink);padding:11px 13px;font-size:15px;font-weight:800;font-family:inherit}
.custom button{border:1px solid var(--line);background:transparent;color:var(--muted);
  border-radius:11px;padding:0 16px;font-size:13px;font-weight:800}
.go{width:100%;border:0;border-radius:15px;padding:18px;font-size:17px;font-weight:900;
  letter-spacing:1px;color:var(--acc-ink);background:var(--acc)}
.go[disabled]{background:var(--panel2);color:var(--muted)}
#toast{position:fixed;left:14px;right:14px;bottom:16px;background:var(--panel2);color:var(--ink);
  border:1px solid var(--line);border-radius:12px;padding:13px 15px;font-size:13px;
  transform:translateY(220%);transition:.25s;z-index:30}
#toast.on{transform:translateY(0)}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div class="b bal" id="bal">…</div>
    <div class="b" id="spins">…</div>
  </div>

  <div class="stage">
    <div class="rw">
      <div class="wheel" id="wheel"></div>
      <div class="ballwrap" id="ballwrap"><span class="ball"></span></div>
      <div class="hub"><div class="n" id="hubNum">—</div><div class="c" id="hubCol">крути</div></div>
    </div>
  </div>

  <div class="res" id="res">Выбери ставку и крути</div>
  <div class="prev" id="prev"></div>

  <div class="block">
    <div class="t">На что ставим</div>
    <div class="bets" id="bets"></div>
  </div>

  <div class="block">
    <div class="t">Ставка</div>
    <div class="bets4" id="bets4"></div>
    <div class="custom">
      <input id="betInput" type="number" inputmode="numeric" placeholder="своя сумма">
      <button id="betSet">ОК</button>
    </div>
  </div>

  <button class="go" id="go" disabled>КРУТИТЬ</button>
</div>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type": "application/json"};
const PRESETS = [100, 500, 1000, 5000];
const TONE = {green: "#1e8a4c", red: "#c0392b", black: "#17181c"};
let S = {data: null, kind: "red", bet: 500, busy: false, rot: 0, ballRot: 0, last: []};

function esc(s){ return String(s).replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c])); }
function money(n){ return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
function toast(t){
  const el = document.getElementById("toast");
  el.textContent = t; el.className = "on";
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "", 3000);
}
function colorOf(n, red){ return n === 0 ? "green" : (red.indexOf(n) >= 0 ? "red" : "black"); }

// Колесо: conic-gradient по порядку лунок + подписи чисел
function buildWheel(){
  const order = S.data.order, red = S.data.red;
  const step = 360 / order.length;
  const stops = order.map((n, i) =>
    TONE[colorOf(n, red)] + " " + (i * step).toFixed(3) + "deg " + ((i + 1) * step).toFixed(3) + "deg");
  const w = document.getElementById("wheel");
  w.style.background = "conic-gradient(from 0deg, " + stops.join(",") + ")";
  w.innerHTML = order.map((n, i) => {
    const a = i * step + step / 2;
    return '<span class="num" style="transform:rotate(' + a + 'deg) translateY(-118px) rotate(' +
      (-a) + 'deg)">' + n + '</span>';
  }).join("");
}
function render(){
  const d = S.data;
  document.getElementById("bal").textContent = "Баланс " + money(d.me.balance);
  document.getElementById("spins").textContent = "Круток " + d.me.left + "/" + d.me.cap;
  document.getElementById("bets").innerHTML = d.bets.map(b =>
    '<button class="ch ' + (b.tone === "red" ? "r" : b.tone === "black" ? "b" : b.tone === "green" ? "g" : "") +
    (b.id === S.kind ? " on" : "") + '" data-k="' + b.id + '">' + esc(b.title) +
    '<small>×' + b.mult + '</small></button>').join("");
  document.getElementById("bets4").innerHTML = PRESETS.map(b =>
    '<button class="bt' + (S.bet === b ? " on" : "") + '" data-b="' + b + '">' + money(b) + '</button>').join("");
  document.getElementById("go").disabled = S.busy;
  document.querySelectorAll("[data-k]").forEach(el => el.onclick = () => { S.kind = el.dataset.k; render(); });
  document.querySelectorAll("[data-b]").forEach(el => el.onclick = () => {
    S.bet = +el.dataset.b; document.getElementById("betInput").value = ""; render();
  });
  document.getElementById("prev").innerHTML = S.last.map(n => {
    const c = colorOf(n, S.data.red);
    return '<b style="background:' + TONE[c] + ';border:1px solid rgba(255,255,255,.15)">' + n + '</b>';
  }).join("");
}
function spinTo(index){
  const count = S.data.order.length;
  const step = 360 / count;
  const target = -(index * step + step / 2) + (Math.random() - 0.5) * step * 0.45;
  const need = (((target - (S.rot % 360)) % 360) + 360) % 360;
  S.rot += 360 * 6 + need;
  S.ballRot -= 360 * 11;
  document.getElementById("wheel").style.transform = "rotate(" + S.rot + "deg)";
  document.getElementById("ballwrap").style.transform = "rotate(" + S.ballRot + "deg)";
}
async function spin(){
  if (S.busy) return;
  S.busy = true; render();
  document.getElementById("res").textContent = "Шарик пошёл…";
  document.getElementById("res").className = "res";
  try{
    const r = await fetch("/api/roulette_table/spin", {method:"POST", headers,
      body: JSON.stringify({bet_type: S.kind, bet: S.bet})});
    const d = await r.json();
    if (d.error){ toast(d.error); S.busy = false; render(); return; }
    const index = S.data.order.indexOf(d.number);
    spinTo(index < 0 ? 0 : index);
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("medium");
    await new Promise(res => setTimeout(res, 7000));
    document.getElementById("hubNum").textContent = d.number;
    document.getElementById("hubCol").textContent = d.color === "red" ? "красное"
      : (d.color === "black" ? "чёрное" : "зелёное");
    document.getElementById("res").textContent = d.won
      ? "ВЫИГРЫШ +" + money(d.payout) + " · " + d.title
      : "ПРОИГРЫШ −" + money(d.bet) + " · " + d.title;
    document.getElementById("res").className = "res " + (d.won ? "win" : "lose");
    S.data.me.balance = d.balance; S.data.me.left = d.left;
    S.last = [d.number].concat(S.last).slice(0, 14);
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred(d.won ? "success" : "error");
  }catch(e){
    toast("Связь потерялась");
  }
  S.busy = false; render();
}
document.getElementById("go").onclick = spin;
document.getElementById("betSet").onclick = () => {
  const v = parseInt(document.getElementById("betInput").value, 10);
  const lim = S.data.limits;
  if (!v || v < lim.min || v > lim.max){ toast("Ставка от " + money(lim.min) + " до " + money(lim.max)); return; }
  S.bet = v; render();
};
if(tg){ tg.ready(); tg.expand(); }
(async () => {
  try{
    const r = await fetch("/api/roulette_table", {headers});
    const d = await r.json();
    if (d.error){ toast(d.error); return; }
    S.data = d; buildWheel(); render();
  }catch(e){ toast("Не смог загрузить"); }
})();
</script>
</body>
</html>
"""
