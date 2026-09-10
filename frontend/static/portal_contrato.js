// Fase 169 (endurecimento) — extraido de portal_contrato.html: a CSP nova
// (script-src 'self', ver app/__init__.py) bloqueia <script> inline.
(function () {
  const partes = location.pathname.split("/").filter(Boolean);
  const token = partes[partes.length - 1];
  const API = location.origin + "/api/v1/portal/contrato";
  const app = document.getElementById("app");

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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

  async function renderizar() {
    let contrato;
    try {
      contrato = await chamar(`/${token}`);
    } catch (erro) {
      if (erro.codigo === "link_expirado") return telaErro("Este link expirou. Entre em contato com seu vendedor na Alphafitus para receber um novo link.");
      if (erro.codigo === "contrato_indisponivel") return telaErro("Este contrato ainda não está disponível para leitura/assinatura — fale com seu contato na Alphafitus.");
      return telaErro("Este link é inválido ou já foi revogado. Confira se copiou o endereço completo, ou peça um novo link ao seu contato na Alphafitus.");
    }

    app.innerHTML = `
      <h1 class="titulo">${escapeHtml(contrato.numero)} <span class="selo-status">${contrato.status === "assinado" ? "Assinado" : "Aguardando sua assinatura"}</span></h1>
      <p class="subtitulo">${escapeHtml(contrato.cliente_razao_social)}</p>

      <div class="cartao">
        <h2>Documento</h2>
        <a href="${API}/${token}/pdf" target="_blank" class="botao-secundario" style="margin-bottom:16px;">📄 Ver contrato completo (PDF)</a>
        <div class="texto-contrato">${escapeHtml(contrato.texto_resolvido)}</div>
      </div>

      ${contrato.status === "aguardando_assinatura" ? `
        <div class="cartao" id="cartao-assinar" style="text-align:center;">
          <h2>Assinatura eletrônica</h2>
          <p class="texto-suave" style="margin-bottom:16px;">Leia o contrato acima com atenção. Pra assinar eletronicamente, informe seus dados abaixo — isso gera o documento definitivo com data, hora e um código de verificação únicos, salvo também no cadastro da Alphafitus.</p>
          <div style="text-align:left;max-width:420px;margin:0 auto;">
            <div class="campo"><label>Seu nome completo</label><input type="text" id="assinatura-nome"></div>
            <div class="campo"><label>Seu CPF</label><input type="text" id="assinatura-cpf" placeholder="000.000.000-00"></div>
            <div class="campo"><label>Seu e-mail (opcional)</label><input type="text" id="assinatura-email"></div>
          </div>
          <button type="button" class="botao" id="btn-assinar" style="margin-top:10px;">Assinar eletronicamente →</button>
        </div>
      ` : ""}

      ${contrato.status === "assinado" && contrato.assinatura_eletronica ? `
        <div class="cartao" style="text-align:center;">
          <h2>Documento assinado</h2>
          <p>Assinado eletronicamente por <strong>${escapeHtml(contrato.assinatura_eletronica.assinante_nome)}</strong> em ${new Date(contrato.assinatura_eletronica.assinado_em).toLocaleString("pt-BR")}.</p>
          <p class="texto-suave" style="word-break:break-all;">Código de verificação (hash SHA-256): ${escapeHtml(contrato.assinatura_eletronica.hash_pdf_sha256)}</p>
        </div>
      ` : ""}
    `;

    const btnAssinar = document.getElementById("btn-assinar");
    if (btnAssinar) {
      btnAssinar.addEventListener("click", async () => {
        const nome = document.getElementById("assinatura-nome").value.trim();
        const cpf = document.getElementById("assinatura-cpf").value.trim();
        const email = document.getElementById("assinatura-email").value.trim();
        if (!nome) { alert("Informe seu nome."); return; }
        if (cpf.replace(/\D/g, "").length !== 11) { alert("Informe um CPF válido."); return; }
        if (!confirm("Confirma a assinatura eletrônica deste contrato? Depois disso ele fica travado até uma nova versão ser aberta.")) return;
        try {
          btnAssinar.disabled = true;
          btnAssinar.textContent = "Assinando…";
          await chamar(`/${token}/assinar`, { method: "POST", body: { nome, cpf, email } });
          renderizar();
        } catch (erro) {
          alert(erro.message || "Não foi possível assinar.");
          btnAssinar.disabled = false;
          btnAssinar.textContent = "Assinar eletronicamente →";
        }
      });
    }
  }

  renderizar();
})();
