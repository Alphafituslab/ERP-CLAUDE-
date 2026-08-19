/* =========================================================================
   TEMA VISUAL 3D — comportamento adicional (Alphafitus OS)
   =========================================================================
   Carregado DEPOIS de app.js, como script independente — não importa nada
   dele, não chama nenhuma função dele, só ouve eventos no `document` (a
   mesma técnica de delegação que o próprio app.js já usa) para:

     1) inclinar levemente em 3D o cartão sob o mouse (cartões de KPI, de
        atalho do painel e o cartão de login), usando as variáveis CSS
        --rx/--ry que tema-3d.css já espera;
     2) mostrar o texto completo da marca (histórico de fases) num
        tooltip nativo ao passar o mouse, já que o CSS só o trunca
        visualmente.

   Como cada tela é redesenhada inteira via `app.innerHTML = ...` (ver
   app.js), nenhum listener pode ser preso a um elemento específico — por
   isso tudo aqui é delegação no `document`, que sobrevive a qualquer
   re-render.
   ========================================================================= */
(function () {
  "use strict";

  var SELETOR_INCLINAVEL = ".cartao-stat, .kpi, .cartao-login";
  var reduzirMovimento = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (!reduzirMovimento && window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    document.addEventListener("mousemove", function (e) {
      var alvo = e.target.closest ? e.target.closest(SELETOR_INCLINAVEL) : null;
      if (!alvo) return;
      var r = alvo.getBoundingClientRect();
      var px = (e.clientX - r.left) / r.width;  // 0..1
      var py = (e.clientY - r.top) / r.height;  // 0..1
      var max = 6; // graus máximos de inclinação — sutil, não "gamer"
      var rx = (px - 0.5) * max * 2;
      var ry = (py - 0.5) * -max * 2;
      alvo.style.setProperty("--rx", rx.toFixed(2) + "deg");
      alvo.style.setProperty("--ry", ry.toFixed(2) + "deg");
    });

    document.addEventListener(
      "mouseout",
      function (e) {
        var alvo = e.target.closest ? e.target.closest(SELETOR_INCLINAVEL) : null;
        if (!alvo) return;
        // Só reseta quando o mouse realmente sai do cartão (não a cada
        // filho sobrevoado dentro dele).
        if (alvo.contains(e.relatedTarget)) return;
        alvo.style.setProperty("--rx", "0deg");
        alvo.style.setProperty("--ry", "0deg");
      },
      true
    );
  }

  // Tooltip nativo com o texto completo da marca (o CSS só corta a
  // exibição com um degradê — o texto inteiro continua no DOM).
  document.addEventListener(
    "mouseover",
    function (e) {
      var alvo = e.target.closest ? e.target.closest(".barra-lateral .marca small") : null;
      if (!alvo || alvo.title) return;
      alvo.title = alvo.textContent.trim();
    },
    true
  );
})();
