/* Aba de NFS-e.

   Fluxo fixo: tarefa → prévia → aprovação → transmissão. O botão de
   transmitir só acorda depois de uma prévia sem bloqueio, e mesmo assim
   pede confirmação explícita daquela nota: em Araguaína a NFS-e não se
   cancela por web service, só por substituição no portal. */

const BASE = '/financeiro/nfse/api';
let tarefaSelecionada = null;

async function pedir(caminho, opcoes = {}) {
  const resposta = await fetch(`${BASE}${caminho}`,
    { credentials: 'same-origin', ...opcoes });
  const dados = await resposta.json().catch(() => ({}));
  if (!resposta.ok) {
    const detalhe = (dados.bloqueios || []).join(' · ');
    throw new Error([dados.erro || dados.mensagem || `Falha (${resposta.status}).`,
      detalhe].filter(Boolean).join(' — '));
  }
  return dados;
}

function escapar(texto) {
  const div = document.createElement('div');
  div.textContent = texto ?? '';
  return div.innerHTML;
}

const aviso = (t) => `<div class="aviso">${escapar(t)}</div>`;
const erro = (t) => `<div class="erro-bloco">${escapar(t)}</div>`;
const ok = (t) => `<div class="ok-bloco">${escapar(t)}</div>`;

// ── Tarefas ──────────────────────────────────────────────────────────

async function importarTarefas() {
  const input = document.getElementById('arquivo-tarefas');
  const alvo = document.getElementById('estado-tarefas');
  if (!input.files.length) {
    alvo.innerHTML = erro('Escolha o arquivo exportado do Projuris.');
    return;
  }

  const dados = new FormData();
  dados.append('arquivo', input.files[0]);
  alvo.innerHTML = '<div class="esqueleto"></div>';

  try {
    const resposta = await pedir('/tarefas', { method: 'POST', body: dados });
    alvo.innerHTML = ok(resposta.resumo) + (resposta.avisos || []).map(aviso).join('');
    listarTarefas(resposta.tarefas);
  } catch (e) {
    alvo.innerHTML = erro(e.message);
  }
}

function listarTarefas(tarefas) {
  const alvo = document.getElementById('lista-tarefas');
  if (!tarefas.length) {
    alvo.innerHTML = '<div class="estado">Nenhuma tarefa de nota fiscal no arquivo.</div>';
    return;
  }

  alvo.innerHTML = `
    <table>
      <thead>
        <tr><th>Tarefa</th><th>Tomador</th><th>Documento</th><th class="num">Valor</th>
            <th>Competência</th><th>Contrato</th><th></th></tr>
      </thead>
      <tbody>
        ${tarefas.map((t) => `
          <tr>
            <td>${escapar(t.tarefa)}</td>
            <td>${escapar(t.tomador_nome) || '—'}</td>
            <td>${escapar(t.tomador_documento) || '—'}</td>
            <td class="num">${t.valor}</td>
            <td>${t.competencia || '—'}</td>
            <td>${escapar(t.referencia_interna) || '—'}</td>
            <td>
              <button class="compacto" data-tarefa="${escapar(t.tarefa)}">Preparar nota</button>
              ${t.faltando.length
                ? `<div class="meta" style="color:#B3261E;font-size:11px">falta: ${
                    escapar(t.faltando.join(', '))}</div>`
                : ''}
            </td>
          </tr>`).join('')}
      </tbody>
    </table>`;

  alvo.querySelectorAll('[data-tarefa]').forEach((botao) => {
    botao.addEventListener('click', () => {
      tarefaSelecionada = tarefas.find((t) => t.tarefa === botao.dataset.tarefa);
      prepararFormulario();
    });
  });
}

function prepararFormulario() {
  document.getElementById('bloco-previa').hidden = false;
  document.getElementById('resultado-previa').innerHTML = '';
  document.getElementById('transmitir').disabled = true;

  if (tarefaSelecionada && tarefaSelecionada.competencia) {
    const [mes, ano] = tarefaSelecionada.competencia.split('/');
    document.getElementById('p-competencia').value = `${ano}-${mes}`;
  }
  document.getElementById('p-discriminacao').value = '';
  document.getElementById('bloco-previa').scrollIntoView({ behavior: 'smooth' });
}

