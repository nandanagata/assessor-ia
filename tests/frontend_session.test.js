// Testa as ações reais de app.js com DOM e fetch locais, sem navegador ou rede.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

class Elemento {
  constructor() {
    this.style = {};
    this.classList = { toggle() {} };
    this.eventos = {};
    this.filhos = [];
    this.disabled = false;
    this.value = "";
    this.textContent = "";
  }
  addEventListener(nome, callback) { this.eventos[nome] = callback; }
  appendChild(filho) { this.filhos.push(filho); }
  focus() {}
  remove() {}
  set innerHTML(texto) { this.html = texto; this.filhos = []; }
  get innerHTML() { return this.html ?? this.textContent; }
}

function ambiente(fetch) {
  const elementos = new Map();
  for (const id of ["thread", "thread-empty", "composer", "pergunta", "enviar", "session-id", "reset-session", "status-dot", "hint"]) {
    elementos.set(id, new Elemento());
  }
  const storage = new Map([["assistente_session_id", "sessao-anterior"]]);
  const contexto = vm.createContext({
    window: { location: { protocol: "http:", origin: "http://localhost:8000" }, crypto: {} },
    crypto: { randomUUID: () => "sessao-nova" },
    localStorage: { getItem: (k) => storage.get(k), setItem: (k, v) => storage.set(k, v) },
    document: { getElementById: (id) => elementos.get(id), createElement: () => new Elemento() },
    console: { warn() {}, error() {} },
    fetch,
  });
  contexto.window.crypto = contexto.crypto;
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../app/frontend/app.js"), "utf8"), contexto);
  return { contexto, elementos, storage };
}

async function testar() {
  let a = ambiente(async () => { throw new Error("Falha simulada"); });
  await vm.runInContext("iniciarNovaSessao()", a.contexto);
  assert.equal(a.storage.get("assistente_session_id"), "sessao-anterior");
  assert.match(a.elementos.get("hint").textContent, /conversa foi mantida/);
  assert.equal(a.elementos.get("enviar").disabled, false);
  console.log("OK: falha de conexão mantém a sessão e permite repetir");

  a = ambiente(async () => ({ ok: false, status: 500 }));
  await vm.runInContext("iniciarNovaSessao()", a.contexto);
  assert.equal(a.storage.get("assistente_session_id"), "sessao-anterior");
  assert.match(a.elementos.get("hint").textContent, /500/);
  console.log("OK: erro HTTP ao encerrar não descarta a conversa");

  a = ambiente(async () => ({
    ok: false, status: 503,
    json: async () => ({ detail: "Não foi possível salvar o resumo da conversa. Tente novamente." }),
  }));
  await vm.runInContext("iniciarNovaSessao()", a.contexto);
  assert.equal(a.storage.get("assistente_session_id"), "sessao-anterior");
  assert.match(a.elementos.get("hint").textContent, /Não foi possível salvar o resumo/);
  assert.match(a.elementos.get("hint").textContent, /conversa foi mantida/);
  console.log("OK: mensagem de falha ao salvar é exibida e mantém a sessão");

  const chamadas = [];
  a = ambiente(async (url) => {
    chamadas.push(url);
    return { ok: true, json: async () => ({ resumo: "Conversa resumida." }) };
  });
  await vm.runInContext("iniciarNovaSessao()", a.contexto);
  assert.equal(a.storage.get("assistente_session_id"), "sessao-nova");
  assert.equal(vm.runInContext("sessionId", a.contexto), "sessao-nova");
  assert.match(chamadas[0], /sessions\/sessao-anterior\/encerrar/);
  console.log("OK: encerramento concluído atualiza o ID na memória e no armazenamento");

  let liberar;
  const pedidos = [];
  a = ambiente((url, opcoes) => {
    pedidos.push({ url, opcoes });
    return new Promise((resolve) => { liberar = resolve; });
  });
  a.elementos.get("pergunta").value = "Oi";
  const enviar = a.elementos.get("composer").eventos.submit;
  const pendente = enviar({ preventDefault() {} });
  await enviar({ preventDefault() {} });
  await vm.runInContext("iniciarNovaSessao()", a.contexto);
  assert.equal(pedidos.length, 1);
  assert.equal(a.elementos.get("reset-session").disabled, true);
  liberar({ ok: true, json: async () => ({ resposta: "Olá" }) });
  await pendente;
  assert.equal(a.elementos.get("reset-session").disabled, false);
  console.log("OK: envio em andamento impede duplicação e troca de sessão");
}

testar().catch((erro) => { console.error(erro); process.exitCode = 1; });
