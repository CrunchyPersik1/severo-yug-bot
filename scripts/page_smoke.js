/* DOM-заглушка для страниц мини-аппок: прогон без браузера.
 *
 *   node scripts/page_smoke.js <файл.js>
 *
 * Создаёт минимальный document/window, подсовывает фейковые canvas 2d и webgl,
 * выполняет скрипт страницы и прокручивает несколько кадров. Ловит опечатки и
 * обращения к отсутствующим элементам, которые `node --check` не видит.
 * Код возврата 1 — если что-то упало.
 */
"use strict";
const fs = require("fs");
const vm = require("vm");

const file = process.argv[2];
if (!file || !fs.existsSync(file)){
  console.error("usage: node scripts/page_smoke.js <file.js>");
  process.exit(2);
}
const code = fs.readFileSync(file, "utf8");

const rafQueue = [];
let canvasCalls = 0;
function ctx2d(){
  const grad = {addColorStop(){}};
  const store = {};
  return new Proxy(store, {
    get(t, p){
      if (p === "createRadialGradient" || p === "createLinearGradient") return () => grad;
      if (p === "measureText") return () => ({width: 10});
      if (p === "canvas") return null;
      if (p in t) return t[p];
      return () => { canvasCalls++; };
    },
    set(t, p, v){ t[p] = v; return true; }
  });
}

function glStub(){
  const t = {
    getShaderParameter: () => true,
    getProgramParameter: () => true,
    getAttribLocation: () => 0,
    getUniformLocation: () => ({}),
    createTexture: () => ({}),
    createFramebuffer: () => ({}),
    createBuffer: () => ({}),
    createShader: () => ({}),
    createProgram: () => ({}),
    shaderSource: () => {},
    getShaderInfoLog: () => "",
    getProgramInfoLog: () => ""
  };
  return new Proxy(t, {
    get(o, p){
      if (p in o) return o[p];
      if (typeof p === "string" && /^[A-Z][A-Z0-9_]*$/.test(p)) return 1;
      return () => { canvasCalls++; };
    },
    set(o, p, v){ o[p] = v; return true; }
  });
}

const els = new Map();
function makeEl(tag){
  return {
    tagName: String(tag || "div").toUpperCase(),
    id: "", style: {}, dataset: {}, innerHTML: "", textContent: "", className: "",
    width: 0, height: 0, clientWidth: 400, clientHeight: 800,
    classList: {add(){}, remove(){}, toggle(){}, contains(){ return false; }},
    getContext(kind){ return kind === "webgl" ? glStub() : ctx2d(); },
    addEventListener(){}, removeEventListener(){},
    querySelectorAll(){ return []; }, querySelector(){ return null; },
    getBoundingClientRect(){ return {left: 0, top: 0, width: 118, height: 118}; },
    appendChild(){}, remove(){}, focus(){}
  };
}

class ImageStub {
  constructor(){ this.complete = true; this.naturalWidth = 16; this.naturalHeight = 16; }
  set src(v){ this._src = v; }
  get src(){ return this._src; }
}

const store = {};
const sandbox = {
  console, Math, Date, JSON, parseFloat, parseInt, isNaN, isFinite, Number, String,
  Boolean, Array, Object, Map, Set, Float32Array, Uint8Array, Uint32Array, RegExp, Error,
  setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
  performance: {now: () => 1000},
  localStorage: {
    getItem: k => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); }
  },
  navigator: {userAgent: "smoke", language: "ru"},
  document: {
    getElementById(id){
      if (!els.has(id)){ const e = makeEl("div"); e.id = id; els.set(id, e); }
      return els.get(id);
    },
    createElement(tag){ return makeEl(tag); },
    querySelectorAll(){ return []; },
    querySelector(){ return null; },
    body: {classList: {add(){}, remove(){}, toggle(){}, contains(){ return false; }}},
    addEventListener(){}, removeEventListener(){}
  },
  Image: ImageStub,
  addEventListener(){}, removeEventListener(){},
  requestAnimationFrame(cb){ rafQueue.push(cb); return rafQueue.length; },
  innerWidth: 400, innerHeight: 800, devicePixelRatio: 2
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.fetch = () => Promise.resolve({ok: false, json: () => Promise.resolve({})});

const errors = [];
const context = vm.createContext(sandbox);
function run(label, fn){
  try { fn(); } catch (e){ errors.push(label + ": " + (e && e.stack ? e.stack.split("\n").slice(0, 4).join("\n") : e)); }
}
function has(name){
  try { return vm.runInContext("typeof " + name, context) !== "undefined"; }
  catch (e){ return false; }
}
function call(name, args){
  if (!has(name)) return undefined;
  return vm.runInContext(name, context).apply(null, args || []);
}
function check(label, got, want){
  const ok = got === want;
  if (!ok){
    errors.push("проверка «" + label + "»: " + JSON.stringify(got) +
                " вместо " + JSON.stringify(want));
  }
  console.log("  " + (ok ? "ok  " : "FAIL") + " " + label + ": " + JSON.stringify(got));
}

