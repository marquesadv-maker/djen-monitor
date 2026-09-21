/* Aba de conciliação.

   Cada item mostra o porquê do match, não só a porcentagem: é o que o
   usuário precisa para defender a baixa depois. A gravação é item a item
   e, enquanto houver pendência de implantação, a resposta do servidor é
   uma simulação — a tela diz isso em vez de fingir que gravou.

   `pedir`/`escapar`/`aviso`/`erro`/`ok` vêm de comum.js, carregado antes
   deste arquivo pelo template. */

// ── Importação ───────────────────────────────────────────────────────

async function enviarArquivo(inputId, caminho, alvoId, extras = {}) {
  const input = document.getElementById(inputId);
  const alvo = document.getElementById(alvoId);
  if (!input.files.length) {
    alvo.innerHTML = erro('Escolha um arquivo antes.');
    return;
  }

  const dados = new FormData();
  dados.append('arquivo', input.files[0]);
  Object.entries(extras).forEach(([k, v]) => v && dados.append(k, v));

  alvo.innerHTML = '<div class="esqueleto"></div>';
  try {
    const resposta = await pedir(caminho, { method: 'POST', body: dados });

    if (resposta.precisa_mapeamento) {
      alvo.innerHTML = aviso(resposta.mensagem)
        + `<table><thead><tr>${resposta.colunas.map((c) =>
            `<th>${escapar(c)}</th>`).join('')}</tr></thead><tbody>${
          resposta.amostra.slice(1).map((linha) =>
            `<tr>${linha.map((c) => `<td>${escapar(c)}</td>`).join('')}</tr>`).join('')
        }</tbody></table>`;
      return;
    }

    alvo.innerHTML = ok(resposta.resumo)
      + (resposta.conta ? aviso(`Conta: ${resposta.conta}`) : '')
      + (resposta.avisos || []).map(aviso).join('')
      + (resposta.reimportacao && resposta.reimportacao.detectada
        ? aviso(resposta.reimportacao.mensagem) : '');
  } catch (e) {
    alvo.innerHTML = erro(e.message);
  }
}

// ── Conciliação ──────────────────────────────────────────────────────

async function conciliar() {
  const resumo = document.getElementById('resumo');
  resumo.innerHTML = '<div class="bloco"><div class="esqueleto"></div>'
    + '<div class="esqueleto" style="width:60%"></div></div>';
  try {
    mostrarResultados(await pedir('/conciliar', { method: 'POST' }));
  } catch (e) {
    resumo.innerHTML = `<div class="bloco">${erro(e.message)}</div>`;
  }
}

// Preenche resumo + os três blocos a partir do resultado da conciliação —
// tanto de uma conciliação recém-rodada quanto de uma sessão restaurada.
function mostrarResultados(dados) {
  mostrarResumo(dados);
  preencherBloco('automatico', dados.automatico);
  preencherBloco('sugestao', dados.sugestao);
  preencherBloco('divergencia', dados.divergencia);
}

function mostrarResumo(dados) {
  const r = dados.resumo;
  const tipos = Object.entries(r.por_tipo_divergencia || {})
    .map(([tipo, qtd]) => `${qtd} ${tipo.replace(/_/g, ' ')}`).join(' · ');
  document.getElementById('resumo').innerHTML = `
    <div class="bloco">
      <h2>Resultado</h2>
      <p>
        ${r.total_lancamentos} lançamento(s): <strong>${r.automatico.qtd}</strong>
        conciliado(s) automaticamente (${r.automatico_valor}),
        <strong>${r.sugestao.qtd}</strong> sugestão(ões) (${r.sugestao_valor}) e
        <strong>${r.divergencia.qtd}</strong> divergência(s) (${r.divergencia_valor}).
        Taxa automática: ${String(r.taxa_automatica_pct).replace('.', ',')}%.
      </p>
      ${tipos ? `<p class="meta">Divergências: ${escapar(tipos)}</p>` : ''}
      <p class="meta" style="font-size:12px">
        Limiar automático ${dados.regras.limiar_automatico} · tolerância de
        ${dados.regras.tolerancia_dias} dia(s) e
        ${String(dados.regras.tolerancia_valor_pct).replace('.', ',')}% de valor.
        ${dados.regras._ajuste ? escapar(dados.regras._ajuste) : ''}
      </p>
    </div>`;
}

function preencherBloco(nome, itens) {
  const bloco = document.getElementById(`bloco-${nome}`);
  const lista = document.getElementById(`lista-${nome}`);
  bloco.hidden = false;
  document.getElementById(`conta-${nome}`).textContent = `(${itens.length})`;

  if (!itens.length) {
    lista.innerHTML = '<div class="estado">Nenhum item nesta faixa.</div>';
    return;
  }
  lista.innerHTML = itens.map(cartao).join('');
  lista.querySelectorAll('[data-acao]').forEach((botao) => {
    botao.addEventListener('click', () => acao(botao.dataset.acao, botao.dataset.id));
  });
}

