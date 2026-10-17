"""Общий стиль мини-аппок: тема игрока, частицы и единый дизайн элементов.

Страницы не переписываются. К каждой подмешивается слой оформления: он
подменяет CSS-переменные и приводит кнопки, карточки и заголовки к одному
аккуратному виду — только через переменные темы, без вшитых цветов.
"""

from __future__ import annotations

POLISH = r"""<style>
  :root{ --radius:14px; --edge:0 6px 20px rgba(0,0,0,.20); }
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

  backBar();
  fetch("/api/theme", {headers: headers}).then(function(r){ return r.json(); }).then(function(d){
    if (d && d.vars) apply(d.vars);
    particles(d && d.particles);
  }).catch(function(){});
})();
</script>
"""


def inject(html: str) -> str:
    """Подмешивает тему, новый стиль и частицы в любую мини-аппку."""
    if "</body>" in html:
        return html.replace("</body>", BOOTSTRAP + "</body>", 1)
    return html + BOOTSTRAP
