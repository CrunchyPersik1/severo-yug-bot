
"""Страница Северо-Пасса: сезон, шкала, дорожки наград и квесты дня."""

from __future__ import annotations

PASS_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>Северо-Пасс</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{
  --bg:#0d1020; --panel:#161a30; --panel2:#1e2340; --line:#2b3050;
  --ink:#f2f0ff; --muted:#9aa0c4; --gold:#f6c94a; --acc:#7c5cff; --acc2:#31d0aa;
  --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --r-1:12px; --r-2:18px;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{width:100%;max-width:100vw;overflow-x:hidden}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding-bottom:90px}
.top{position:sticky;top:0;z-index:5;padding:12px 16px;display:flex;align-items:center;flex-wrap:wrap;
  justify-content:space-between;gap:10px;background:rgba(13,16,32,.94);
  border-bottom:1px solid var(--line);backdrop-filter:blur(10px)}
.top h1{margin:0;font-size:13px;letter-spacing:1.4px;text-transform:uppercase;color:var(--muted)}
.season{font-size:11px;color:var(--gold);font-weight:800;max-width:60%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-left:auto}
.wrap{width:100%;max-width:560px;margin:0 auto;padding:14px;overflow:hidden}
.hero{min-width:0;border-radius:var(--r-2);padding:16px;margin-bottom:14px;
  background:linear-gradient(135deg,#221a3f,#111528 65%);
  border:1px solid #3a2f66;position:relative;overflow:hidden}
.hero::after{content:"";position:absolute;inset:-40% -10% auto;height:140%;
  background:radial-gradient(circle at 30% 20%,rgba(246,201,74,.18),transparent 60%);
  pointer-events:none}
.hero .name{font-size:18px;font-weight:900;line-height:1.25}
.hero .sub{margin-top:5px;font-size:12px;color:var(--muted)}
.hero .timer{margin-top:10px;font-size:12px;color:var(--gold);font-weight:800}
.bar{margin-top:12px;height:12px;border-radius:7px;background:rgba(255,255,255,.12);overflow:hidden}
.bar i{display:block;height:100%;border-radius:7px;
  background:linear-gradient(90deg,var(--acc2),var(--gold));transition:width .3s}
.rowxp{display:flex;justify-content:space-between;margin-top:7px;font-size:12px;
  color:var(--muted);font-variant-numeric:tabular-nums}
.lvl{font-size:22px;font-weight:900;color:var(--gold)}
.buys{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.buys button{flex:1 1 45%;min-width:130px;border:0;border-radius:var(--r-1);padding:12px;
  font-family:inherit;font-size:13px;font-weight:900;background:var(--acc);color:#fff}
.buys button.alt{background:linear-gradient(135deg,#f6c94a,#c98a1a);color:#241a03}
.buys button:disabled{background:var(--panel2);color:var(--muted)}
.section{margin-top:18px}
.section h2{margin:0 0 8px;font-size:12px;letter-spacing:1.3px;text-transform:uppercase;
  color:var(--muted)}
.quest{border-radius:var(--r-1);background:var(--panel);border:1px solid var(--line);
  padding:12px;margin-bottom:8px}
.quest.done{border-color:#3f7a4f;background:#152418}
.quest .qt{display:flex;justify-content:space-between;gap:10px;font-size:13.5px;font-weight:800}
.quest .qm{margin-top:6px;font-size:12px;color:var(--muted);display:flex;
  justify-content:space-between;gap:8px}
.quest button{margin-top:10px;width:100%;border:0;border-radius:10px;padding:10px;
  font-family:inherit;font-weight:900;font-size:13px;background:var(--acc2);color:#07231c}
.quest button:disabled{background:var(--panel2);color:var(--muted)}
.quest .plus{color:var(--gold);font-weight:900;font-size:11px}
.track{display:flex;gap:6px;align-items:stretch;margin-bottom:8px;overflow:hidden}
.level{width:44px;flex:0 0 44px;border-radius:10px;background:var(--panel2);
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  font-weight:900;font-size:13px;color:var(--muted);border:1px solid var(--line)}
.level.open{color:var(--gold);border-color:#5c4a1a;background:#241d0c}
.cell{flex:1;min-width:0;overflow:hidden;border-radius:10px;background:var(--panel);border:1px solid var(--line);
  padding:9px;font-size:11.5px;line-height:1.35;min-height:54px}
.cell.plus{border-color:#4a3f8a;background:#1b1a35}
.cell.prem{border-color:#8a5a1a;background:#2a1f0d}
.cell.locked{opacity:.45}
.cell button{margin-top:6px;width:100%;border:0;border-radius:8px;padding:6px;
  font-family:inherit;font-size:11px;font-weight:900;background:var(--acc2);color:#07231c}
.cell button:disabled{background:var(--panel2);color:var(--muted)}
.toast{position:fixed;left:12px;right:12px;bottom:16px;padding:12px 14px;border-radius:12px;
  background:#241a3f;border:1px solid #4a3f8a;font-size:13px;font-weight:700;
  transform:translateY(140%);transition:transform .25s;z-index:20}
.toast.on{transform:translateY(0)}
.small{font-size:11px;color:var(--muted)}
</style>
</head>
<body>
<div class="top">
  <h1>Северо-Пасс</h1>
  <div class="season" id="seasonName">—</div>
</div>
<div class="wrap">
  <div class="hero">
    <div class="name" id="heroName">Академия Северо-Южных</div>
    <div class="sub" id="heroSub">Сезонный пропуск</div>
    <div class="timer" id="timer">—</div>
    <div class="bar"><i id="xpFill" style="width:0%"></i></div>
    <div class="rowxp"><span id="xpText">0 / 0</span><span class="lvl" id="lvlText">0 ур.</span></div>
    <div class="buys" id="buys"></div>
  </div>

  <div class="section" id="styleBox" style="display:none">
    <h2>Стиль сезона</h2>
    <div class="quest">
      <div class="qt"><span>Геймерский</span><span class="plus">ПАСС++</span></div>
      <div class="qm"><span>Чёрный терминал, жёлтый акцент</span></div>
      <button id="styleBtn">Включить стиль</button>
    </div>
  </div>

  <div class="section">
    <h2>Квесты сегодня</h2>
    <div id="quests"></div>
  </div>

  <div class="section" id="bonusBox" style="display:none">
    <h2>Бонусы после 50 уровня</h2>
    <div class="small" id="bonusHint" style="margin-bottom:8px"></div>
    <div id="bonusList"></div>
  </div>

  <div class="section">
    <h2>Дорожки наград</h2>
    <div class="small" style="margin-bottom:8px">
      Фри — валюта и кейсы. Пасс+ — карты, стили и акции. Пасс++ — бонусы на 1-10 и 41-50.
    </div>
    <div id="tracks"></div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
let S = null;
function tg(){ try { return window.Telegram && Telegram.WebApp ? Telegram.WebApp : null; } catch(e){ return null; } }
function headers(){
  const t = tg();
  const init = (t && t.initData) || sessionStorage.getItem("tginit") || "";
  return {"X-Telegram-Init-Data": init};
}
function esc(s){ return String(s == null ? "" : s).replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c])); }
function toast(text){
  const el = document.getElementById("toast");
  el.textContent = text; el.className = "toast on";
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "toast", 2600);
}
function money(n){ return String(Math.round(Number(n)||0)).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }

async function api(path, body){
  const opts = {headers: Object.assign({"Content-Type":"application/json"}, headers())};
  if (body !== undefined){ opts.method = "POST"; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  return r.json();
}

function showReports(){
  const reports = (S.reports || []);
  if (!reports.length) return;
  const r = reports[0];
  const items = (r.items || []).slice(0, 12).map(x => "· " + x).join("\n");
  alert("Сезон " + r.season + " закрыт.\n" +
        "Уровень: " + r.level + (r.premium ? " · Пасс++" : r.plus ? " · Пасс+" : "") + "\n" +
        "Незабранные награды выданы автоматически (" + (r.count || 0) + "):\n" + items);
}

function paint(){
  const p = S.progress;
  document.getElementById("seasonName").textContent = S.season.name;
  document.getElementById("heroName").textContent = S.season.theme.name;
  const own = S.title && S.title.title;
  document.getElementById("heroSub").textContent = own
    ? ("Твой титул: «" + own + "»")
    : ("Сезон " + S.season.key + " · титул «" + S.season.theme.title + "» за полное прохождение Пасс++");
  document.getElementById("lvlText").textContent = p.level + " ур.";
  const need = p.need || 0;
  const pct = p.level >= 50 ? 100 : Math.round((p.into / (need || 1)) * 100);
  document.getElementById("xpFill").style.width = pct + "%";
  document.getElementById("xpText").textContent =
    p.level >= 50 ? (money(p.xp) + " XP · бонусы после 50") : (p.into + " / " + need + " XP");

  const buys = document.getElementById("buys");
  const items = [];
  if (!p.plus) items.push({kind:"plus", label:"Северо-Пасс+ · " + S.prices.plus + " 💎", alt:false});
  if (!p.premium) items.push({kind: p.plus ? "upgrade" : "premium",
    label:(p.plus ? "До Пасс++ · " + S.prices.upgrade : "Северо-Пасс++ · " + S.prices.premium) + " 💎", alt:true});
  buys.innerHTML = items.length
    ? items.map(i => '<button data-buy="' + i.kind + '" class="' + (i.alt ? "alt" : "") + '">' + i.label + '</button>').join("")
    : '<button disabled>Обе дорожки куплены</button>';
  buys.querySelectorAll("[data-buy]").forEach(b => b.onclick = () => buy(b.dataset.buy, b));

  const q = document.getElementById("quests");
  q.innerHTML = S.quests.map(item => {
    const done = item.claimed;
    const ready = item.ready && (S.progress.plus || !item.plus);
    return '<div class="quest ' + (done ? "done" : "") + '">' +
      '<div class="qt"><span>' + esc(item.title) + '</span>' +
      '<span>' + (item.plus ? '<span class="plus">ПАСС+</span>' : "") + '</span></div>' +
      '<div class="qm"><span>' + Math.min(item.progress, item.need) + ' / ' + item.need + '</span>' +
      '<span>+' + item.xp + ' XP</span></div>' +
      '<button data-quest="' + item.slot + '" ' + (ready ? "" : "disabled") + '>' +
      (done ? "Забрано" : ready ? "Забрать" : (item.plus && !S.progress.plus ? "Нужен Пасс+" : "В процессе")) +
      '</button></div>';
  }).join("");
  q.querySelectorAll("[data-quest]").forEach(b => b.onclick = () => claimQuest(Number(b.dataset.quest)));

  paintStyle();
  paintBonus();

  const t = document.getElementById("tracks");
  t.innerHTML = S.rewards.map(row => {
    const open = row.level <= p.level;
    const freeCell = cell(row.free, open, p.claimed_free.includes(row.level), "free", row.level);
    const plusCell = row.plus ? cell(row.plus, open && p.plus, p.claimed_plus.includes(row.level), "plus", row.level) : '<div class="cell locked">—</div>';
    const premCell = row.premium ? cell(row.premium, open && p.premium, p.claimed_prem.includes(row.level), "premium", row.level) : '<div class="cell locked">—</div>';
    return '<div class="track"><div class="level ' + (open ? "open" : "") + '">' + row.level + '</div>' +
      freeCell + plusCell + premCell + '</div>';
  }).join("");
  t.querySelectorAll("[data-claim]").forEach(b => b.onclick = () => claim(Number(b.dataset.level), b.dataset.track));
}

function cell(data, open, claimed, track, level){
  if (!data) return '<div class="cell locked">—</div>';
  const cls = "cell " + (track === "plus" ? "plus" : track === "premium" ? "prem" : "") + (open ? "" : " locked");
  const btn = !open ? "" :
    claimed ? '<button disabled>Забрано</button>' :
    '<button data-claim="1" data-level="' + level + '" data-track="' + track + '">Забрать</button>';
  return '<div class="' + cls + '">' + esc(data.text) + btn + '</div>';
}

function paintStyle(){
  const box = document.getElementById("styleBox");
  const btn = document.getElementById("styleBtn");
  const st = S.style;
  if (!st || !st.owned){ box.style.display = "none"; return; }
  box.style.display = "block";
  btn.textContent = st.active ? "Стиль включён" : "Включить стиль";
  btn.disabled = false;
  btn.onclick = async () => {
    const d = await api("/api/theme/set", {theme: st.id});
    if (d.error){ toast(d.error); return; }
    toast("Геймерский стиль включён");
    setTimeout(() => location.reload(), 700);
  };
}

function paintBonus(){
  const box = document.getElementById("bonusBox");
  const list = document.getElementById("bonusList");
  const hint = document.getElementById("bonusHint");
  const b = S.bonus || {steps: 0, claimed: 0, left: 0, to_next: 2800, options: []};
  if (!b.steps && !b.left){ box.style.display = "none"; return; }
  box.style.display = "block";
  hint.textContent = "Заработано шагов: " + b.claimed + " из " + b.steps +
    " · до следующего " + b.to_next + " XP";
  if (!b.left || !b.options.length){ list.innerHTML = '<div class="small">Все бонусы забраны</div>'; return; }
  const step = b.steps;
  list.innerHTML = b.options.map(opt =>
    '<div class="quest"><div class="qt"><span>Шаг ' + step + '</span>' +
    '<span>' + (opt.gems ? opt.gems + ' 💎' : 'бесплатно') + '</span></div>' +
    '<div class="qm"><span>' + esc((opt.bundle && opt.bundle.text) || '') + '</span></div>' +
    '<button data-bonus="' + opt.index + '">' + (opt.gems ? "Забрать за гемы" : "Забрать") +
    '</button></div>'
  ).join("");
  list.querySelectorAll("[data-bonus]").forEach(btn =>
    btn.onclick = () => takeBonus(step, Number(btn.dataset.bonus)));
}

async function takeBonus(step, index){
  const d = await api("/api/pass/bonus", {step: step, index: index});
  if (d.error){ toast(d.error); return; }
  toast("Получено: " + (d.granted || []).join(", "));
  await load();
}

async function load(){
  try{
    const d = await api("/api/pass");
    if (d.error){ toast(d.error); return; }
    const first = !S;
    S = d; paint();
    if (first) showReports();
  }catch(e){ toast("Связь потерялась"); }
}

async function claimQuest(slot){
  const d = await api("/api/pass/quest", {slot: slot});
  if (d.error){ toast(d.error); return; }
  toast("+" + d.amount + " XP в пасс");
  await load();
}
async function claim(level, track){
  const d = await api("/api/pass/claim", {level: level, track: track});
  if (d.error){ toast(d.error); return; }
  toast("Получено: " + (d.granted || []).join(", "));
  await load();
}
async function buy(kind, btn){
  btn.disabled = true;
  const d = await api("/api/pass/buy", {kind: kind});
  if (d.error){ toast(d.error); btn.disabled = false; return; }
  toast(kind === "plus" ? "Северо-Пасс+ открыт!" : "Северо-Пасс++ открыт · +20% прогресса");
  await load();
}

const t = tg();
if (t){ try { t.ready(); t.expand(); } catch(e){} }
load();
</script>
</body>
</html>
"""
