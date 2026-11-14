"""Общий стиль мини-аппок: тема игрока, частицы и единый дизайн элементов.

Страницы не переписываются. К каждой подмешивается слой оформления: он
подменяет CSS-переменные и приводит кнопки, карточки и заголовки к одному
аккуратному виду — только через переменные темы, без вшитых цветов.
"""

from __future__ import annotations

POLISH = r"""<style>
  :root{
    --radius:14px; --edge:0 6px 20px rgba(0,0,0,.20);
    /* шкала, общая для всех страниц: отступы, радиусы, типографика */
    --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px;
    --r-1:10px; --r-2:14px; --r-pill:999px;
    --fs-xs:11px; --fs-sm:12.5px; --fs-md:14px; --fs-lg:17px;
    --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
    --money:var(--acc2);
  }
  *{ -webkit-tap-highlight-color:transparent }
  html{ -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility }
  body{
    background:var(--bg)!important;
    color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  }

  /* Мягкое свечение вместо пустой черноты */
  body::before{
    content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
    background:
      radial-gradient(115% 52% at 50% -18%,
        color-mix(in srgb, var(--acc) 20%, transparent), transparent 72%),
      radial-gradient(75% 42% at 88% 108%,
        color-mix(in srgb, var(--acc2) 11%, transparent), transparent 70%);
  }
  body>*{ position:relative; z-index:1 }

  /* Шапки */
  header,.top{
    background:color-mix(in srgb, var(--bg) 88%, transparent)!important;
    border-color:var(--line)!important;
  }

  /* Карточки и панели */
  .card,.item,.lot,.box,.slot,.tile,.unit,.panel,.stat{
    background:var(--panel);
    border:1px solid var(--line);
    border-radius:var(--radius);
    box-shadow:var(--edge);
    animation:__rise .46s cubic-bezier(.2,.8,.25,1) both;
    transition:transform .16s cubic-bezier(.2,.8,.25,1),
               box-shadow .22s ease, border-color .22s ease;
  }
  .card:nth-child(2n),.item:nth-child(2n),.lot:nth-child(2n){ animation-delay:.03s }
  .card:nth-child(3n),.item:nth-child(3n),.lot:nth-child(3n){ animation-delay:.06s }
  .card:nth-child(5n),.item:nth-child(5n),.lot:nth-child(5n){ animation-delay:.1s }
  .card:active,.item:active,.lot:active{ transform:scale(.975) }
  @keyframes __rise{ from{opacity:0;transform:translateY(11px) scale(.986)} to{opacity:1;transform:none} }

  /* Кнопки: плоский акцент, тонкая внутренняя подсветка, без шаблонных градиентов */
  button,.go,.buy,.sell,.btn,.mult,.tab,.act{
    border:0!important;
    border-radius:12px!important;
    background:var(--acc)!important;
    background-image:none!important;
    color:var(--acc-ink)!important;
    font-weight:800!important;
    letter-spacing:.35px;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.16),
               0 4px 14px color-mix(in srgb, var(--acc) 28%, transparent)!important;
    transition:transform .13s ease, filter .13s ease, box-shadow .2s ease;
  }
  button:active,.go:active,.buy:active,.sell:active,.btn:active,.mult:active,.tab:active{
    transform:scale(.968); filter:brightness(.96);
  }
  button:not([disabled]):hover,.go:not([disabled]):hover,.buy:not([disabled]):hover{
    filter:brightness(1.06);
  }
  button[disabled],.go[disabled],.buy[disabled],.sell[disabled]{
    background:var(--panel2)!important;
    color:var(--muted)!important;
    box-shadow:none!important;
  }
  /* Второстепенные кнопки — контурные, не сплошные */
  .btn.ghost,.ghost,.tab:not(.on),.mult:not(.on){
    background:transparent!important;
    color:var(--muted)!important;
    border:1px solid var(--line)!important;
    box-shadow:none!important;
  }
  .tab.on,.mult.on{
    background:var(--acc)!important;
    color:var(--acc-ink)!important;
    border-color:transparent!important;
  }

  /* Цены и суммы */
  .price,.pr,.bal,.wallet,.money{ color:var(--acc2)!important }

  /* Балансы: знак валюты, ровные цифры и мягкая подложка */
  .bal,.b.bal,.wallet{
    font-variant-numeric:tabular-nums;
    letter-spacing:.3px;
    font-weight:900;
  }
  body .bal,body .b.bal,body .wallet{
    background:color-mix(in srgb, var(--acc) 13%, var(--panel))!important;
    border:1px solid color-mix(in srgb, var(--acc) 28%, var(--line))!important;
    border-radius:999px!important;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.06),0 3px 12px rgba(0,0,0,.18);
  }

  /* Длинный текст не выпирает за карточку — обрезается с многоточием */
  .card .nm,.item .nm,.row .nm,.res .nm,.line .nm,.tile .tt,.tile .tn,
  .stat b,.name,.tname,.cn,.cp{
    min-width:0;overflow:hidden;text-overflow:ellipsis;
  }

  /* Пустые состояния */
  .empty,.ph,.noart{
    color:var(--muted);
    background:color-mix(in srgb, var(--panel) 60%, transparent);
    border:1px dashed var(--line);
    border-radius:var(--radius);
  }

  /* Скроллбары */
  ::-webkit-scrollbar{ width:6px; height:6px }
  ::-webkit-scrollbar-thumb{ background:var(--line); border-radius:99px }
  ::-webkit-scrollbar-track{ background:transparent }

  img{ transition:opacity .3s ease }

  /* ===================== СОЧНОСТЬ ===================== */

  /* Страница мягко проявляется */
  @keyframes __pageIn{ from{opacity:0; transform:translateY(7px)} to{opacity:1; transform:none} }
  body{ animation:__pageIn .42s cubic-bezier(.2,.8,.25,1) both }

  /* Картинки не «выскакивают», а проявляются */
  @keyframes __imgIn{ from{opacity:0; transform:scale(1.04)} to{opacity:1; transform:none} }
  img{ animation:__imgIn .45s cubic-bezier(.2,.8,.25,1) both }

  /* Кнопки: живой отклик на нажатие */
  body button,body .btn,body .go,body .buy,body .sell,body .tab,body .ch,body .bt{
    transition:transform .13s cubic-bezier(.2,.8,.3,1),
               filter .16s ease, box-shadow .22s ease,
               background .2s ease, color .2s ease!important;
    will-change:transform;
  }
  body button:active,body .btn:active,body .go:active,body .buy:active,
  body .sell:active,body .tab:active,body .ch:active,body .bt:active{
    transform:scale(.955)!important;
  }
  /* Радиус нажатия (рисуется скриптом внизу) */
  @keyframes __ripple{ from{transform:scale(0); opacity:.55} to{transform:scale(1); opacity:0} }

  /* Оверлеи: открываются зумом, содержимое подъезжает */
  @keyframes __fadeIn{ from{opacity:0} to{opacity:1} }
  @keyframes __zoomIn{
    from{opacity:0; transform:scale(.86) translateY(14px)}
    to{opacity:1; transform:none}
  }
  .result.on,.flying.on,.modal.on,.sheet.on,.popup.on,.overlay.on{
    animation:__fadeIn .26s ease both;
  }
  .result.on>*,.flying.on>*,.modal.on>*,.sheet.on>*,.popup.on>*{
    animation:__zoomIn .36s cubic-bezier(.2,.9,.3,1.06) both;
  }

  /* Списки и сетки: содержимое подъезжает волной */
  @keyframes __slideIn{ from{opacity:0; transform:translateY(10px)} to{opacity:1; transform:none} }
  .cards>*,.grid>*,.list>*,.rows>*,.ticker>*{
    animation:__slideIn .42s cubic-bezier(.2,.8,.25,1) both;
  }
  .cards>*:nth-child(2n),.grid>*:nth-child(2n),.list>*:nth-child(2n){ animation-delay:.04s }
  .cards>*:nth-child(3n),.grid>*:nth-child(3n),.list>*:nth-child(3n){ animation-delay:.08s }
  .cards>*:nth-child(5n),.grid>*:nth-child(5n),.list>*:nth-child(5n){ animation-delay:.13s }

  /* Переключение вкладок: активная подчёркивается */
  .tab,.ch,.bt{ position:relative; overflow:hidden }
  .tab::after,.ch::after,.bt::after{
    content:"";position:absolute;left:12%;right:12%;bottom:3px;height:2px;border-radius:2px;
    background:currentColor;opacity:0;transform:scaleX(.4);
    transition:opacity .2s ease, transform .25s cubic-bezier(.2,.8,.3,1);
  }
  .tab.on::after,.ch.on::after,.bt.on::after{ opacity:.5; transform:scaleX(1) }

  /* Тост выезжает с лёгким отскоком */
  @keyframes __toastIn{ from{opacity:0; transform:translateY(140%)} to{opacity:1; transform:none} }
  #toast.on{ animation:__toastIn .34s cubic-bezier(.2,.9,.3,1.08) both }

  @media (prefers-reduced-motion: reduce){
    body,img,.cards>*,.grid>*,.list>*,#toast.on,
    .result.on,.flying.on,.modal.on,.sheet.on,.popup.on,
    .result.on>*,.flying.on>*,.modal.on>*{
      animation:none!important;
    }
  }

  /* Кнопка «Назад» в главное приложение — на всех аппках, кроме самого хаба */
  #__back{
    display:flex;align-items:center;gap:10px;padding:11px 15px;
    background:color-mix(in srgb, var(--bg) 82%, transparent);
    border-bottom:1px solid var(--line);position:relative;z-index:60;
    backdrop-filter:blur(10px);
  }
  body #__back button{
    background:var(--panel)!important;color:var(--ink)!important;
    border:1px solid var(--line)!important;box-shadow:none!important;
    border-radius:999px!important;padding:9px 17px!important;
    font-size:13.5px!important;font-weight:800!important;letter-spacing:0;
  }
  body #__back button:active{ background:var(--panel2)!important }
  #__back .__ttl{
    flex:1;text-align:right;font-size:11.5px;color:var(--muted);
    letter-spacing:1.2px;text-transform:uppercase;font-weight:800;
  }

  /* Настройки приложения: кнопка и модалка (одна на все страницы) */
  #__gear{
    position:fixed;right:14px;bottom:18px;z-index:9400;width:46px;height:46px;padding:0!important;
    border-radius:50%!important;border:1px solid var(--line)!important;
    background:var(--panel)!important;color:var(--ink)!important;font-size:20px!important;
    line-height:1!important;box-shadow:0 8px 22px rgba(0,0,0,.45)!important;
  }
  body #__gear:active{ transform:scale(.93)!important }
  .__ov{position:fixed;inset:0;z-index:9600;background:rgba(6,8,12,.74);
    display:none;align-items:flex-end;justify-content:center}
  .__ov.on{display:flex;animation:__fadeIn .2s ease both}
  .__sheet{width:100%;max-width:520px;background:var(--panel);border:1px solid var(--line);
    border-radius:20px 20px 0 0;padding:16px 16px 26px;max-height:82vh;overflow-y:auto;
    animation:__zoomIn .26s cubic-bezier(.2,.9,.3,1.05) both}
  .__hd{display:flex;justify-content:space-between;align-items:center;
    font-size:16px;font-weight:900;margin-bottom:8px}
  .__hd button{width:34px;height:34px;padding:0!important;border-radius:10px!important;
    background:var(--panel2)!important;color:var(--ink)!important;
    border:1px solid var(--line)!important;font-size:17px!important;box-shadow:none!important}
  .__row{display:flex;justify-content:space-between;align-items:center;gap:10px;
    padding:12px 0;border-top:1px solid var(--line)}
  .__row .__t{font-size:13.5px;font-weight:800}
  .__row .__s{font-size:11.5px;color:var(--muted);margin-top:2px;max-width:190px;line-height:1.35}
  .__seg{display:flex;gap:6px;flex:0 0 auto}
  .__seg button{border:1px solid var(--line)!important;background:transparent!important;
    color:var(--muted)!important;border-radius:10px!important;padding:8px 11px!important;
    font-size:12px!important;font-weight:800!important;box-shadow:none!important}
  .__seg button.on{background:var(--acc)!important;color:var(--acc-ink)!important;
    border-color:transparent!important}
  .__sw{border:1px solid var(--line)!important;background:var(--panel2)!important;
    color:var(--muted)!important;border-radius:999px!important;padding:9px 16px!important;
    font-size:12.5px!important;font-weight:800!important;box-shadow:none!important}
  .__sw.on{background:var(--acc)!important;color:var(--acc-ink)!important;
    border-color:transparent!important}
  .__opts{display:flex;flex-wrap:wrap;gap:6px;padding:0 0 12px}
  .__opts button{flex:1 0 30%;border:1px solid var(--line)!important;background:transparent!important;
    color:var(--muted)!important;border-radius:10px!important;padding:9px 6px!important;
    font-size:11.5px!important;font-weight:800!important;box-shadow:none!important}
  .__opts button.on{background:var(--acc)!important;color:var(--acc-ink)!important;
    border-color:transparent!important}
  .__note{font-size:11.5px;color:var(--muted);margin-top:12px;line-height:1.5}

  /* ==================== Получение карты: оверлей ==================== */
  .rv{position:fixed;inset:0;z-index:9700;display:flex;align-items:center;justify-content:center;
    padding:18px;background:rgba(4,6,10,.9);--fxc:#334155;animation:__fadeIn .2s ease both;
    overflow:hidden;touch-action:manipulation}
  .rv.out{opacity:0;transition:opacity .28s ease}
  .rv .rv-rays{position:absolute;left:50%;top:50%;width:150vmax;height:150vmax;
    transform:translate(-50%,-50%);opacity:.2;pointer-events:none;
    background:conic-gradient(from 0deg,transparent 0 5deg,var(--fxc) 5deg 7deg,transparent 7deg 30deg);
    animation:__rvspin 10s linear infinite}
  .rv .rv-flash{position:absolute;left:50%;top:50%;width:20px;height:20px;border-radius:50%;
    transform:translate(-50%,-50%);pointer-events:none;
    background:radial-gradient(circle,#fff,var(--fxc) 45%,transparent 72%);
    animation:__rvflash 1s ease-out both}
  .rv .rv-spark{position:absolute;width:7px;height:7px;border-radius:50%;background:#ffe9a8;
    box-shadow:0 0 12px #ffd166;pointer-events:none;animation:__rvspark 1.4s ease-out both}
  .rv-card{position:relative;z-index:2;width:100%;max-width:330px;border-radius:20px;
    padding:20px;background:var(--panel);border:2px solid var(--fxc);
    box-shadow:0 0 40px -8px var(--fxc),0 18px 50px rgba(0,0,0,.6);
    animation:__rvpop .55s cubic-bezier(.2,.9,.3,1.15) both}
  .rv-card.hi{border-width:3px;
    background:linear-gradient(var(--panel),var(--panel)) padding-box,
      conic-gradient(from 0deg,var(--fxc),#fff,var(--fxc),#111,var(--fxc)) border-box}
  .rv-emoji{font-size:64px;line-height:1;text-align:center;
    filter:drop-shadow(0 6px 18px var(--fxc))}
  .rv-name{text-align:center;font-size:21px;font-weight:900;margin-top:10px;line-height:1.15}
  .rv-rar{text-align:center;font-size:11px;letter-spacing:1.6px;text-transform:uppercase;
    color:var(--fxc);font-weight:900;margin-top:5px}
  .rv-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:14px}
  .rv-stats div{background:var(--panel2);border:1px solid var(--line);border-radius:10px;
    padding:8px 4px;text-align:center}
  .rv-stats b{display:block;font-size:15px;font-weight:900}
  .rv-stats span{font-size:9.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px}
  .rv-block{margin-top:11px;background:var(--panel2);border:1px solid var(--line);
    border-radius:11px;padding:9px 11px}
  .rv-block .t{font-size:9.5px;letter-spacing:1.2px;text-transform:uppercase;
    color:var(--muted);font-weight:900}
  .rv-block .v{font-size:12.5px;margin-top:3px;line-height:1.45}
  .rv-new{position:absolute;top:-11px;left:50%;transform:translateX(-50%);
    background:var(--acc);color:var(--acc-ink);font-size:10px;font-weight:900;
    border-radius:8px;padding:3px 9px;letter-spacing:.6px}
  .rv-tap{margin-top:14px;text-align:center;font-size:11px;color:var(--muted)}
  /* ===== ПРЕМИУМ: карта летит из далека, вспышка, конфетти и огонь ===== */
  .rv.ultra{background:#04070d}
  .rv.ultra .rv-card{animation:__rvfly .78s cubic-bezier(.2,.9,.2,1) both,
      __rvshimmer 3.2s linear .8s infinite}
  .rv.ultra .rv-card::after{content:"";position:absolute;inset:-2px;border-radius:22px;
    padding:2px;pointer-events:none;
    background:conic-gradient(from 0deg,var(--fxc),#fff,var(--fxc),#000,var(--fxc));
    -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
    -webkit-mask-composite:xor;mask-composite:exclude;opacity:.85;
    animation:__rvspin 4.5s linear infinite}
  .rv.ultra .rv-card::before{content:"";position:absolute;inset:-40%;pointer-events:none;
    background:linear-gradient(115deg,transparent 42%,rgba(255,255,255,.5) 50%,transparent 58%);
    animation:__rvshine 2.6s linear infinite}
  .rv .rv-burst{position:absolute;left:50%;top:50%;width:10px;height:10px;border-radius:50%;
    transform:translate(-50%,-50%);pointer-events:none;z-index:1;
    background:radial-gradient(circle,#fff,var(--fxc) 40%,transparent 70%);
    animation:__rvwhite .5s ease-out both}
  .rv .rv-jet{position:absolute;bottom:-30px;width:120px;height:70%;pointer-events:none;z-index:1;
    opacity:.9;filter:blur(1px)}
  .rv .rv-jet.left{left:-20px;transform:rotate(14deg);
    background:linear-gradient(to top,rgba(255,120,0,.0) 0%,#ff8a00 30%,#ffd166 60%,rgba(255,209,102,0) 100%);
    clip-path:polygon(0% 100%,100% 100%,62% 0%,38% 0%);animation:__rvjet 1.6s ease-out both}
  .rv .rv-jet.right{right:-20px;transform:rotate(-14deg);
    background:linear-gradient(to top,rgba(255,120,0,.0) 0%,#ff8a00 30%,#ffd166 60%,rgba(255,209,102,0) 100%);
    clip-path:polygon(0% 100%,100% 100%,62% 0%,38% 0%);animation:__rvjet 1.6s ease-out both}
  .rv .rv-conf{position:absolute;bottom:0;width:9px;height:14px;border-radius:2px;
    pointer-events:none;z-index:3;animation:__rvconf 2.2s cubic-bezier(.2,.6,.4,1) both}
  @keyframes __rvfly{
    0%{transform:scale(.08) translateZ(0);filter:blur(6px) brightness(1.6);opacity:0}
    55%{transform:scale(1.06);filter:blur(0) brightness(1.2);opacity:1}
    100%{transform:scale(1);filter:none}
  }
  @keyframes __rvwhite{0%{transform:translate(-50%,-50%) scale(.2);opacity:0}
    40%{opacity:1}100%{transform:translate(-50%,-50%) scale(60);opacity:0}}
  @keyframes __rvshine{from{transform:translateX(-60%) rotate(0)}to{transform:translateX(60%) rotate(0)}}
  @keyframes __rvshimmer{0%,100%{box-shadow:0 0 34px -6px var(--fxc)}50%{box-shadow:0 0 62px -2px var(--fxc)}}
  @keyframes __rvjet{0%{transform:scaleY(.05) translateY(30%);opacity:0}
    25%{opacity:.95}70%{opacity:.7}100%{transform:scaleY(1) translateY(0);opacity:0}}
  @keyframes __rvconf{0%{transform:translate(0,0) rotate(0);opacity:1}
    100%{transform:translate(var(--cx,0),var(--cy,-320px)) rotate(var(--cr,540deg));opacity:0}}
  @keyframes __rvspin{to{transform:translate(-50%,-50%) rotate(360deg)}}
  @keyframes __rvflash{0%{transform:translate(-50%,-50%) scale(.2);opacity:0}
    35%{opacity:1}100%{transform:translate(-50%,-50%) scale(30);opacity:0}}
  @keyframes __rvpop{from{opacity:0;transform:scale(.82) translateY(16px)}
    to{opacity:1;transform:none}}
  @keyframes __rvspark{0%{transform:translate(0,0) scale(1);opacity:1}
    100%{transform:translate(var(--dx,0),var(--dy,-120px)) scale(.2);opacity:0}}

  /* ==================== Снежная тема ==================== */
  body.theme-snow button,body.theme-snow .btn,body.theme-snow .tab{
    position:relative;overflow:hidden}
  body.theme-snow button::before,body.theme-snow .tab::before{
    content:"\2744";position:absolute;right:4px;top:1px;font-size:9px;opacity:.45;
    color:var(--acc2);pointer-events:none;line-height:1}
  .__snowfront{position:fixed;inset:0;pointer-events:none;overflow:hidden;z-index:3}
  .__snowfront span{position:absolute;top:-40px;color:#eaf6ff;
    animation:__snowfall linear infinite}
  @keyframes __snowfall{to{transform:translateY(115vh) translateX(30px) rotate(200deg);opacity:0}}
</style>
"""

