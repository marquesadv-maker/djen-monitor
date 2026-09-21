# Integração ao MarquesPro — ambiente Financeiro

## Arquitetura existente

| Camada | Detalhe |
|---|---|
| Host | `marquespro.marquesss.com.br` — IP interno `192.168.31.131` |
| Proxy reverso | nginx |
| Gateway | .NET, porta 5005 |
| Serviços | Python/FastAPI, porta 8000 |
| Integrações | DJEN, Gmail, Projuris |

## Isolamento

Antes de tocar em qualquer arquivo compartilhado (navegação, rotas, índice), aplique a skill `isolamento-nao-regressao`. Suas seis regras valem integralmente: isolamento total, não-regressão, não-acoplamento, arquivos compartilhados append-only, verificação antes/depois, parar-e-perguntar.

Nenhum arquivo é apagado ou modificado sem permissão explícita. Incluir o Financeiro na navegação é **append**.

## Estrutura

```
modulos/financeiro/
├── shared/
│   ├── projuris_financeiro.py   # autenticação e leitura comum às duas abas
│   └── auditoria.py             # log append-only único
├── conciliacao/
│   ├── api/motor_conciliacao.py
│   ├── web/                     # dashboard, conciliação, divergências
│   └── config/regras.json       # tolerâncias e limiares
├── nfse/
│   ├── api/rps_builder.py
│   ├── api/nfse_webiss.py
│   ├── web/                     # pendentes, prévia, emitidas
│   └── config/
│       ├── prestador.json       # cadastro fiscal do escritório
│       └── numeracao.json       # série/número de RPS persistidos
└── config/permissoes.json
```

Tudo dentro de `modulos/financeiro/`. Nenhuma lógica financeira em arquivo compartilhado do painel.

## Certificado digital

O A1 já existe no ambiente do robô de audiências dos tribunais. **Não aponte o Financeiro para a pasta daquele robô** — acoplaria os dois módulos, e mexer em um passaria a quebrar o outro.

```
/etc/marquespro/certificados/     # fora dos módulos, permissão restrita
├── ecnpj-sociedade.pfx           # NFS-e
└── ecpf-<advogado>.pfx           # PJe
```

Cada módulo lê o seu. Senhas em variável de ambiente ou cofre.

**Confirmar qual certificado está lá hoje.** PJe usa e-CPF do advogado; NFS-e usa e-CNPJ da sociedade, casado com a inscrição municipal. Se só houver e-CPF, o e-CNPJ precisa ser providenciado.

A1 vence em 1 ano e a falha aparece como erro genérico de assinatura. Alerta 30 dias antes.

## Permissões

Módulo mais sensível do painel: faturamento, honorários, fornecedores, documentos fiscais. Padrão **negar**; quem não tem acesso não vê nem o item na navegação.

| Nível | Conciliação | NFS-e |
|---|---|---|
| `leitura` | Ver dashboard e resultados | Ver pendentes e emitidas |
| `operacao` | Aceitar/rejeitar sugestões, tratar divergências | Montar e revisar RPS |
| `gravacao` | Gravar baixa no Projuris | Transmitir ao web service |

As abas podem ter níveis diferentes para a mesma pessoa:

```json
{
  "modulo": "financeiro",
  "padrao": "negado",
  "usuarios": [
    { "identificador": "", "conciliacao": "", "nfse": "" }
  ]
}
```

A lista é definida pela responsável — **não presuma**. Enquanto não estiver definida, o módulo fica restrito a ela.

Verificação sempre no backend. Esconder botão no frontend é conveniência, não controle.

## Auditoria

Um log único, append-only, sem exclusão pela interface. Por registro:

- data/hora, usuário, aba (`conciliacao` | `nfse`)
- conciliação: lançamento, título, valor, confiança, regra
- NFS-e: tarefa de origem, tomador, valor, RPS (número/série), NFS-e (número/código de verificação), **ambiente** (homologação/produção)
- resultado e resposta da API

O campo ambiente é o que separa nota de teste de nota real quando o log for revisto meses depois.

## Ordem de implantação

**Conciliação**
1. Leitura e dashboard — conferir números com o painel atual
2. Conciliação em simulação — comparar com a conciliação manual por alguns ciclos
3. Escrita com aprovação — após checklist de `projuris-financeiro.md`, começando por título de valor baixo acompanhado

**NFS-e**
1. Listar tarefas de NF pendentes
2. Montar RPS e prévia, sem transmitir — conferir contra notas já emitidas manualmente
3. Homologação — com liberação específica da prefeitura, cobrindo os casos reais
4. Produção assistida — primeiras notas com o advogado acompanhando cada uma
5. Rotina

**Comum:** definir e testar permissões com um usuário de cada nível.

Pular etapas é o caminho curto para baixa indevida ou nota que não se cancela por API.

## Antes de publicar

- [ ] Módulos existentes carregam normalmente, inclusive o robô de audiências
- [ ] Nada fora de `modulos/financeiro/` modificado além do append na navegação
- [ ] Certificado lido do repositório comum, não da pasta de outro módulo
- [ ] Senhas fora de código, log e repositório
- [ ] Usuário sem permissão não alcança a API por URL direta
- [ ] Ambiente (homologação/produção) visível na tela e gravado no log
- [ ] Numeração de RPS persistida e sem lacuna
- [ ] Consulta por RPS antes de cada transmissão
- [ ] Log de auditoria gravando nas duas abas
- [ ] Números do dashboard conferem com o painel atual
- [ ] Estados de carregando, vazio e erro implementados
