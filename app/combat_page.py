
"""Прототип боевой системы: комбо, рывок с i-frames, замах, стан.

Отдельная страница /combat — чтобы потрогать бой до того, как тащить его
в подземелье. Управление: стик слева, кнопки справа (удар, замах, рывок).
"""

COMBAT_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>Бой · прототип</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{height:100%;overflow:hidden;background:#0a0b0d;color:#f2f3f5;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;user-select:none}
#game{position:fixed;inset:0;display:block;width:100%;height:100%;touch-action:none}
.hud{position:fixed;left:0;right:0;top:0;padding:10px 12px;display:flex;gap:10px;
  align-items:center;pointer-events:none;font-variant-numeric:tabular-nums}
.bar{height:10px;border-radius:5px;background:rgba(255,255,255,.14);overflow:hidden;flex:1}
.bar i{display:block;height:100%;transition:width .12s}
.hp i{background:linear-gradient(90deg,#ff5a5a,#ff8a6a)}
.st i{background:linear-gradient(90deg,#3fd7ff,#7be0c8)}
.lbl{font-size:10px;letter-spacing:1.4px;color:#8b9198;width:24px}
.mult{font-size:20px;font-weight:900;color:#ffd400;min-width:52px;text-align:right}
.cd{position:fixed;right:14px;top:58px;display:flex;flex-direction:column;gap:8px;pointer-events:none}
.slot{width:52px;height:52px;border-radius:14px;border:1px solid rgba(255,255,255,.18);
  background:rgba(10,12,16,.66);display:flex;align-items:center;justify-content:center;
  font-size:11px;font-weight:800;letter-spacing:.6px;color:#cfd4db;position:relative;
  overflow:hidden}
.slot b{position:absolute;inset:auto 0 0;height:0%;background:rgba(255,212,0,.32)}
.pad{position:fixed;left:16px;bottom:26px;width:132px;height:132px;border-radius:50%;
  border:1px solid rgba(255,255,255,.14);background:rgba(12,14,18,.5)}
.pad i{position:absolute;left:50%;top:50%;width:54px;height:54px;margin:-27px 0 0 -27px;
  border-radius:50%;background:rgba(255,212,0,.30);border:1px solid rgba(255,212,0,.55)}
.btns{position:fixed;right:16px;bottom:30px;display:grid;gap:10px;
  grid-template-columns:repeat(2,74px)}
.act{height:74px;border-radius:20px;border:1px solid rgba(255,255,255,.16);
  background:rgba(18,21,26,.78);color:#f2f3f5;font-family:inherit;font-weight:800;
  font-size:12px;letter-spacing:.4px;display:flex;align-items:center;justify-content:center}
.act.main{background:rgba(255,212,0,.92);color:#0a0a0a;border-color:#ffd400}
.act:active{transform:translateY(1px)}
.act.dim{opacity:.45}
.foot{position:fixed;left:0;right:0;bottom:6px;text-align:center;font-size:10px;
  color:#5b6167;letter-spacing:1px;pointer-events:none}
.banner{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;
  font-size:30px;font-weight:900;letter-spacing:2px;pointer-events:none;opacity:0;
  transition:opacity .2s;text-align:center;padding:0 24px}
.banner.on{opacity:1}
</style>
</head>
<body>
<canvas id="game"></canvas>
<div class="hud">
  <span class="lbl">HP</span><div class="bar hp"><i id="hp" style="width:100%"></i></div>
  <span class="lbl">ST</span><div class="bar st"><i id="st" style="width:100%"></i></div>
  <span class="mult" id="kills">0</span>
  <span class="mult" id="mult"></span>
</div>
<div class="cd">
  <div class="slot" id="sHeavy"><b id="bHeavy"></b>ЗАМАХ</div>
  <div class="slot" id="sDash"><b id="bDash"></b>РЫВОК</div>
</div>
<div class="pad" id="pad"><i id="stick"></i></div>
<div class="btns">
  <button class="act" id="bHeavyBtn">ЗАМАХ</button>
  <button class="act" id="bDashBtn">РЫВОК</button>
  <button class="act main" id="bAtk" style="grid-column:1 / span 2">УДАР</button>
</div>
<div class="banner" id="banner"></div>
<div class="foot">ПРОТОТИП БОЯ · КОМБО · РЫВОК С НЕУЯЗВИМОСТЬЮ</div>
<script>
const cv = document.getElementById("game"), cx = cv.getContext("2d");
let W = 0, H = 0, DPR = 1;
function resize(){
  DPR = Math.min(2, window.devicePixelRatio || 1);
  W = window.innerWidth; H = window.innerHeight;
  cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
  cx.setTransform(DPR, 0, 0, DPR, 0, 0);
}
window.addEventListener("resize", resize); resize();

/* ---------- состояние ---------- */
const S = {
  t: 0, hitstop: 0, shake: 0, zoom: 1, slow: 0,
  combo: 0, comboT: 0, comboWindow: 0.62,
  hp: 100, max: 100, st: 100, stMax: 100,
  over: false, kills: 0, msg: null, msgT: 0,
};
const P = {
  x: 0, y: 0, r: 15, vx: 0, vy: 0, speed: 250,
  face: {x: 0, y: 1}, atkCd: 0, dashCd: 0, heavyCd: 0,
  dashT: 0, dashDir: {x: 0, y: 0}, iframes: 0, swing: null,
  heavy: 0, hurt: 0, alive: true,
};
const KEYS = {};
const STICK = { active: false, id: null, dx: 0, dy: 0, ox: 0, oy: 0 };
const enemies = [];
const shots = [];
const fx = [];
const nums = [];

/* ---------- звук ---------- */
let AC = null;
function beep(f, d, type, g){
  try{
    if (!AC) AC = new (window.AudioContext || window.webkitAudioContext)();
    if (AC.state === "suspended") AC.resume();
    const o = AC.createOscillator(), gn = AC.createGain();
    o.type = type || "square"; o.frequency.value = f;
    gn.gain.setValueAtTime(g || 0.05, AC.currentTime);
    gn.gain.exponentialRampToValueAtTime(0.001, AC.currentTime + d);
    o.connect(gn); gn.connect(AC.destination); o.start(); o.stop(AC.currentTime + d);
  }catch(e){}
}

/* ---------- спавн ---------- */
function spawnWave(n){
  for (let i = 0; i < n; i++){
    const a = Math.random() * Math.PI * 2, d = 240 + Math.random() * 220;
    const type = Math.random() < 0.34 ? "shooter" : (Math.random() < 0.25 ? "brute" : "grunt");
    enemies.push({
      id: "e" + (Math.random() * 1e9 | 0),
      type: type,
      x: P.x + Math.cos(a) * d, y: P.y + Math.sin(a) * d,
      hp: type === "brute" ? 90 : type === "shooter" ? 42 : 55,
      max: type === "brute" ? 90 : type === "shooter" ? 42 : 55,
      r: type === "brute" ? 22 : 15,
      speed: type === "brute" ? 70 : type === "shooter" ? 80 : 120,
      wind: 0, cd: 0.8 + Math.random(), stagger: 0, hurt: 0,
      face: {x: 0, y: 1}, dead: false, lunge: 0,
    });
  }
}

/* ---------- удары ---------- */
function playerAttack(){
  if (!P.alive || P.atkCd > 0 || P.dashT > 0 || S.over) return;
  S.combo = (S.comboT > 0) ? Math.min(3, S.combo + 1) : 1;
  S.comboT = S.comboWindow;
  P.atkCd = S.combo === 3 ? 0.34 : 0.20;
  P.swing = { t: 0, dur: S.combo === 3 ? 0.26 : 0.18, arc: S.combo === 3 ? 2.5 : 1.7,
              reach: S.combo === 3 ? 84 : 66, dmg: [14, 16, 26][S.combo - 1],
              hit: {} , heavy: false };
  beep(S.combo === 3 ? 520 : 700, 0.05, "square", 0.045);
  if (S.combo === 3){ S.shake = Math.max(S.shake, 7); S.zoom = 1.035; }
}
function playerHeavy(){
  if (!P.alive || P.heavyCd > 0 || P.dashT > 0 || S.st < 35 || S.over) return;
  P.heavyCd = 0.85; S.st -= 35; P.heavy = 0.42;
  P.swing = { t: 0, dur: 0.36, arc: 3.2, reach: 100, dmg: 34, hit: {}, heavy: true, delay: 0.16 };
  beep(300, 0.12, "sawtooth", 0.05);
}
function playerDash(){
  if (!P.alive || P.dashCd > 0 || S.st < 25 || S.over) return;
  const v = inputVec();
  P.dashDir = (v.x || v.y) ? {x: v.x, y: v.y} : P.face;
  P.dashT = 0.18; P.iframes = 0.20; P.dashCd = 0.55; S.st -= 25;
  beep(880, 0.05, "sine", 0.035);
  fx.push({ type: "dashRing", x: P.x, y: P.y, t: 0, dur: 0.28 });
}

/* ---------- ввод ---------- */
function inputVec(){
  let x = 0, y = 0;
  if (KEYS["a"] || KEYS["ф"]) x -= 1;
  if (KEYS["d"] || KEYS["в"]) x += 1;
  if (KEYS["w"] || KEYS["ц"]) y -= 1;
  if (KEYS["s"] || KEYS["ы"]) y += 1;
  x += STICK.dx; y += STICK.dy;
  const len = Math.hypot(x, y);
  if (len > 1){ x /= len; y /= len; }
  return {x: x, y: y};
}
window.addEventListener("keydown", (e) => {
  const k = e.key.toLowerCase();
  KEYS[k] = true;
  if (k === " " || k === "j") { e.preventDefault(); playerAttack(); }
  if (k === "k") { e.preventDefault(); playerHeavy(); }
  if (k === "shift" || k === "l") { e.preventDefault(); playerDash(); }
});
window.addEventListener("keyup", (e) => { KEYS[e.key.toLowerCase()] = false; });

/* ---------- геометрия удара ---------- */
function hitArc(swing, target){
  const dx = target.x - P.x, dy = target.y - P.y;
  const dist = Math.hypot(dx, dy);
  if (dist > swing.reach + target.r) return false;
  const ang = Math.atan2(dy, dx);
  const face = Math.atan2(P.face.y, P.face.x);
  let diff = Math.abs(((ang - face + Math.PI * 3) % (Math.PI * 2)) - Math.PI);
  return diff <= swing.arc / 2;
}

/* ---------- урон ---------- */
function damageEnemy(e, dmg, knock){
  e.hp -= dmg; e.hurt = 0.14; e.stagger = 0.22;
  e.x += Math.cos(Math.atan2(e.y - P.y, e.x - P.x)) * knock;
  e.y += Math.sin(Math.atan2(e.y - P.y, e.x - P.x)) * knock;
  nums.push({x: e.x, y: e.y - 20, v: dmg, t: 0, dur: 0.7, big: dmg > 25});
  S.hitstop = Math.max(S.hitstop, dmg > 25 ? 0.085 : 0.05);
  S.shake = Math.max(S.shake, dmg > 25 ? 8 : 3.5);
  fx.push({type: "spark", x: e.x, y: e.y, t: 0, dur: 0.22, big: dmg > 25});
  beep(dmg > 25 ? 220 : 380, 0.045, "square", 0.03);
  if (e.hp <= 0 && !e.dead){
    e.dead = true; S.kills++; S.slow = 0.14; S.zoom = 1.06;
    fx.push({type: "death", x: e.x, y: e.y, t: 0, dur: 0.5});
    beep(140, 0.18, "triangle", 0.05);
  }
}
function damagePlayer(dmg){
  if (P.iframes > 0 || P.dashT > 0 || !P.alive) return;
  S.hp -= dmg; P.iframes = 0.5; P.hurt = 0.25;
  S.shake = 10; S.hitstop = 0.07;
  nums.push({x: P.x, y: P.y - 24, v: dmg, t: 0, dur: 0.7, hurt: true});
  beep(120, 0.14, "sawtooth", 0.05);
  if (S.hp <= 0){ S.hp = 0; P.alive = false; S.over = true; banner("ТЫ ПАЛ"); }
}

/* ---------- апдейт ---------- */
function update(dt){
  if (S.over) { S.t += dt; return; }
  if (S.hitstop > 0){ S.hitstop -= dt; return; }

  const slow = S.slow > 0 ? 0.35 : 1;
  if (S.slow > 0) S.slow -= dt;
  S.t += dt * slow;
  const d = dt * slow;

  P.iframes = Math.max(0, P.iframes - d);
  P.hurt = Math.max(0, P.hurt - d);
  P.atkCd = Math.max(0, P.atkCd - d);
  P.dashCd = Math.max(0, P.dashCd - d);
  P.heavyCd = Math.max(0, P.heavyCd - d);
  S.shake = Math.max(0, S.shake - d * 30);
  S.zoom += (1 - S.zoom) * Math.min(1, d * 8);
  S.comboT = Math.max(0, S.comboT - d);
  if (S.comboT <= 0) S.combo = 0;
  if (S.msgT > 0) S.msgT -= d;

  // стамина
  S.st = Math.min(S.stMax, S.st + 22 * d);

  // движение
  if (P.dashT > 0){
    P.dashT -= d;
    P.x += P.dashDir.x * 720 * d;
    P.y += P.dashDir.y * 720 * d;
  } else {
    const v = inputVec();
    if (v.x || v.y) P.face = v;
    P.x += v.x * P.speed * d;
    P.y += v.y * P.speed * d;
  }

  // замах
  if (P.swing){
    const s = P.swing;
    s.t += d;
    const delay = s.delay || 0;
    if (s.t >= delay && s.t - d < delay + 0.05){
      for (const e of enemies){
        if (e.dead || s.hit[e.id]) continue;
        if (hitArc(s, e)){
          s.hit[e.id] = true;
          damageEnemy(e, s.dmg, s.heavy ? 26 : (S.combo === 3 ? 20 : 8));
        }
      }
      if (s.heavy) S.shake = Math.max(S.shake, 9);
    }
    if (s.t >= s.dur) P.swing = null;
  }

  // враги
  for (const e of enemies){
    if (e.dead) continue;
    e.hurt = Math.max(0, e.hurt - d);
    e.stagger = Math.max(0, e.stagger - d);
    const dx = P.x - e.x, dy = P.y - e.y;
    const dist = Math.hypot(dx, dy) || 1;
    e.face = {x: dx / dist, y: dy / dist};
    if (e.stagger > 0) continue;

    if (e.type === "shooter"){
      if (dist > 260) { e.x += e.face.x * e.speed * d; e.y += e.face.y * e.speed * d; }
      else if (dist < 190) { e.x -= e.face.x * e.speed * 0.7 * d; e.y -= e.face.y * e.speed * 0.7 * d; }
      e.cd -= d;
      if (e.cd <= 0 && dist < 420){
        e.cd = 1.6 + Math.random() * 0.7; e.wind = 0.28;
        shots.push({x: e.x, y: e.y, vx: e.face.x * 300, vy: e.face.y * 300, r: 5, dmg: 8, t: 0});
        beep(520, 0.05, "sine", 0.025);
      }
    } else {
      const reach = e.type === "brute" ? 52 : 40;
      if (dist > reach){
        const sp = e.speed * (e.wind > 0 ? 0.25 : 1);
        e.x += e.face.x * sp * d; e.y += e.face.y * sp * d;
      } else if (e.cd <= 0){
        e.cd = 1.1; e.wind = 0.45;
      }
      e.cd -= d;
      if (e.wind > 0){
        e.wind -= d;
        if (e.wind <= 0 && dist < reach + 26){
          if (e.type === "brute"){ S.shake = Math.max(S.shake, 6); }
          damagePlayer(e.type === "brute" ? 16 : 9);
        }
      }
    }
    // расталкивание
    for (const o of enemies){
      if (o === e || o.dead) continue;
      const ox = e.x - o.x, oy = e.y - o.y, od = Math.hypot(ox, oy) || 1;
      if (od < e.r + o.r){
        e.x += (ox / od) * (e.r + o.r - od) * 0.5;
        e.y += (oy / od) * (e.r + o.r - od) * 0.5;
      }
    }
  }

  // пули
  for (const s of shots){
    s.x += s.vx * d; s.y += s.vy * d; s.t += d;
    if (Math.hypot(s.x - P.x, s.y - P.y) < s.r + P.r) { damagePlayer(s.dmg); s.t = 99; }
  }
  for (let i = shots.length - 1; i >= 0; i--) if (shots[i].t > 2.4) shots.splice(i, 1);
  for (let i = enemies.length - 1; i >= 0; i--) if (enemies[i].dead) enemies.splice(i, 1);

  // эффекты
  for (const f of fx) f.t += d;
  for (let i = fx.length - 1; i >= 0; i--) if (fx[i].t > fx[i].dur) fx.splice(i, 1);
  for (const n of nums){ n.t += d; n.y -= 42 * d; }
  for (let i = nums.length - 1; i >= 0; i--) if (nums[i].t > nums[i].dur) nums.splice(i, 1);

  if (!enemies.length) spawnWave(4 + (S.kills / 6 | 0));
}

/* ---------- отрисовка ---------- */
function drawPlayer(){
  const blink = P.iframes > 0 && Math.floor(S.t * 20) % 2 === 0;
  cx.save();
  cx.translate(P.x, P.y);
  // тень
  cx.fillStyle = "rgba(0,0,0,.45)";
  cx.beginPath(); cx.ellipse(0, 12, 15, 7, 0, 0, 7); cx.fill();
  cx.globalAlpha = blink ? 0.45 : 1;
  {
    const g = cx.createLinearGradient(0, -20, 0, 18);
    g.addColorStop(0, P.hurt > 0 ? "#ff9a9a" : "#f2f3f5");
    g.addColorStop(1, P.hurt > 0 ? "#c85a5a" : "#9aa0a6");
    cx.fillStyle = g;
    cx.beginPath(); cx.arc(0, -4, 13, 0, 7); cx.fill();
    // глаз-направление
    cx.fillStyle = "#ffd400";
    cx.beginPath();
    cx.arc(P.face.x * 5, -4 + P.face.y * 5, 4.4, 0, 7); cx.fill();
    cx.fillStyle = "#0a0a0a";
    cx.beginPath();
    cx.arc(P.face.x * 6.4, -4 + P.face.y * 6.4, 1.9, 0, 7); cx.fill();
    // белая обводка: видно на чёрном
    cx.strokeStyle = "rgba(255,255,255,.75)"; cx.lineWidth = 1.6;
    cx.beginPath(); cx.arc(0, -4, 13, 0, 7); cx.stroke();
  }
  cx.globalAlpha = 1;
  cx.restore();

  // дуга удара
  if (P.swing){
    const s = P.swing, k = s.t / s.dur;
    const face = Math.atan2(P.face.y, P.face.x);
    const a0 = face - s.arc / 2 + s.arc * k * 0.85;
    cx.save();
    cx.translate(P.x, P.y);
    cx.strokeStyle = s.heavy ? "rgba(255,212,0,.95)" : "rgba(255,255,255,.85)";
    cx.lineWidth = s.heavy ? 9 : 6;
    cx.lineCap = "round";
    cx.beginPath();
    cx.arc(0, 0, s.reach * (0.72 + k * 0.3), a0 - 0.5, a0 + 0.5);
    cx.stroke();
    cx.restore();
  }
}
function drawEnemy(e){
  cx.save();
  cx.translate(e.x, e.y);
  cx.fillStyle = "rgba(0,0,0,.4)";
  cx.beginPath(); cx.ellipse(0, e.r * 0.75, e.r, e.r * 0.45, 0, 0, 7); cx.fill();
  const col = e.type === "brute" ? "#b06a3a" : e.type === "shooter" ? "#7c5cff" : "#31d0aa";
  cx.fillStyle = e.hurt > 0 ? "#fff" : col;
  cx.beginPath(); cx.arc(0, 0, e.r, 0, 7); cx.fill();
  // шипы: брут — толстые, грант — мелкие
  cx.strokeStyle = e.hurt > 0 ? "#fff" : col; cx.lineWidth = e.type === "brute" ? 3 : 2;
  for (let i = 0; i < (e.type === "brute" ? 8 : 5); i++){
    const a = i * (Math.PI * 2 / (e.type === "brute" ? 8 : 5)) + S.t;
    cx.beginPath();
    cx.moveTo(Math.cos(a) * e.r, Math.sin(a) * e.r);
    cx.lineTo(Math.cos(a) * (e.r + (e.type === "brute" ? 7 : 5)), Math.sin(a) * (e.r + 5));
    cx.stroke();
  }
  cx.fillStyle = "#0a0a0a";
  cx.beginPath();
  cx.arc(e.face.x * e.r * 0.42, e.face.y * e.r * 0.42, e.r * 0.26, 0, 7); cx.fill();
  // телеграф замаха
  if (e.wind > 0){
    cx.strokeStyle = "rgba(255,90,90," + (0.4 + 0.6 * (1 - e.wind / 0.45)) + ")";
    cx.lineWidth = 3;
    cx.beginPath(); cx.arc(0, 0, e.r + 7 + e.wind * 22, 0, 7); cx.stroke();
  }
  // хп
  if (e.hp < e.max){
    cx.fillStyle = "rgba(0,0,0,.55)"; cx.fillRect(-e.r, -e.r - 12, e.r * 2, 4);
    cx.fillStyle = "#ff5a5a"; cx.fillRect(-e.r, -e.r - 12, e.r * 2 * (e.hp / e.max), 4);
  }
  cx.restore();
}
function draw(){
  const sh = S.shake;
  cx.save();
  cx.setTransform(DPR, 0, 0, DPR, 0, 0);
  cx.clearRect(0, 0, W, H);
  const ox = W / 2 - P.x, oy = H / 2 - P.y;
  const shx = (Math.random() - 0.5) * sh, shy = (Math.random() - 0.5) * sh;
  cx.translate(W / 2 + shx, H / 2 + shy);
  cx.scale(S.zoom, S.zoom);
  cx.translate(-W / 2, -H / 2);
  cx.translate(ox, oy);

  // пол-сетка
  cx.fillStyle = "#0b0d10";
  cx.fillRect(P.x - W, P.y - H, W * 2, H * 2);
  cx.strokeStyle = "rgba(255,255,255,.045)"; cx.lineWidth = 1;
  const step = 64;
  const x0 = Math.floor((P.x - W) / step) * step, y0 = Math.floor((P.y - H) / step) * step;
  cx.beginPath();
  for (let x = x0; x < P.x + W; x += step){ cx.moveTo(x, P.y - H); cx.lineTo(x, P.y + H); }
  for (let y = y0; y < P.y + H; y += step){ cx.moveTo(P.x - W, y); cx.lineTo(P.x + W, y); }
  cx.stroke();

  for (const s of shots){
    cx.fillStyle = "#ff9a6a";
    cx.beginPath(); cx.arc(s.x, s.y, s.r, 0, 7); cx.fill();
  }
  for (const e of enemies) drawEnemy(e);
  drawPlayer();

  for (const f of fx){
    const k = f.t / f.dur;
    if (f.type === "spark"){
      cx.strokeStyle = "rgba(255,255,255," + (1 - k) + ")";
      cx.lineWidth = f.big ? 3 : 2;
      for (let i = 0; i < 6; i++){
        const a = i * 1.05 + f.t * 8, r0 = 6 + k * (f.big ? 34 : 18);
        cx.beginPath();
        cx.moveTo(f.x + Math.cos(a) * r0, f.y + Math.sin(a) * r0);
        cx.lineTo(f.x + Math.cos(a) * (r0 + 9), f.y + Math.sin(a) * (r0 + 9));
        cx.stroke();
      }
    } else if (f.type === "dashRing"){
      cx.strokeStyle = "rgba(120,220,255," + (1 - k) * 0.9 + ")";
      cx.lineWidth = 3;
      cx.beginPath(); cx.arc(f.x, f.y, 12 + k * 46, 0, 7); cx.stroke();
    } else if (f.type === "death"){
      cx.strokeStyle = "rgba(255,90,90," + (1 - k) + ")";
      cx.lineWidth = 2;
      for (let i = 0; i < 8; i++){
        const a = i * 0.8, r0 = 8 + k * 40;
        cx.beginPath();
        cx.moveTo(f.x + Math.cos(a) * r0 * 0.6, f.y + Math.sin(a) * r0 * 0.6);
        cx.lineTo(f.x + Math.cos(a) * r0, f.y + Math.sin(a) * r0);
        cx.stroke();
      }
    }
  }
  for (const n of nums){
    const k = n.t / n.dur;
    cx.globalAlpha = 1 - k * k;
    cx.fillStyle = n.hurt ? "#ff8a8a" : (n.big ? "#ffd400" : "#ffffff");
    cx.font = "900 " + (n.big ? 22 : 17) + "px -apple-system,Segoe UI,Roboto,sans-serif";
    cx.textAlign = "center";
    cx.fillText("-" + Math.round(n.v), n.x, n.y);
    cx.globalAlpha = 1;
  }
  cx.restore();
}

/* ---------- HUD ---------- */
function syncHud(){
  document.getElementById("hp").style.width = Math.max(0, (S.hp / S.max) * 100) + "%";
  document.getElementById("st").style.width = Math.max(0, (S.st / S.stMax) * 100) + "%";
  document.getElementById("mult").textContent = S.combo > 1 ? "x" + S.combo : "";
  document.getElementById("kills").textContent = "☠" + S.kills;
  const hd = Math.max(0, P.heavyCd), dd = Math.max(0, P.dashCd);
  document.getElementById("bHeavy").style.height = (hd / 0.85 * 100) + "%";
  document.getElementById("bDash").style.height = (dd / 0.55 * 100) + "%";
  document.getElementById("bHeavyBtn").classList.toggle("dim", S.st < 35);
  document.getElementById("bDashBtn").classList.toggle("dim", S.st < 25);
}
function banner(text){
  const el = document.getElementById("banner");
  el.textContent = text; el.classList.add("on");
  setTimeout(() => el.classList.remove("on"), 1400);
}

/* ---------- цикл ---------- */
let last = performance.now();
function frame(now){
  const dt = Math.min(0.05, (now - last) / 1000); last = now;
  update(dt); draw(); syncHud();
  requestAnimationFrame(frame);
}

/* ---------- управление ---------- */
const pad = document.getElementById("pad"), stick = document.getElementById("stick");
function padMove(e){
  const t = e.touches ? e.touches[0] : e;
  const r = pad.getBoundingClientRect();
  let dx = (t.clientX - (r.left + r.width / 2)) / (r.width / 2);
  let dy = (t.clientY - (r.top + r.height / 2)) / (r.height / 2);
  const len = Math.hypot(dx, dy);
  if (len > 1){ dx /= len; dy /= len; }
  STICK.dx = dx; STICK.dy = dy;
  stick.style.transform = "translate(" + dx * 34 + "px," + dy * 34 + "px)";
}
pad.addEventListener("touchstart", (e) => { STICK.active = true; padMove(e); }, {passive: false});
pad.addEventListener("touchmove", (e) => { if (STICK.active){ e.preventDefault(); padMove(e); } }, {passive: false});
pad.addEventListener("touchend", () => {
  STICK.active = false; STICK.dx = 0; STICK.dy = 0;
  stick.style.transform = "";
});
document.getElementById("bAtk").onclick = playerAttack;
document.getElementById("bHeavyBtn").onclick = playerHeavy;
document.getElementById("bDashBtn").onclick = playerDash;

/* ---------- тестовые крючки ---------- */
/* Прогон боя без requestAnimationFrame: headless-скриншоты и автотесты
   не дают кадров, а логику проверить надо. На игрока не влияет. */
window.__combatStep = function(seconds, ai){
  const dt = 1 / 60;
  for (let i = 0; i < seconds * 60; i++){
    if (ai){
      if (enemies.length){
        const e = enemies[0];
        const dx = e.x - P.x, dy = e.y - P.y, d = Math.hypot(dx, dy) || 1;
        STICK.dx = d > 40 ? dx / d : 0;
        STICK.dy = d > 40 ? dy / d : 0;
        if (d > 30) P.face = {x: dx / d, y: dy / d};
        if (d < 86) playerAttack();
        if (i % 220 === 0) playerHeavy();
        if (i % 380 === 0) playerDash();
      } else { STICK.dx = 0; STICK.dy = 0; }
    }
    update(dt);
  }
  return window.__combatState();
};
window.__combatState = function(){
  return {kills: S.kills, hp: Math.round(S.hp), enemies: enemies.length,
          combo: S.combo, shots: shots.length, fx: fx.length,
          player: [Math.round(P.x), Math.round(P.y)]};
};

/* ---------- старт ---------- */
P.x = 0; P.y = 0;
spawnWave(4);
requestAnimationFrame(frame);
const tg = window.Telegram && window.Telegram.WebApp;
if (tg){ try { tg.ready(); tg.expand(); } catch(e){} }
</script>
</body>
</html>
"""