// ── Prévia ───────────────────────────────────────────────────────────

function corpoDaNota() {
  const valor = (id) => document.getElementById(id).value.trim();
  return {
    tarefa: tarefaSelecionada ? tarefaSelecionada.tarefa : '',
    tomador: {
      endereco: {
        logradouro: valor('p-logradouro'),
        bairro: valor('p-bairro'),
        municipio_ibge: valor('p-municipio'),
        uf: valor('p-uf').toUpperCase(),
        cep: valor('p-cep'),
      },
    },
    servico: {
      competencia: valor('p-competencia'),
      discriminacao: valor('p-discriminacao'),
      item_lc116: valor('p-item'),
      iss_retido: document.getElementById('p-iss-retido').checked,
    },
  };
}

async function montarPrevia() {
  const alvo = document.getElementById('resultado-previa');
  alvo.innerHTML = '<div class="esqueleto" style="height:120px"></div>';
  document.getElementById('transmitir').disabled = true;

  try {
    const dados = await pedir('/previa', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(corpoDaNota()),
    });

    alvo.innerHTML =
      (dados.alertas_sigilo || []).map(aviso).join('')
      + (dados.bloqueios || []).map(erro).join('')
      + `<pre class="previa">${escapar(dados.previa)}</pre>`
      + `<table><tbody>
          <tr><th>Valor bruto</th><td class="num">${dados.valores.bruto}</td></tr>
          <tr><th>Base de cálculo</th><td class="num">${dados.valores.base_calculo}</td></tr>
          <tr><th>ISS${dados.valores.iss_retido ? ' (retido)' : ''}</th>
              <td class="num">${dados.valores.regime_fixo
                ? 'regime fixo por profissional' : dados.valores.iss}</td></tr>
          <tr><th>Líquido a receber</th><td class="num">${dados.valores.liquido}</td></tr>
        </tbody></table>`;

    const podeGravar = window.NIVEL_NFSE === 'gravacao';
    document.getElementById('transmitir').disabled = !(dados.pode_transmitir && podeGravar);
    if (dados.pode_transmitir && !podeGravar) {
      alvo.insertAdjacentHTML('beforeend',
        aviso('A nota passou na validação, mas seu nível nesta aba não permite transmitir.'));
    }
  } catch (e) {
    alvo.innerHTML = erro(e.message);
  }
}

// ── Transmissão ──────────────────────────────────────────────────────

async function transmitir() {
  const alvo = document.getElementById('resultado-previa');
  const confirmado = window.confirm(
    'Confirma a transmissão desta nota?\n\n'
    + 'Em Araguaína a NFS-e não pode ser cancelada por web service — '
    + 'só substituída pelo portal. Confira tomador, valor e competência antes.');
  if (!confirmado) return;

  try {
    const dados = await pedir('/transmitir', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(corpoDaNota()),
    });

    if (dados.simulacao) {
      alvo.insertAdjacentHTML('afterbegin',
        aviso(dados.mensagem.replace(/\*\*/g, ''))
        + `<div class="meta">Pendências abertas: ${dados.pendencias.length}</div>`);
      return;
    }
    alvo.insertAdjacentHTML('afterbegin',
      ok(`NFS-e transmitida (${dados.ambiente}). RPS ${dados.numero_rps}. `
         + dados.lembrete));
    document.getElementById('transmitir').disabled = true;
  } catch (e) {
    alvo.insertAdjacentHTML('afterbegin', erro(e.message));
  }
}

// ── Início ───────────────────────────────────────────────────────────

document.getElementById('enviar-tarefas').addEventListener('click', importarTarefas);
document.getElementById('montar-previa').addEventListener('click', montarPrevia);
document.getElementById('transmitir').addEventListener('click', transmitir);
