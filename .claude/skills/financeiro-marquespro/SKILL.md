---
name: financeiro-marquespro
description: 'Ambiente Financeiro do escritório Marques Advogados, integrado ao Projuris ADV e ao MarquesPro. Duas frentes: (1) conciliação bancária — cruza extrato (OFX/CSV/XLSX) com contas a receber e a pagar do Projuris, aponta divergências, gera o dashboard financeiro e só grava baixa após aprovação; (2) emissão de NFS-e em Araguaína/TO — lê tarefas de Nota Fiscal pendentes no Projuris, monta o RPS, mostra a prévia e só transmite ao WebISS (ABRASF 2.02, certificado A1) após aprovação. Use SEMPRE que o usuário mencionar conciliação bancária, conciliar o banco, bater o extrato, baixar título, contas a receber, contas a pagar, dashboard financeiro, fluxo de caixa, emitir nota fiscal, NFS-e, NF pendente, tarefa de nota fiscal, faturar o cliente, RPS, WebISS, ISS, robô de nota fiscal, financeiro do Projuris ou aba financeiro do MarquesPro, ou quando anexar extrato bancário.'
---

# Ambiente Financeiro — MarquesPro

Duas abas, um ciclo: a nota emitida vira título a receber; o título a receber é o que a conciliação procura no extrato. Dado limpo na nota (documento do tomador, valor exato, referência interna) é o que faz a conciliação acertar depois.

| Pedido do usuário | Frente | Referências |
|---|---|---|
| Extrato, baixa, divergência, dashboard | Conciliação | `references/conciliacao/` |
| Nota fiscal, RPS, ISS, tarefa de NF | NFS-e | `references/nfse/` |
| Autenticação e endpoints do Projuris | Ambas | `references/projuris-financeiro.md` |
| Deploy, certificado, permissões | Ambas | `references/integracao-marquespro.md` |

## Por que tudo aqui é conservador

As duas frentes escrevem em sistemas onde o erro custa caro e se desfaz mal:

- **Baixa indevida no Projuris** apaga a pendência de um título que não foi pago de verdade.
- **NFS-e errada em Araguaína** não pode ser cancelada pelo web service — só por substituição, no portal. Vira obrigação tributária e documento errado na mão do cliente.

Por isso a skill monta, confere e mostra tudo, e para antes de escrever. Um robô que age sozinho erra sozinho.

## Regras invioláveis (valem para as duas abas)

1. **Escrita só com aprovação item a item.** Baixa no Projuris ou transmissão de nota: liste quantos itens, quais e o valor total, e aguarde. "Pode ir" genérico não autoriza lote.
2. **Nunca inventar endpoint, URL, campo ou ID.** Os endpoints financeiros e de tarefas de NF do Projuris e a URL do web service da prefeitura **não estão confirmados**. Os scripts recusam chamadas sem registro. Procedimentos de descoberta em `references/projuris-financeiro.md` (seção 4) e `references/nfse/webiss-araguaina.md`.
3. **Nunca inventar dado.** Valor, data, documento, alíquota, item da LC 116 — vêm do extrato, da API, do cadastro ou do contador. Campo vazio bloqueia; a skill não preenche por dedução.
4. **Sigilo e LGPD.** Extrato não sai do ambiente; conta e agência aparecem mascaradas (`****1234`). Discriminação da nota não expõe parte, número de processo ou matéria — a NFS-e é consultável por terceiros. Base: arts. 6º e 46 da LGPD e art. 34, VII, da Lei 8.906/94.
5. **Credenciais nunca armazenadas.** Senha do Projuris e do certificado vêm da conversa, de variável de ambiente ou de cofre — nunca de arquivo versionado, nunca em log.
6. **Tudo que é gravado fica registrado.** Log append-only com data/hora, usuário, item, valor, regra/origem, resultado e resposta da API. Sem log, não grave.
7. **Resultado real, inclusive falhas.** "7 gravadas, 3 falharam" — com a lista. Nunca arredondar para "concluído".

## Estado atual

| Item | Situação |
|---|---|
| Motor de conciliação | Pronto e testado (`scripts/motor_conciliacao.py`) |
| Montagem e validação de RPS | Pronta e testada (`scripts/rps_builder.py`) |
| Endpoints financeiros do Projuris | **Não confirmados** — inspecionar no DevTools |
| Endpoints de tarefas de NF do Projuris | **Não confirmados** — mesmo procedimento |
| URL do web service WebISS | **Não confirmada** — obter da Secretaria da Fazenda |
| Cadastro fiscal do prestador | **Pendente** — inscrição, regime, item LC 116, alíquota (contador) |
| Certificado | A1 existente no ambiente do robô de tribunais — confirmar se é e-CNPJ |

Enquanto houver pendência, a escrita fica em **modo simulação**: mostra o que faria, não faz. Diga isso ao usuário em vez de silenciosamente não fazer nada.

---

## Aba 1 — Conciliação bancária

### Fluxo

