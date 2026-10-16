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
