# Ambiente Financeiro — MarquesPro

Módulo isolado com as duas frentes da skill `financeiro-marquespro`:

1. **Conciliação bancária** — lê o extrato (OFX/CSV/XLSX), cruza com as contas
   a receber e a pagar, separa o que fecha sozinho do que precisa de olho
   humano e monta o dashboard.
2. **NFS-e (Araguaína/TO)** — lê as tarefas de nota fiscal pendentes, monta o
   RPS no padrão ABRASF 2.02, valida campo a campo e mostra a prévia.

A nota emitida vira título a receber; o título a receber é o que a conciliação
procura no extrato. É o mesmo ciclo, visto de dois lados.

## Estado: modo simulação

**Nada é gravado no Projuris e nenhuma nota é transmitida ao WebISS.** Não é
limitação de código — é o que a skill determina enquanto houver pendência:

| Pendência | Onde se resolve |
|---|---|
| Endpoints financeiros do Projuris não confirmados | inspecionar a chamada real no DevTools e registrar em `shared/projuris_financeiro.py` (`ENDPOINTS`) |
| Endpoints de tarefas de NF não confirmados | mesmo procedimento |
| URL do web service WebISS não confirmada | Secretaria Municipal da Fazenda de Araguaína → `nfse/config/webservice.json` |
| Cadastro fiscal do prestador em branco | contador → `nfse/config/prestador.json` |
| Certificado e-CNPJ da sociedade | confirmar qual A1 existe hoje; o do PJe é e-CPF, outro documento |

Enquanto isso, as rotas de escrita respondem **o que fariam**, registram a
tentativa no log como `simulado` e não chamam a API. A tela diz isso em uma
faixa no alto da página — em vez de silenciosamente não fazer nada.

Endereço adivinhado é pior que endereço nenhum: um POST em caminho inventado
pode gravar no lugar errado ou devolver 404 silencioso que parece sucesso.

## Como rodar

Atalho, na própria pasta do módulo:

- Windows: `iniciar_financeiro.bat`
- Linux/macOS e servidor: `./iniciar_financeiro.sh`

Os dois pedem o e-mail do usuário, instalam as dependências, sobem o serviço
e **abrem o navegador sozinhos** assim que ele responder em
<http://localhost:8010/financeiro> — sem precisar digitar o endereço.

Na mão, se preferir:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r modulos/financeiro/requirements.txt

# quem está usando o painel; em produção vem do nginx, no cabeçalho
export FINANCEIRO_USUARIO_LOCAL="fulano@marquesss.com.br"