BOOTSTRAP = POLISH + r"""<script>
(function(){
  var tg = window.Telegram ? window.Telegram.WebApp : null;
  var headers = {"X-Telegram-Init-Data": tg ? tg.initData : ""};
  function apply(vars){
    var r = document.documentElement.style;
    for (var k in vars) r.setProperty("--" + k, vars[k]);
  }
  function particles(kind){
    var glyphs = {
      leaf: ["\uD83C\uDF41", "\uD83C\uDF42", "\uD83C\uDF43"],
      star: ["\u2726", "\u2727", "\u00B7"],
      snow: ["\u2744", "\u00B7", "\u2022"],
      spark: ["\u2726", "\u2022", "\u2727"],
      ember: ["\u2022", "\u00B7", "\u2727"]
    }[kind] || ["\u2022"];
    var colors = ["var(--acc)", "var(--acc2)", "var(--muted)"];
    var box = document.createElement("div");
    box.style.cssText = "position:fixed;inset:0;pointer-events:none;overflow:hidden;z-index:0";
    document.body.appendChild(box);
    for (var i = 0; i < 22; i++){
      var s = document.createElement("span");
      s.textContent = glyphs[Math.floor(Math.random() * glyphs.length)];
      s.style.cssText = "position:absolute;top:-48px;opacity:" + (0.08 + Math.random() * 0.3) +
        ";font-size:" + (9 + Math.random() * 13) + "px;color:" + colors[i % colors.length] +
        ";left:" + (Math.random() * 100) + "vw;animation:__fall " + (8 + Math.random() * 12) +
        "s linear " + (Math.random() * 10) + "s infinite";
      box.appendChild(s);
    }
    var st = document.createElement("style");
    st.textContent = "@keyframes __fall{to{transform:translateY(118vh) rotate(400deg);opacity:0}}";
    document.head.appendChild(st);
    if (kind === "snow"){
      document.body.classList.add("theme-snow");
      snowFront();
    }
  }
  function backBar(){
    if (location.pathname === "/hub") return;
    if (document.getElementById("__back")) return;
    var bar = document.createElement("div");
    bar.id = "__back";
    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "‹ Назад";
    btn.onclick = function(){ location.href = "/hub"; };
    bar.appendChild(btn);
    var ttl = document.createElement("div");
    ttl.className = "__ttl";
    ttl.textContent = "Северо-Юг";
    bar.appendChild(ttl);
    document.body.insertBefore(bar, document.body.firstChild);
  }
  /* Волна от нажатия на любой кнопке — «сочный» отклик */
  document.addEventListener("pointerdown", function(e){
    var b = e.target && e.target.closest
      ? e.target.closest("button,.btn,.go,.buy,.sell,.tab,.ch,.bt,.mult")
      : null;
    if (!b || b.disabled) return;
    try{
      var r = b.getBoundingClientRect();
      if (getComputedStyle(b).position === "static") b.style.position = "relative";
      b.style.overflow = "hidden";
      var size = Math.max(r.width, r.height) * 2.2;
      var s = document.createElement("span");
      s.style.cssText = "position:absolute;border-radius:50%;pointer-events:none;z-index:3;" +
        "background:radial-gradient(circle,rgba(255,255,255,.5),transparent 68%);" +
        "width:" + size + "px;height:" + size + "px;" +
        "left:" + (e.clientX - r.left - size / 2) + "px;" +
        "top:" + (e.clientY - r.top - size / 2) + "px;" +
        "animation:__ripple .55s ease-out forwards";
      b.appendChild(s);
      setTimeout(function(){ s.remove(); }, 580);
    }catch(err){}
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
  }, {passive:true});


  /* ---------- Настройки приложения ---------- */
  var PREFS = null;
  var GEAR_SKIP = ["/proto_dungeon", "/proto_yugi"];

  function prefsRequest(method, body, done){
    var opts = {method: method, headers: headers};
    if (body){
      opts.headers = {"X-Telegram-Init-Data": headers["X-Telegram-Init-Data"],
                      "Content-Type": "application/json"};
      opts.body = JSON.stringify(body);
    }
    fetch("/api/prefs", opts).then(function(r){ return r.json(); }).then(function(d){
      if (d && d.prefs){ PREFS = d; }
      if (done) done(d || {});
    }).catch(function(){ if (done) done({}); });
  }

  function gearButton(){
    if (document.getElementById("__gear")) return;
    if (GEAR_SKIP.indexOf(location.pathname) >= 0) return;
    prefsRequest("GET", null, function(d){
      if (!d || !d.prefs) return;
      PREFS = d;
      var btn = document.createElement("button");
      btn.id = "__gear";
      btn.type = "button";
      btn.textContent = "\u2699";
      btn.setAttribute("aria-label", "Настройки");
      btn.onclick = openSettings;
      document.body.appendChild(btn);
    });
  }

  function segRow(key, title, sub, value){
    return '<div class="__row"><div><div class="__t">' + title + '</div>' +
      '<div class="__s">' + sub + '</div></div><div class="__seg" data-key="' + key + '">' +
      '<button data-v="wheel" class="' + (value === "wheel" ? "on" : "") + '">Колесо</button>' +
      '<button data-v="reel" class="' + (value === "reel" ? "on" : "") + '">Лента</button>' +
      '</div></div>';
  }

  function paintSettings(ov){
    var d = PREFS || {};
    var p = d.prefs || {fx: true, view_classic: "wheel", view_crystal: "wheel", pinned: ""};
    var pin = d.pinned_card;
    ov.innerHTML = '<div class="__sheet">' +
      '<div class="__hd"><span>\u2699 Настройки</span>' +
      '<button id="__gear-x">\u00d7</button></div>' +
      '<div class="__row"><div><div class="__t">Эффекты карточек</div>' +
      '<div class="__s">Вспышка, лучи и обводка при открытии редкой карты</div></div>' +
      '<button class="__sw' + (p.fx ? " on" : "") + '" id="__sw-fx">' +
      (p.fx ? "Вкл" : "Выкл") + '</button></div>' +
      segRow("view_classic", "Классическая рулетка", "Как показывать приз",
             p.view_classic || "wheel") +
      segRow("view_crystal", "Кристальная рулетка", "Колесо или лента",
             p.view_crystal || "wheel") +
      '<div class="__row"><div><div class="__t">Карточка в профиле</div>' +
      '<div class="__s">' +
      (pin ? ("Сейчас: " + pin.name) : "Витрина пуста — повесь карту из коллекции") +
      '</div></div>' +
      (pin ? '<button class="__sw" id="__pin-clear">Снять</button>' : "") +
      '</div>' +
      '<div class="__note">Эти настройки хранятся в профиле и действуют ' +
      'во всех мини-аппках.</div></div>';
    var x = document.getElementById("__gear-x");
    if (x) x.onclick = function(){ ov.classList.remove("on"); };
    var fxBtn = document.getElementById("__sw-fx");
    if (fxBtn) fxBtn.onclick = function(){
      var next = !p.fx;
      fxBtn.className = "__sw" + (next ? " on" : "");
      fxBtn.textContent = next ? "Вкл" : "Выкл";
      p.fx = next;
      prefsRequest("POST", {fx: next}, function(saved){
        if (saved && saved.prefs) p.fx = saved.prefs.fx;
        if (window.__onPrefs) window.__onPrefs(saved && saved.prefs);
      });
    };
    ov.querySelectorAll(".__seg").forEach(function(box){
      var key = box.dataset.key;
      box.querySelectorAll("button").forEach(function(b){
        b.onclick = function(){
          box.querySelectorAll("button").forEach(function(o){ o.className = ""; });
          b.className = "on";
          var patch = {};
          patch[key] = b.dataset.v;
          prefsRequest("POST", patch, function(saved){
            if (window.__onPrefs) window.__onPrefs(saved && saved.prefs);
          });
        };
      });
    });
    var clear = document.getElementById("__pin-clear");
    if (clear) clear.onclick = function(){
      prefsRequest("POST", {pinned: ""}, function(){
        ov.classList.remove("on");
        if (window.__onPrefs) window.__onPrefs(null);
      });
    };
  }

  function openSettings(){
    var ov = document.getElementById("__gear-ov");
    if (!ov){
      ov = document.createElement("div");
      ov.id = "__gear-ov";
      ov.className = "__ov";
      ov.onclick = function(e){ if (e.target === ov) ov.classList.remove("on"); };
      document.body.appendChild(ov);
    }
    ov.classList.add("on");
    prefsRequest("GET", null, function(){ paintSettings(ov); });
  }

  /* ---------- Получение карты: оверлей с анимацией ---------- */
  function rvEsc(s){
    return String(s == null ? "" : s).replace(/[<>&"]/g, function(c){
      return {"<":"&lt;",">":"&gt;","&":"&amp;",'"':"&quot;"}[c];
    });
  }
  function rvShow(card){
    return new Promise(function(resolve){
      var fx = card.fx || {};
      var lvl = Number(fx.level) || 0;
      var color = fx.color || "#334155";
      var ov = document.createElement("div");
      ov.className = "rv";
      ov.style.setProperty("--fxc", color);
      var html = "";
      var ultra = lvl >= 4;
      if (ultra){ ov.className = "rv ultra"; }
      if (lvl >= 3) html += '<div class="rv-rays"></div><div class="rv-flash"></div>';
      if (ultra){
        // белая вспышка на весь экран
        html += '<div class="rv-burst"></div>';
        // огонь из двух «труб» по краям снизу
        html += '<div class="rv-jet left"></div><div class="rv-jet right"></div>';
        // конфетти: вылетают из обоих нижних углов
        var palette = [color, "#ffffff", "#ffd166", "#ff8a00"];
        for (var c = 0; c < 34; c++){
          var side = c % 2 === 0 ? -1 : 1;
          var cx = side * (40 + Math.random() * 260);
          var cy = -(180 + Math.random() * 320);
          var rot = (side * (240 + Math.random() * 720)) | 0;
          html += '<div class="rv-conf" style="' +
            (side < 0 ? "left:6px;" : "right:6px;") +
            "background:" + palette[c % palette.length] + ";" +
            "--cx:" + cx + "px;--cy:" + cy + "px;--cr:" + rot + "deg;" +
            'animation-delay:' + (0.15 + Math.random() * 0.5).toFixed(2) + 's"></div>';
        }
        // частицы цвета редкости прямо из карты
        for (var i = 0; i < 26; i++){
          var dx = Math.round(Math.random() * 320 - 160);
          var dy = Math.round(-60 - Math.random() * 240);
          html += '<div class="rv-spark" style="left:' + (44 + Math.random() * 12) +
            "%;top:" + (42 + Math.random() * 14) + "%;--dx:" + dx + "px;--dy:" + dy +
            'px;background:' + color + ';box-shadow:0 0 14px ' + color + ';' +
            'animation-delay:' + (Math.random() * 0.6).toFixed(2) + 's"></div>';
        }
      }
      html += '<div class="rv-card' + (lvl >= 4 ? " hi" : "") + '" style="--fxc:' + color + '">' +
        (card.is_new ? '<div class="rv-new">НОВАЯ</div>' : "") +
        '<div class="rv-emoji">' + (card.emoji || "?") + "</div>" +
        '<div class="rv-name">' + rvEsc(card.name) + "</div>" +
        '<div class="rv-rar">' + rvEsc(card.rarity_title || "") + "</div>" +
        '<div class="rv-stats">' +
          "<div><b>" + (card.hp || 0) + "</b><span>HP</span></div>" +
          "<div><b>" + (card.atk || 0) + "</b><span>атака</span></div>" +
          "<div><b>" + (card.points || 0) + "</b><span>очки</span></div>" +
        "</div>" +
        (card.ability
          ? '<div class="rv-block"><div class="t">Способность</div><div class="v"><b>' +
            rvEsc(card.ability) + "</b>" +
            (card.ability_text ? "<br>" + rvEsc(card.ability_text) : "") + "</div></div>"
          : "") +
        (card.description
          ? '<div class="rv-block"><div class="t">Описание</div><div class="v">' +
            rvEsc(card.description) + "</div></div>"
          : "") +
        '<div class="rv-tap">' + (lvl >= 3 ? "\u2728 " : "") + "нажми, чтобы продолжить</div>" +
        "</div>";
      ov.innerHTML = html;
      document.body.appendChild(ov);
      if (tg && tg.HapticFeedback){
        try{
          if (lvl >= 3) tg.HapticFeedback.notificationOccurred("success");
          tg.HapticFeedback.impactOccurred(lvl >= 4 ? "heavy" : "light");
          if (lvl >= 4) setTimeout(function(){
            try { tg.HapticFeedback.impactOccurred("heavy"); } catch(e){}
          }, 520);
        }catch(e){}
      }
      var closed = false;
      function close(){
        if (closed) return;
        closed = true;
        ov.classList.add("out");
        setTimeout(function(){ ov.remove(); resolve(); }, 240);
      }
      ov.onclick = close;
      setTimeout(close, lvl >= 4 ? 4200 : lvl >= 3 ? 2400 : 1600);
    });
  }
  function revealCards(cards, done){
    if (!cards || !cards.length){ if (done) done(); return; }
    var index = 0;
    function next(){
      if (index >= cards.length){ if (done) done(); return; }
      rvShow(cards[index++]).then(next);
    }
    next();
  }
  window.__revealCards = revealCards;
  window.__revealOne = function(card, done){ revealCards([card], done); };

  /* ---------- Снег: крупные размытые хлопья поверх экрана ---------- */
  function snowFront(){
    if (document.querySelector(".__snowfront")) return;
    var box = document.createElement("div");
    box.className = "__snowfront";
    document.body.appendChild(box);
    for (var i = 0; i < 9; i++){
      var flake = document.createElement("span");
      flake.textContent = "\u2744";
      flake.style.cssText =
        "left:" + (Math.random() * 100).toFixed(1) + "vw;" +
        "font-size:" + (14 + Math.random() * 26).toFixed(0) + "px;" +
        "filter:blur(" + (Math.random() * 5).toFixed(1) + "px);" +
        "opacity:" + (0.16 + Math.random() * 0.34).toFixed(2) + ";" +
        "animation-duration:" + (16 + Math.random() * 16).toFixed(1) + "s;" +
        "animation-delay:" + (Math.random() * 12).toFixed(1) + "s";
      box.appendChild(flake);
    }
  }

  backBar();
  gearButton();
  fetch("/api/theme", {headers: headers}).then(function(r){ return r.json(); }).then(function(d){
    if (d && d.vars) apply(d.vars);
    particles(d && d.particles);
  }).catch(function(){});
})();
</script>
"""


