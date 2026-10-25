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

if (errors.length){
  console.error("ОШИБКИ (" + errors.length + "):\n" + errors.join("\n---\n"));
  process.exit(1);
}
console.log("стенд: страница работает без исключений");
