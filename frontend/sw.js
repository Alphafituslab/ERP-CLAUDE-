/*
 * Service Worker do Alphafitus OS (Fase 38 — Responsividade e App
 * Instalável para Celular/Tablet).
 *
 * Escopo deliberadamente pequeno: só cuida do "app shell" (o HTML/CSS/JS
 * que desenham a tela), nunca de dado de negócio. Duas responsabilidades:
 *
 *   1. Junto com `manifest.json`, é um dos dois requisitos técnicos para o
 *      navegador oferecer "Adicionar à tela inicial"/"Instalar app" no
 *      celular ou tablet — depois de instalado, abre em janela própria
 *      (sem a barra de endereço do navegador), com o ícone da Alphafitus.
 *   2. Deixa o app SHELL abrir mesmo com internet ruim ou momentaneamente
 *      offline (útil pra quem usa o App de Vendas em campo, Fase 36) —
 *      mas around isso, é rede-primeiro: sempre tenta buscar a versão mais
 *      nova antes de recorrer ao cache, para nunca travar alguém numa
 *      versão antiga do sistema sem perceber.
 *
 * Qualquer chamada para `/api/...` NUNCA passa por aqui (ver o `return`
 * antecipado no handler de `fetch`) — dado de negócio (saldo de estoque,
 * pedido, notificação etc.) tem que ser sempre buscado de verdade, ou
 * falhar de forma clara sem internet; jamais uma cópia desatualizada
 * silenciosa vinda de um cache, o que seria perigoso numa fábrica.
 */

const NOME_DO_CACHE = "alphafitus-shell-v1";

const ARQUIVOS_DO_SHELL = [
  "/",
  "/static/app.js",
  "/static/styles.css",
  "/manifest.json",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (evento) => {
  evento.waitUntil(
    caches
      .open(NOME_DO_CACHE)
      .then((cache) => cache.addAll(ARQUIVOS_DO_SHELL))
      .catch(() => {
        /* Falhar em pré-cachear não deve impedir a instalação do
           service worker — o app continua funcionando 100% normal via
           rede, só sem o benefício extra de abrir offline. */
      })
  );
  self.skipWaiting();
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches
      .keys()
      .then((nomes) => Promise.all(nomes.filter((n) => n !== NOME_DO_CACHE).map((n) => caches.delete(n))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (evento) => {
  const url = new URL(evento.request.url);

  if (url.pathname.startsWith("/api/")) return; // nunca intercepta a API
  if (evento.request.method !== "GET") return;

  evento.respondWith(
    fetch(evento.request)
      .then((resposta) => {
        const copia = resposta.clone();
        caches.open(NOME_DO_CACHE).then((cache) => cache.put(evento.request, copia)).catch(() => {});
        return resposta;
      })
      .catch(() => caches.match(evento.request))
  );
});