1. **Verificar o que já existe.** Extrato anexado? Credencial do Projuris nesta sessão (senha nunca armazenada — pedir se faltar)? O pedido é só dashboard (leitura) ou conciliação (leitura + escrita)?
2. **Ler o Projuris.** Contas a receber, contas a pagar e baixas já lançadas no período. Sem período informado: mês do extrato, 30 dias para trás e 15 para frente.
3. **Ler o extrato.** Ver `references/conciliacao/formatos-extrato.md`. Arquivo que não pôde ser lido é dito como tal — nunca apresentado como processado.
4. **Cruzar.** Use `scripts/motor_conciliacao.py` — determinístico, para que o mesmo extrato dê o mesmo resultado e o usuário possa auditar. Regras em `references/conciliacao/motor-matching.md`.

   | Confiança | Destino |
   |---|---|
   | 90–100 | Automático (ainda listado ao usuário) |
   | 70–89 | Sugestão — aceite explícito |
   | < 70 | Divergência — tratamento humano |

5. **Apresentar** em três blocos: Conciliado automaticamente → Sugestões para aprovação → Divergências. Sempre com o **porquê** do match, não só a porcentagem.
6. **Gravar** só após aprovação, um a um, 150 ms entre chamadas.

### Erros comuns

- **Conciliar duas vezes o mesmo título** em reimportação — comparar antes com as baixas existentes.
- **Tratar duplicidade como match** — dois lançamentos iguais e um só título: um deles não tem título.
- **Somar crédito e débito no mesmo KPI** — conferir o sinal antes.
- **Concluir que valor diferente é erro do banco** — pode ser tarifa, retenção, juros ou desconto. Mostrar a diferença, não a causa.

### Dashboard

Layout, paleta (marinho `#1B2A4A` + dourado `#C9A227`), KPIs e gráficos em `references/conciliacao/dashboard.md`. O dashboard é **leitura** e nunca dispara escrita. Pedido explícito de painel → construir; pergunta "como está o financeiro" → números no chat, painel oferecido em uma linha.

---

## Aba 2 — Emissão de NFS-e (Araguaína/TO)

Provedor WebISS, padrão ABRASF 2.02, certificado A1, IBGE `1702109`. Detalhes em `references/nfse/webiss-araguaina.md`.

### Fluxo

1. **Buscar as tarefas de NF pendentes** no Projuris: processo ou atendimento, cliente, valor, descrição, competência, responsável.
2. **Montar o RPS** com `scripts/rps_builder.py`, que valida antes de montar — campo ausente vira bloqueio explícito. Campos e mapeamento em `references/nfse/dados-rps.md`.
3. **Consultar por RPS** antes de transmitir: se já existe nota para aquela tarefa, não emitir de novo.
4. **Apresentar a prévia** por nota:

   ```
   Tomador:      <razão social> — <CNPJ/CPF>
   Serviço:      item <LC 116 sem ponto> — <discriminação>
   Competência:  MM/AAAA
   Valor bruto:  R$ X
   ISS:          X% — <retido | não retido>
   Líquido:      R$ Y
   Origem:       tarefa <id> · contrato <ref interna>
   ```

   Apontar faltas e alertas de sigilo antes de pedir aprovação. Alíquota vazia é dita como vazia — nunca presumir 2%, 3% ou 5%.
5. **Transmitir** após aceite, uma nota por chamada (`GerarNfse`), com `scripts/nfse_webiss.py`. Homologação antes de produção.
6. **Devolver ao Projuris** número da NFS-e, código de verificação e link, e concluir a tarefa. Se a nota saiu e a gravação no Projuris falhou, **avisar em destaque**: a nota existe no fisco e não no ERP.

### ISS de sociedade de advogados

Pode haver recolhimento fixo por profissional habilitado, em vez de percentual. A skill não decide: regime, alíquota e item da LC 116 vêm do contador e ficam registrados em `references/nfse/dados-rps.md`. Enquanto não estiverem, a emissão não avança.

### Erros comuns

- **Certificado errado** — e-CPF do advogado é do PJe; a NFS-e pede o e-CNPJ da sociedade.
- **Nota emitida duas vezes** — tarefa não concluída no Projuris após emitir.
- **Competência trocada** — é o mês da prestação, não da emissão.
- **Bruto x líquido** — retenção reduz o líquido, não o valor do serviço.
- **Código com ponto** — Araguaína exige o item da LC 116 sem ponto; CTISS não se preenche.

---

## Arquivos

**Referências**
- `references/projuris-financeiro.md` — autenticação, hosts, rate limit, descoberta de endpoints
- `references/integracao-marquespro.md` — deploy das duas abas, certificado, permissões, auditoria, ordem de implantação
- `references/conciliacao/motor-matching.md` — regras R1–R5, limiares, tipos de divergência
- `references/conciliacao/formatos-extrato.md` — OFX, CSV, XLSX, encoding, reimportação
- `references/conciliacao/dashboard.md` — layout, paleta, KPIs, gráficos
- `references/nfse/webiss-araguaina.md` — web service, homologação, assinatura, cancelamento
- `references/nfse/dados-rps.md` — cadastro do prestador, campos, mapeamento, sigilo na discriminação

**Scripts**
- `scripts/projuris_financeiro.py` — cliente da API (escrita bloqueada por padrão)
- `scripts/motor_conciliacao.py` — motor determinístico de matching
- `scripts/rps_builder.py` — monta, valida e gera prévia do RPS (não transmite)
- `scripts/nfse_webiss.py` — transmissor WebISS e controle de numeração (bloqueado por padrão)
