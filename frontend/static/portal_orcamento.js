// Portal público do Orçamento (Fase 197) — sem login, mesma receita de
// portal_contrato.js (CSP bloqueia <script> inline, por isso arquivo à parte).
(function () {
  const partes = location.pathname.split("/").filter(Boolean);
  const token = partes[partes.length - 1];
  const API = location.origin + "/api/v1/portal/orcamento";
  const app = document.getElementById("app");

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function fmtMoeda(v) {
    return (v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
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
      <h2 style="margin:0;font-weight:600;">Não foi possível abrir este link</h2>
      <p class="texto-suave" style="max-width:420px;">${escapeHtml(mensagem)}</p>
    </div>`;
  }

  const ROTULO_STATUS = {
    enviado: ["Aguardando sua decisão", ""],
    aprovado: ["Aprovado", "aprovado"],
    recusado: ["Recusado", "recusado"],
  };

  async function renderizar() {
    let orcamento;
    try {
      orcamento = await chamar(`/${token}`);
    } catch (erro) {
      if (erro.codigo === "link_expirado") return telaErro("Este link expirou. Entre em contato com seu vendedor na Alphafitus para receber um novo link.");
      if (erro.codigo === "orcamento_indisponivel") return telaErro("Este orçamento ainda não está disponível — fale com seu contato na Alphafitus.");
      return telaErro("Este link é inválido ou já foi revogado. Confira se copiou o endereço completo, ou peça um novo link ao seu contato na Alphafitus.");
    }

    const [rotulo, classeSelo] = ROTULO_STATUS[orcamento.status] || [orcamento.status, ""];
    const criadoEm = new Date(orcamento.criado_em);
    const validade = new Date(criadoEm.getTime() + orcamento.validade_dias * 86400000);

    const linhasItens = orcamento.itens.map((it) => `
      <tr>
        <td>${escapeHtml(it.item_descricao)}</td>
        <td class="num">${it.quantidade} ${escapeHtml(it.unidade || "")}</td>
        <td class="num">${fmtMoeda(it.preco_unitario)}</td>
        <td class="num">${fmtMoeda(it.quantidade * it.preco_unitario)}</td>
      </tr>`).join("");

    app.innerHTML = `
      <h1 class="titulo">${escapeHtml(orcamento.numero)} <span class="selo-status ${classeSelo}">${rotulo}</span></h1>
      <p class="subtitulo">${escapeHtml(orcamento.cliente ? orcamento.cliente.razao_social : "")} — válido até ${validade.toLocaleDateString("pt-BR")}</p>

      <div class="cartao">
        <h2>Itens da proposta</h2>
        <a href="${API}/${token}/pdf" target="_blank" class="botao-secundario" style="margin-bottom:16px;">📄 Ver proposta completa (PDF)</a>
        <table class="itens">
          <thead><tr><th>Produto</th><th class="num">Qtd.</th><th class="num">Preço unit.</th><th class="num">Subtotal</th></tr></thead>
          <tbody>${linhasItens}</tbody>
          <tfoot><tr class="linha-total"><td colspan="3">Valor total</td><td class="num">${fmtMoeda(orcamento.valor_total)}</td></tr></tfoot>
        </table>
        ${orcamento.condicoes_texto ? `<p style="margin-top:16px;"><strong>Condições:</strong> ${escapeHtml(orcamento.condicoes_texto)}</p>` : ""}
        ${orcamento.observacoes ? `<p><strong>Observações:</strong> ${escapeHtml(orcamento.observacoes)}</p>` : ""}
      </div>

      ${orcamento.status === "enviado" ? `
        <div class="cartao" style="text-align:center;">
          <h2>Sua decisão</h2>
          <p class="texto-suave" style="margin-bottom:16px;">Confira os itens e o valor acima. Você pode aprovar esta proposta (gera automaticamente seu pedido) ou recusar.</p>
          <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">
            <button type="button" class="botao" id="btn-aprovar">Aprovar proposta →</button>
            <button type="button" class="botao-perigo" id="btn-recusar">Recusar</button>
          </div>
        </div>
      ` : ""}

      ${orcamento.status === "aprovado" ? `
        <div class="cartao" style="text-align:center;">
          <h2>Proposta aprovada</h2>
          <p>Aprovada em ${new Date(orcamento.aprovado_em).toLocaleString("pt-BR")}. Seu pedido já foi gerado — nossa equipe vai entrar em contato para os próximos passos.</p>
        </div>
      ` : ""}

      ${orcamento.status === "recusado" ? `
        <div class="cartao" style="text-align:center;">
          <h2>Proposta recusada</h2>
          <p>Recusada em ${new Date(orcamento.recusado_em).toLocaleString("pt-BR")}.${orcamento.motivo_recusa ? ` Motivo: ${escapeHtml(orcamento.motivo_recusa)}` : ""}</p>
        </div>
      ` : ""}
    `;

    const btnAprovar = document.getElementById("btn-aprovar");
    if (btnAprovar) {
      btnAprovar.addEventListener("click", async () => {
        if (!confirm("Confirma a aprovação desta proposta? Isso vai gerar o pedido automaticamente.")) return;
        try {
          btnAprovar.disabled = true;
          btnAprovar.textContent = "Aprovando…";
          await chamar(`/${token}/aprovar`, { method: "POST", body: {} });
          renderizar();
        } catch (erro) {
          alert(erro.message || "Não foi possível aprovar.");
          btnAprovar.disabled = false;
          btnAprovar.textContent = "Aprovar proposta →";
        }
      });
    }
    const btnRecusar = document.getElementById("btn-recusar");
    if (btnRecusar) {
      btnRecusar.addEventListener("click", async () => {
        const motivo = prompt("Se quiser, conte o motivo (opcional):") || "";
        if (!confirm("Confirma que deseja recusar esta proposta?")) return;
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
