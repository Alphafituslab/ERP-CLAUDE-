// Portal público do convite de Agenda (Fase 199) — sem login, mesma receita
// de portal_orcamento.js (CSP bloqueia <script> inline, por isso arquivo à parte).
(function () {
  const partes = location.pathname.split("/").filter(Boolean);
  const token = partes[partes.length - 1];
  const API = location.origin + "/api/v1/portal/agenda-convite";
  const app = document.getElementById("app");

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function fmtDataHora(iso) {
    return new Date(iso).toLocaleString("pt-BR", { dateStyle: "full", timeStyle: "short" });
  }

  async function chamar(caminho, opcoes) {
    opcoes = opcoes || {};
    const resp = await fetch(API + caminho, {
      method: opcoes.method || "GET",
      headers: { "Content-Type": "application/json" },
      body: opcoes.body !== undefined ? JSON.stringify(opcoes.body) : undefined,
    });
    let dados = {};
    try { dados = await resp.json(); } catch (e) { /* corpo vazio */ }
    if (!resp.ok) {
      const erro = new Error(dados.mensagem || `Erro ${resp.status}`);
      erro.codigo = dados.erro;
      throw erro;
    }
    return dados;
  }

  function telaErro(mensagem) {
    app.innerHTML = `<div class="tela-central">
      <div style="font-size:36px;">🔒</div>
      <h2 style="margin:0;font-weight:600;">Não foi possível abrir este convite</h2>
      <p class="texto-suave" style="max-width:420px;">${escapeHtml(mensagem)}</p>
    </div>`;
  }

  const ROTULO_STATUS = {
    pendente: ["Aguardando sua resposta", ""],
    aceito: ["Você confirmou presença", "aceito"],
    recusado: ["Você recusou", "recusado"],
  };

  async function renderizar() {
    let convite;
    try {
      convite = await chamar(`/${token}`);
    } catch (erro) {
      if (erro.codigo === "compromisso_indisponivel") return telaErro("Este compromisso não está mais disponível — pode ter sido cancelado.");
      return telaErro("Este link é inválido. Confira se copiou o endereço completo, ou peça um novo convite a quem te chamou.");
    }

    const [rotulo, classeSelo] = ROTULO_STATUS[convite.status] || [convite.status, ""];
    const evento = convite.evento;

    app.innerHTML = `
      <h1 class="titulo">${escapeHtml(evento.titulo)} <span class="selo-status ${classeSelo}">${rotulo}</span></h1>
      <p class="subtitulo">Convidado por ${escapeHtml(convite.convidado_por_nome || "")}</p>

      <div class="cartao">
        <h2>Detalhes do compromisso</h2>
        <div class="linha">🗓️ <span>${escapeHtml(fmtDataHora(evento.data_inicio))}</span></div>
        ${evento.local_texto ? `<div class="linha">📍 <span>${escapeHtml(evento.local_texto)}</span></div>` : ""}
        ${evento.link_video ? `<div class="linha">📹 <a href="${escapeHtml(evento.link_video)}" target="_blank" rel="noopener">Entrar na videochamada</a></div>` : ""}
        ${evento.descricao ? `<div class="linha">📝 <span>${escapeHtml(evento.descricao)}</span></div>` : ""}
      </div>

      ${convite.status === "pendente" ? `
        <div class="cartao" style="text-align:center;">
          <h2>Você vai participar?</h2>
          <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">
            <button type="button" class="botao" id="btn-aceitar">Aceitar convite →</button>
            <button type="button" class="botao-perigo" id="btn-recusar">Recusar</button>
          </div>
        </div>
      ` : ""}

      ${convite.status === "aceito" ? `
        <div class="cartao" style="text-align:center;">
          <p>Sua presença está confirmada. Se mudar de ideia, pode recusar aqui a qualquer momento.</p>
          <button type="button" class="botao-perigo" id="btn-recusar">Recusar agora</button>
        </div>
      ` : ""}

      ${convite.status === "recusado" ? `
        <div class="cartao" style="text-align:center;">
          <p>Você recusou este convite.${convite.motivo_recusa ? ` Motivo: ${escapeHtml(convite.motivo_recusa)}` : ""}</p>
          <button type="button" class="botao" id="btn-aceitar">Aceitar mesmo assim →</button>
        </div>
      ` : ""}
    `;

    const btnAceitar = document.getElementById("btn-aceitar");
    if (btnAceitar) {
      btnAceitar.addEventListener("click", async () => {
        try {
          btnAceitar.disabled = true;
          btnAceitar.textContent = "Confirmando…";
          await chamar(`/${token}/aceitar`, { method: "POST", body: {} });
          renderizar();
        } catch (erro) {
          alert(erro.message || "Não foi possível confirmar.");
          btnAceitar.disabled = false;
          btnAceitar.textContent = "Aceitar convite →";
        }
      });
    }
    const btnRecusar = document.getElementById("btn-recusar");
    if (btnRecusar) {
      btnRecusar.addEventListener("click", async () => {
        const motivo = prompt("Se quiser, conte o motivo (opcional):") || "";
        try {
          btnRecusar.disabled = true;
          await chamar(`/${token}/recusar`, { method: "POST", body: { motivo } });
          renderizar();
        } catch (erro) {
          alert(erro.message || "Não foi possível recusar.");
          btnRecusar.disabled = false;
        }
      });
    }
  }

  renderizar();
})();
