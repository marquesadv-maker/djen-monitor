/* Dashboard financeiro — leitura apenas. Nenhuma ação desta tela grava
   no Projuris; a conciliação e a baixa vivem na aba ao lado.

   Os gráficos são SVG próprio, sem biblioteca externa: o painel roda numa
   rede interna e não depende de CDN para desenhar. */

const CORES = {
  entrada: '#1B2A4A',
  saida: '#B08A3E',
  total: '#2E7D53',
  pago: '#2E7D53',
  vencido: '#C9A227',
  a_vencer: '#1B2A4A',
  nao_conciliado: '#B3261E',
};

const SVG = 'http://www.w3.org/2000/svg';

function el(tag, attrs = {}, texto = '') {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (texto) node.textContent = texto;
  return node;
}

function vazio(mensagem, acao = '') {
  return `<div class="estado"><strong>${mensagem}</strong>${acao}</div>`;
}

// ── Carga ────────────────────────────────────────────────────────────

function filtrosAtuais() {
  const params = new URLSearchParams();
  document.querySelectorAll('[data-filtro]').forEach((campo) => {
    if (campo.value) params.set(campo.dataset.filtro, campo.value);
  });
  return params;
}

async function carregar() {
  let dados;
  try {
    const resposta = await fetch(`/financeiro/conciliacao/api/painel?${filtrosAtuais()}`,
      { credentials: 'same-origin' });
    dados = await resposta.json();
    if (!resposta.ok) throw new Error(dados.mensagem || dados.erro || 'falha');
  } catch (erro) {
    document.getElementById('kpis').innerHTML =
      `<div class="kpi"><div class="rotulo">Erro</div><div class="nota">${erro.message}
       — tente recarregar a página.</div></div>`;
    return;
  }

  desenharKpis(dados);
  desenharMensal(dados);
  desenharStatus(dados);
  desenharRanking('top-clientes', dados.top_clientes, 'entrada', dados.vazio);
  desenharRanking('top-fornecedores', dados.top_fornecedores, 'saida', dados.vazio);
  preencherFiltros(dados.opcoes_filtro);
  document.getElementById('atualizacao').textContent =
    `Última atualização: ${dados.atualizado_em}`;
}

// ── KPIs ─────────────────────────────────────────────────────────────

function desenharKpis(dados) {
  const k = dados.kpis || {};
  const cartao = (rotulo, valor, nota = '', negativo = false) => `
    <div class="kpi">
      <div class="rotulo">${rotulo}</div>
      <div class="valor ${negativo ? 'negativo' : ''}">${valor}</div>
      ${nota ? `<div class="nota">${nota}</div>` : ''}
    </div>`;

  if (dados.vazio) {
    const texto = dados.filtros_ativos
      ? 'Nenhum lançamento para os filtros selecionados'
      : 'Nada conciliado ainda';
    document.getElementById('kpis').innerHTML =
      cartao('Entrada', '—') + cartao('Saída', '—') +
      cartao('Saldo', '—') + cartao('% Margem', '—', texto);
    return;
  }

  document.getElementById('kpis').innerHTML =
    cartao('Entrada', k.entrada, `${k.conciliados} lançamento(s) conciliado(s)`) +
    cartao('Saída', k.saida) +
    cartao('Saldo', k.saldo, '', k.saldo_negativo) +
    cartao('% Margem', k.margem,
      k.margem === '—' ? 'Sem entrada no período' : '');
}

// ── Entrada × Saída mensal ───────────────────────────────────────────

