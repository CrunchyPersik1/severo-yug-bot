"""Общий стиль мини-аппок: тема игрока + падающие частицы.

Страницы не переписываются. К каждой подмешивается маленький скрипт: он
спрашивает активную тему и подменяет CSS-переменные прямо на месте.
"""

from __future__ import annotations

POLISH = r"""<style>
  html{-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
  body{background:var(--bg);color:var(--ink)}
  .card,.item,.lot,.box,.slot,.tile,.unit,.cell{
    animation:__rise .5s cubic-bezier(.2,.8,.25,1) both;
    transition:transform .16s cubic-bezier(.2,.8,.25,1),box-shadow .2s ease,border-color .2s ease;
  }
  .card:nth-child(2n),.item:nth-child(2n),.lot:nth-child(2n){animation-delay:.035s}
  .card:nth-child(3n),.item:nth-child(3n),.lot:nth-child(3n){animation-delay:.07s}
  .card:nth-child(5n),.item:nth-child(5n),.lot:nth-child(5n){animation-delay:.11s}
  @keyframes __rise{from{opacity:0;transform:translateY(12px) scale(.985)}to{opacity:1;transform:none}}
  .card:active,.item:active,.lot:active{transform:scale(.975)}
  button,.go,.btn,.buy,.sell,.mult,.tab{
    transition:transform .13s ease,filter .13s ease,box-shadow .22s ease,background .2s ease;
  }
  button:active,.go:active,.btn:active,.buy:active,.sell:active,.mult:active,.tab:active{transform:scale(.972)}
  button:not([disabled]):hover,td:not([disabled]):hover{filter:brightness(1.07)}
  .go,.buy,.sell,.btn:not(.ghost):not(.close){
    background-image:linear-gradient(135deg,var(--acc2),var(--acc));
    background-size:100% 100%;
  }
  ::-webkit-scrollbar{width:6px;height:6px}
  ::-webkit-scrollbar-thumb{background:var(--line);border-radius:99px}
  ::-webkit-scrollbar-track{background:transparent}
  header,.top{border-color:var(--line)}
  .price,.pr,.bal,.wallet{color:var(--acc2)}
  a,button{-webkit-tap-highlight-color:transparent}
</style>
"""

BOOTSTRAP = POLISH + r"""<script>
(function(){
  var tg = window.Telegram ? window.Telegram.WebApp : null;
  var headers = {"X-Telegram-Init-Data": tg ? tg.initData : ""};
  function apply(vars){
    var r = document.documentElement.style;
    for (var k in vars) r.setProperty("--" + k, vars[k]);
    document.body.style.background = "var(--bg)";
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
    for (var i = 0; i < 24; i++){
      var s = document.createElement("span");
      s.textContent = glyphs[Math.floor(Math.random() * glyphs.length)];
      s.style.cssText = "position:absolute;top:-48px;opacity:" + (0.10 + Math.random() * 0.38) +
        ";font-size:" + (9 + Math.random() * 14) + "px;color:" + colors[i % colors.length] +
        ";left:" + (Math.random() * 100) + "vw;animation:__fall " + (7 + Math.random() * 11) +
        "s linear " + (Math.random() * 9) + "s infinite";
      box.appendChild(s);
    }
    var st = document.createElement("style");
    st.textContent = "@keyframes __fall{to{transform:translateY(118vh) rotate(420deg);opacity:0}}" +
      " body>*{position:relative;z-index:1} .top,header{position:sticky;z-index:9}";
    document.head.appendChild(st);
  }
  fetch("/api/theme", {headers: headers}).then(function(r){ return r.json(); }).then(function(d){
    if (d && d.vars) apply(d.vars);
    particles(d && d.particles);
  }).catch(function(){});
})();
</script>
"""


def inject(html: str) -> str:
    """Подмешивает тему и частицы в любую мини-аппку."""
    if "</body>" in html:
        return html.replace("</body>", BOOTSTRAP + "</body>", 1)
    return html + BOOTSTRAP