TG_SCRIPT = '<script src="https://telegram.org/js/telegram-web-app.js"></script>'

INIT_KEEP = """<script>
/* initData теряется при переходах внутри мини-аппки: Telegram отдаёт его
   только на старте. Держим копию в sessionStorage и возвращаем на место
   сразу после загрузки SDK — иначе после перехода любая ручка отвечает 401. */
(function(){
  try{
    var tg = window.Telegram && window.Telegram.WebApp;
    if (!tg) return;
    if (tg.initData){
      window.__TG_INIT = tg.initData;
      try { sessionStorage.setItem("tginit", tg.initData); } catch(e){}
      return;
    }
    var saved = null;
    try { saved = sessionStorage.getItem("tginit"); } catch(e){}
    if (saved){
      window.__TG_INIT = saved;
      try { tg.initData = saved; } catch(e){}
    }
  }catch(e){}
})();
</script>"""


def inject(html: str) -> str:
    """Подмешивает тему, новый стиль и частицы в любую мини-аппку.

    Заодно возвращает initData после переходов внутри мини-аппки: страницы
    ходят друг к другу по ссылкам, а Telegram отдаёт данные только на старте.
    """
    if TG_SCRIPT in html and "sessionStorage" not in html:
        html = html.replace(TG_SCRIPT, TG_SCRIPT + INIT_KEEP, 1)
    if "</body>" in html:
        return html.replace("</body>", BOOTSTRAP + "</body>", 1)
    return html + BOOTSTRAP