function desenharMensal(dados) {
  const alvo = document.getElementById('grafico-mensal');
  if (!dados.mensal.length) {
    alvo.innerHTML = vazio(dados.filtros_ativos
      ? 'Nenhum lançamento para os filtros selecionados'
      : 'Importe um extrato e concilie para ver a série mensal.');
    return;
  }

  const L = 760, A = 240, margem = { t: 18, r: 16, b: 34, l: 74 };
  const larguraUtil = L - margem.l - margem.r;
  const alturaUtil = A - margem.t - margem.b;
  const maximo = Math.max(...dados.mensal.flatMap((m) =>
    [m.entrada_centavos, m.saida_centavos, Math.abs(m.total_centavos)])) || 1;
  const escala = (v) => alturaUtil - (v / maximo) * alturaUtil;

  const svg = el('svg', { viewBox: `0 0 ${L} ${A}`, width: '100%', role: 'img' });
  const grupo = el('g', { transform: `translate(${margem.l},${margem.t})` });

  for (let i = 0; i <= 4; i += 1) {
    const y = (alturaUtil / 4) * i;
    grupo.appendChild(el('line', {
      x1: 0, x2: larguraUtil, y1: y, y2: y, stroke: 'rgba(27,42,74,.12)',
    }));
    grupo.appendChild(el('text', {
      x: -8, y: y + 4, 'text-anchor': 'end', 'font-size': 10, fill: '#1B2A4A',
    }, reais(maximo * (1 - i / 4))));
  }

  const passo = larguraUtil / dados.mensal.length;
  const larguraBarra = Math.min(26, passo / 3);
  const pontos = [];

  dados.mensal.forEach((mes, i) => {
    const centro = passo * i + passo / 2;
    [['entrada_centavos', CORES.entrada, -larguraBarra - 2],
     ['saida_centavos', CORES.saida, 2]].forEach(([campo, cor, deslocamento]) => {
      const valor = mes[campo];
      const y = escala(valor);
      grupo.appendChild(el('rect', {
        x: centro + deslocamento, y, width: larguraBarra,
        height: Math.max(alturaUtil - y, 0), fill: cor, rx: 2,
      }));
      if (valor > 0) {
        // Contorno bege: o rótulo de uma barra baixa cai sobre a barra
        // vizinha e sumiria, por ser da mesma cor.
        grupo.appendChild(el('text', {
          x: centro + deslocamento + larguraBarra / 2, y: y - 4,
          'text-anchor': 'middle', 'font-size': 9, fill: '#1B2A4A',
          stroke: '#F2EFE6', 'stroke-width': 3, 'paint-order': 'stroke',
        }, reais(valor)));
      }
    });
    pontos.push(`${centro},${escala(Math.abs(mes.total_centavos))}`);
    grupo.appendChild(el('text', {
      x: centro, y: alturaUtil + 18, 'text-anchor': 'middle',
      'font-size': 11, fill: '#1B2A4A',
    }, mes.rotulo));
  });

  grupo.appendChild(el('polyline', {
    points: pontos.join(' '), fill: 'none', stroke: CORES.total,
    'stroke-width': 2, 'stroke-linejoin': 'round',
  }));

  svg.appendChild(grupo);
  alvo.replaceChildren(svg);
}

// ── Status de recebimentos (rosca) ───────────────────────────────────

function desenharStatus(dados) {
  const alvo = document.getElementById('grafico-status');
  const fatias = dados.status_recebimentos || [];
  if (!fatias.length) {
    alvo.innerHTML = vazio('Sem títulos a receber no período.');
    return;
  }

  const total = fatias.reduce((soma, f) => soma + f.valor_centavos, 0);
  const svg = el('svg', { viewBox: '0 0 430 180', width: '100%', role: 'img' });
  const cx = 88, cy = 90, raio = 66, espessura = 26;
  let angulo = -Math.PI / 2;

  fatias.forEach((fatia) => {
    const fracao = fatia.valor_centavos / total;
    const fim = angulo + fracao * Math.PI * 2;
    svg.appendChild(el('path', {
      d: arco(cx, cy, raio, angulo, fim),
      stroke: CORES[fatia.cor] || CORES.entrada,
      'stroke-width': espessura, fill: 'none',
    }));
    angulo = fim;
  });

  svg.appendChild(el('text', {
    x: cx, y: cy - 2, 'text-anchor': 'middle', 'font-size': 12,
    fill: '#1B2A4A', 'font-weight': 700,
  }, 'A receber'));
  svg.appendChild(el('text', {
    x: cx, y: cy + 14, 'text-anchor': 'middle', 'font-size': 11, fill: '#1B2A4A',
  }, reais(total)));

  fatias.forEach((fatia, i) => {
    const y = 34 + i * 26;
    svg.appendChild(el('rect', {
      x: 184, y: y - 9, width: 11, height: 11, rx: 2,
      fill: CORES[fatia.cor] || CORES.entrada,
    }));
    svg.appendChild(el('text', { x: 202, y, 'font-size': 11, fill: '#1B2A4A' },
      `${fatia.rotulo} — ${fatia.valor}`));
  });

  alvo.replaceChildren(svg);
}

