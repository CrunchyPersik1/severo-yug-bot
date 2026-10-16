"""Общий стиль мини-аппок: тема игрока + падающие частицы.

Страницы не переписываются. К каждой подмешивается маленький скрипт: он
спрашивает активную тему и подменяет CSS-переменные прямо на месте.
"""

from __future__ import annotations

BOOTSTRAP = r"""<script>
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