run("инициализация", () => vm.runInContext(code, context, {filename: file}));

// гоняем только те кадры, которые страница сама запланировала через rAF
function frames(count, base){
  for (let i = 0; i < count && rafQueue.length; i++){
    const cb = rafQueue.shift();
    const label = "кадр " + (i + 1);
    try { cb(base + i * 16); }
    catch (e){ errors.push(label + ": " + ((e && e.stack) || e)); return; }
  }
}
frames(8, 1000);
if (has("startbtn")) run("кнопка старта", () => {
  const el = sandbox.document.getElementById("startbtn");
  if (typeof el.onclick === "function") el.onclick({});
});
run("кадры", () => frames(12, 2000));
run("атака", () => { for (let i = 0; i < 4; i++){ call("attack"); frames(1, 3000 + i * 16); } });
run("способность", () => { call("ability"); call("shieldUp"); frames(2, 3100); });
run("настройки графики", () => {
  if (!has("FX")) return;
  const fx = vm.runInContext("FX", context);
  call("openGfx");
  fx.setLevel(0); frames(2, 3200);
  fx.setLevel(2); frames(2, 3300);
});

const summary = has("FX")
  ? vm.runInContext("({level: FX.level, hasGL: FX.hasGL, live: FX.live})", context)
  : {};
console.log("инициализация ok · обращений к canvas-API: " + canvasCalls +
            " · состояние: " + JSON.stringify(summary));

/* ---------- кооп-босс: подсовываем фейковый сервер и прокликиваем ---------- */

function bossPayload(over){
  const base = {
    id: 1, zone: 0, zone_name: "Опушка", hp: 540, max_hp: 540, status: "waiting",
    status_text: "ждём второго", coop: false, ready_in: 10, cooldown: 0, hit: 0,
    players: [{name: "Ты", slot: 1, hp: 120, max_hp: 120, damage: 0, hits: 0,
               dead: false, left: false, me: true}],
    me: {name: "Ты", slot: 1, hp: 120, max_hp: 120, damage: 0, hits: 0,
         dead: false, left: false, me: true}
  };
  return Object.assign(base, over || {});
}

async function coopScenario(){
  const seen = [];
  let next = {boss: bossPayload()};
  sandbox.fetch = async function(url, opts){
    seen.push(String(url) + " " + ((opts && opts.method) || "GET"));
    return {ok: true, status: 200, json: async () => ({ok: true, boss: next.boss})};
  };
  const run1 = (expr) => vm.runInContext(expr, context);
  const room = () => run1("COOP.room");
  const pairs = [
    {name: "Саня", slot: 2, hp: 120, max_hp: 120, damage: 0, hits: 0,
     dead: false, left: false, me: false}
  ];

  await run1("coopJoin(0)");
  check("кооп: комната открыта", run1("COOP.open"), true);
  check("кооп: статус ожидания", room().status, "waiting");

  next = {boss: bossPayload({status: "fight", coop: true, ready_in: 0,
                             players: [bossPayload().me].concat(pairs)})};
  await run1("coopPoll()");
  check("кооп: бой начался", room().status, "fight");
  check("кооп: в команде двое", room().players.length, 2);

  next = {boss: bossPayload({status: "fight", coop: true, hp: 420, hit: 120, cooldown: 0.4})};
  await run1("coopHit()");
  check("кооп: удар снял HP", room().hp, 420);
  check("кооп: урон попал в лог", run1("COOP.log.length") > 0, true);

  next = {boss: bossPayload({status: "dead", hp: 0, coop: true})};
  await run1("coopPoll()");
  check("кооп: победа видна", room().status, "dead");

  await run1("coopClose(false)");
  check("кооп: закрыли оверлей", run1("COOP.open"), false);
  check("кооп: ручки дёргались", seen.length >= 4, true);
  console.log("  запросы: " + seen.map(function(s){ return s.replace(/^http:\/\/x/, ""); }).join(" | "));
}

(async function(){
  if (has("COOP")){
    try { await coopScenario(); }
    catch (e){ errors.push("сценарий кооп-боя: " + ((e && e.stack) || e)); }
  }
  if (errors.length){
    console.error("ОШИБКИ (" + errors.length + "):\n" + errors.join("\n---\n"));
    process.exitCode = 1;
    return;
  }
  console.log("стенд: страница работает без исключений");
})();