python -m modulos.financeiro.servidor_financeiro       # http://127.0.0.1:8010/financeiro
```

Produção, atrás do nginx que já autentica o painel:

```bash
gunicorn "modulos.financeiro.servidor_financeiro:criar_app()" -b 127.0.0.1:8010
```

O nginx precisa repassar a identidade do usuário no cabeçalho
`X-Usuario-Financeiro` (configurável em `config/permissoes.json`).

### Variáveis de ambiente

| Variável | Para quê |
|---|---|
| `FINANCEIRO_PORTA`, `FINANCEIRO_HOST` | onde o serviço escuta (padrão `127.0.0.1:8010`) |
| `FINANCEIRO_USUARIO_LOCAL` | identidade em execução local, fora do nginx |
| `FINANCEIRO_LOG_AUDITORIA` | caminho do log (padrão `dados/auditoria/financeiro.jsonl`) |
| `FINANCEIRO_ESCRITA_CONCILIACAO` | habilita a baixa no Projuris — **só depois** do checklist |
| `FINANCEIRO_TRANSMISSAO_NFSE` | habilita a transmissão ao WebISS — idem |
| `FINANCEIRO_CERT_SENHA` | senha do certificado A1 (cofre ou ambiente; nunca arquivo versionado) |

Ligar a variável sem confirmar o endpoint/URL **não** libera a escrita: as duas
condições valem juntas, para que ninguém destrave o módulo por engano.

## Permissões

Padrão **negar**, em `config/permissoes.json`. Hoje a lista tem uma única
entrada, a do responsável, para o primeiro acesso; quem mais entra e com qual
nível é decisão dele, não presunção do módulo:

```json
{
  "usuarios": [
    { "identificador": "fulano@marquesss.com.br",
      "conciliacao": "gravacao", "nfse": "leitura" }
  ]
}
```

| Nível | Conciliação | NFS-e |
|---|---|---|
| `leitura` | ver dashboard e resultados | ver cadastro, pendentes e emitidas |
| `operacao` | importar, conciliar, aceitar sugestões | importar tarefas, montar RPS e prévia |
| `gravacao` | gravar baixa no Projuris | transmitir ao web service |

A verificação é sempre no backend: URL direta não passa por cima. Esconder o
botão no frontend é conveniência, não controle.

## Estrutura

```
modulos/financeiro/
├── servidor_financeiro.py        # entrypoint isolado (Flask, porta própria)
├── config/permissoes.json        # padrão negar; lista definida pela responsável
├── shared/
│   ├── projuris_financeiro.py    # cliente da API (escrita bloqueada por padrão)
│   ├── auditoria.py              # log único, append-only (JSONL)
│   ├── permissoes.py             # controle de acesso por aba e nível
│   ├── modo.py                   # simulação × escrita, a partir das pendências reais
│   └── sessao.py                 # extrato e títulos em memória, nunca em disco
├── conciliacao/
│   ├── api/motor_conciliacao.py  # regras R1–R5, determinístico
│   ├── api/leitor_extrato.py     # OFX, CSV, XLSX, encoding, reimportação
│   ├── api/leitor_titulos.py     # contas a receber/pagar exportadas do Projuris
│   ├── api/agregador.py          # KPIs e séries do dashboard
│   ├── api/rotas.py
│   ├── config/regras.json        # tolerâncias e limiares
│   └── web/                      # dashboard e tela de conciliação
├── nfse/
│   ├── api/rps_builder.py        # monta, valida e gera a prévia do RPS
│   ├── api/nfse_webiss.py        # transmissor e controle de numeração
│   ├── api/leitor_tarefas.py     # tarefas de NF exportadas do Projuris
│   ├── api/rotas.py
│   ├── config/{prestador,numeracao,webservice}.json
│   └── web/
├── dados/                        # extratos e log — fora do versionamento
└── tests/                        # 57 testes
```

## Dados e sigilo

- Extrato e títulos ficam **só na memória** do processo, enquanto a sessão está
  aberta. Nada vai para disco nem para o repositório (LGPD, arts. 6º e 46).
- Conta e agência aparecem mascaradas (`****1234`); CPF/CNPJ aparecem com os
  quatro últimos dígitos, inclusive dentro das explicações de match.
- A discriminação da NFS-e é conferida contra número de processo e termos que
  identificam parte — a nota é consultável por terceiros com o código de
  verificação, e o dever de sigilo (art. 34, VII, da Lei 8.906/94) não cede por
  ser campo de documento fiscal.
- O log de auditoria registra as duas abas, com o campo `ambiente` na NFS-e:
  é o que separa nota de teste de nota real quando o log for revisto meses
  depois. Não existe função de exclusão — de propósito.

## Ordem de implantação

**Conciliação**
1. Leitura e dashboard — conferir os números com o painel atual.
2. Conciliação em simulação — comparar com a conciliação manual por alguns ciclos.
3. Escrita com aprovação — após o checklist, começando por título de valor baixo,
   acompanhado.

**NFS-e**
1. Listar as tarefas pendentes.
2. Montar RPS e prévia, sem transmitir — conferir contra notas já emitidas à mão.
3. Homologação, com liberação específica da prefeitura.
4. Produção assistida, com o advogado acompanhando cada nota.
5. Rotina.

Pular etapas é o caminho curto para baixa indevida ou para uma nota que, em
Araguaína, não se cancela por API — só por substituição no portal.

## Testes

```bash
pip install pytest openpyxl
python -m pytest modulos/financeiro/tests -q
```

Cobrem o que dói caro: sinal invertido no extrato, linha de saldo contada como
lançamento, reimportação, padrão negar, aprovação item a item, escrita que não
acontece em modo simulação e o log registrando o que foi recusado.

## Isolamento

Este módulo não importa nada dos outros módulos do painel e não é importado por
eles. Nenhum arquivo fora de `modulos/financeiro/` foi alterado para criá-lo —
o monitor DJEN (`djen-monitor/app.py`) segue exatamente como estava. Para
incluir o item na navegação do painel principal, o acréscimo é combinado antes
e feito apenas por adição, sem mexer nas entradas existentes.