function cartao(item) {
  const podeOperar = ['operacao', 'gravacao'].includes(window.NIVEL_CONCILIACAO);
  const podeGravar = window.NIVEL_CONCILIACAO === 'gravacao';
  const titulo = item.titulo;

  const acoes = [];
  if (item.status === 'sugestao' && podeOperar && !item.aprovado) {
    acoes.push(`<button class="compacto" data-acao="aprovar" data-id="${item.id}">Aceitar sugestão</button>`);
  }
  if (item.aprovado && podeGravar) {
    acoes.push(`<button class="compacto" data-acao="baixa" data-id="${item.id}">Gravar baixa</button>`);
  }
  if (item.status === 'automatico' && podeOperar && !item.aprovado) {
    acoes.push(`<button class="compacto secundario" data-acao="aprovar" data-id="${item.id}">Confirmar para gravação</button>`);
  }

  // Candidatos só interessam onde a escolha ainda está em aberto; num
  // match por documento exato, listá-los é ruído.
  const candidatos = item.status !== 'automatico' && (item.candidatos || []).length
    ? `<div class="meta">Outros candidatos: ${item.candidatos.map((c) =>
        `${escapar(c.id)} (${c.valor}, vence ${c.vencimento})`).join(' · ')}</div>`
    : '';

  return `
    <div class="item ${item.status}">
      <div class="linha">
        <span class="lancamento">${item.data} — ${escapar(item.descricao) || '(sem histórico)'}</span>
        <span class="valor ${item.tipo === 'debito' ? 'debito' : ''}">${item.valor}</span>
      </div>
      <div class="meta">
        <span class="etiqueta ${item.status}">${item.status}</span>
        ${item.aprovado ? '<span class="etiqueta aprovado">aprovado</span>' : ''}
        ${item.confianca}% · ${escapar(item.regra)}
        ${item.tipo_divergencia ? ` · ${escapar(item.tipo_divergencia.replace(/_/g, ' '))}` : ''}
      </div>
      <div class="porque">${escapar(item.explicacao)}</div>
      ${titulo ? `<div class="meta">Título ${escapar(titulo.id)} · ${escapar(titulo.contraparte) || '—'}
        · ${titulo.valor} · vence ${titulo.vencimento} · ${escapar(titulo.status)}</div>` : ''}
      ${candidatos}
      <div class="acoes" data-resposta="${item.id}">${acoes.join('')}</div>
    </div>`;
}

// ── Ações ────────────────────────────────────────────────────────────

async function acao(tipo, lancamentoId) {
  const alvo = document.querySelector(`[data-resposta="${lancamentoId}"]`);
  const corpo = { lancamento_id: lancamentoId };

  try {
    if (tipo === 'aprovar') {
      await pedir('/aprovar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(corpo),
      });
      alvo.innerHTML = '<span class="etiqueta aprovado">aprovado</span>'
        + (window.NIVEL_CONCILIACAO === 'gravacao'
          ? ` <button class="compacto" data-acao="baixa" data-id="${lancamentoId}">Gravar baixa</button>`
          : '');
      alvo.querySelectorAll('[data-acao]').forEach((b) =>
        b.addEventListener('click', () => acao(b.dataset.acao, b.dataset.id)));
      return;
    }

    const dados = await pedir('/baixa', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(corpo),
    });

    if (dados.simulacao) {
      alvo.innerHTML = aviso(dados.mensagem.replace(/\*\*/g, ''))
        + `<div class="meta">Pendências: ${dados.pendencias.length}</div>`;
    } else {
      alvo.innerHTML = ok(`Baixa gravada no título ${dados.titulo_id}.`);
    }
  } catch (e) {
    alvo.innerHTML = erro(e.message);
  }
}

// ── Início ───────────────────────────────────────────────────────────

document.getElementById('enviar-extrato').addEventListener('click', () =>
  enviarArquivo('arquivo-extrato', '/extrato', 'estado-extrato'));

document.getElementById('enviar-titulos').addEventListener('click', () =>
  enviarArquivo('arquivo-titulos', '/titulos', 'estado-titulos',
    { tipo: document.getElementById('tipo-titulos').value }));

document.getElementById('conciliar').addEventListener('click', conciliar);

document.getElementById('limpar').addEventListener('click', async () => {
  await pedir('/limpar', { method: 'POST' }).catch(() => {});
  window.location.reload();
});

// Recarregar a página não descarta o que já foi conciliado nem as
// aprovações dadas: o estado continua na sessão e é relido aqui.
(async function restaurar() {
  try {
    const dados = await pedir('/resultados');
    if (dados.conciliado) mostrarResultados(dados);
  } catch (e) {
    /* sessão nova ou sem permissão de leitura: a tela fica no estado inicial */
  }
}());