function arco(cx, cy, r, inicio, fim) {
  const x1 = cx + r * Math.cos(inicio), y1 = cy + r * Math.sin(inicio);
  const x2 = cx + r * Math.cos(fim), y2 = cy + r * Math.sin(fim);
  const grande = fim - inicio > Math.PI ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${grande} 1 ${x2} ${y2}`;
}

// ── Rankings ─────────────────────────────────────────────────────────

function desenharRanking(id, itens, cor, painelVazio) {
  const alvo = document.getElementById(id);
  if (!itens || !itens.length) {
    alvo.innerHTML = vazio(painelVazio
      ? 'Sem dados para exibir.'
      : 'Nenhum item conciliado nesta categoria.');
    return;
  }
  const maximo = Math.max(...itens.map((i) => i.valor_centavos)) || 1;
  alvo.innerHTML = itens.map((item) => `
    <div class="barra-linha">
      <span class="nome" title="${escapar(item.nome)}">${escapar(item.nome)}</span>
      <span class="trilho">
        <span class="preenchimento ${cor === 'saida' ? 'saida' : ''}"
              style="width:${(item.valor_centavos / maximo) * 100}%"></span>
      </span>
      <span class="valor">${item.valor}</span>
    </div>`).join('');
}

// ── Filtros ──────────────────────────────────────────────────────────

function preencherFiltros(opcoes) {
  if (!opcoes) return;
  const preencher = (id, valores, rotulo = (v) => v) => {
    const campo = document.getElementById(id);
    const atual = campo.value;
    const primeira = campo.options[0];
    campo.replaceChildren(primeira);
    valores.forEach((v) => {
      const valor = typeof v === 'object' ? v.valor : v;
      const opcao = document.createElement('option');
      opcao.value = valor;
      opcao.textContent = typeof v === 'object' ? v.rotulo : rotulo(v);
      campo.appendChild(opcao);
    });
    campo.value = atual;
    campo.disabled = valores.length === 0;
  };

  preencher('f-ano', opcoes.ano);
  preencher('f-mes', opcoes.mes);
  preencher('f-banco', opcoes.banco);
  preencher('f-forma', opcoes.forma_pagamento);
  preencher('f-cat-entrada', opcoes.categoria_entrada);
  preencher('f-cat-saida', opcoes.categoria_saida);

  document.getElementById('sem-banco').hidden = opcoes.banco.length > 0;
  document.getElementById('sem-forma').hidden = opcoes.forma_pagamento.length > 0;
  document.getElementById('sem-categoria').hidden =
    opcoes.categoria_entrada.length > 0 || opcoes.categoria_saida.length > 0;
}

// ── Utilidades ───────────────────────────────────────────────────────

function reais(centavos) {
  const valor = Math.abs(centavos) / 100;
  if (valor >= 1000000) return `R$ ${(valor / 1000000).toFixed(1).replace('.', ',')} Mi`;
  return `R$ ${valor.toLocaleString('pt-BR', { minimumFractionDigits: 2,
    maximumFractionDigits: 2 })}`;
}

function escapar(texto) {
  const div = document.createElement('div');
  div.textContent = texto ?? '';
  return div.innerHTML;
}

// ── Início ───────────────────────────────────────────────────────────

document.querySelectorAll('[data-filtro]').forEach((campo) => {
  campo.addEventListener('change', carregar);
});

document.getElementById('limpar-filtros').addEventListener('click', () => {
  document.querySelectorAll('[data-filtro]').forEach((campo) => { campo.value = ''; });
  carregar();
});

carregar();
