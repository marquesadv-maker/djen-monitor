/* Utilitários compartilhados pelas duas telas da aba de Conciliação
   (dashboard.html e conciliacao.html) — carregado antes de dashboard.js
   e conciliacao.js nos respectivos templates.

   Escopo é a aba de Conciliação só: a aba de NFS-e tem os seus próprios
   equivalentes, deliberadamente separados (cópia é preferível a
   acoplamento entre abas, ver README do módulo). */

const BASE = '/financeiro/conciliacao/api';

async function pedir(caminho, opcoes = {}) {
  const resposta = await fetch(`${BASE}${caminho}`,
    { credentials: 'same-origin', ...opcoes });
  const dados = await resposta.json().catch(() => ({}));
  if (!resposta.ok) {
    throw new Error(dados.erro || dados.mensagem || `Falha (${resposta.status}).`);
  }
  return dados;
}

function escapar(texto) {
  const div = document.createElement('div');
  div.textContent = texto ?? '';
  return div.innerHTML;
}

function aviso(texto) { return `<div class="aviso">${escapar(texto)}</div>`; }
function erro(texto) { return `<div class="erro-bloco">${escapar(texto)}</div>`; }
function ok(texto) { return `<div class="ok-bloco">${escapar(texto)}</div>`; }
