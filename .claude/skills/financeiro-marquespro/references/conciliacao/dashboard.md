# Dashboard financeiro

Reproduz o painel que o escritório já usa, para que quem conhece o atual não precise reaprender nada.

## Paleta

| Uso | Cor |
|---|---|
| Fundo do painel | `#1B2A4A` (azul marinho) |
| Cards e blocos | `#F2EFE6` (bege claro) |
| Texto sobre bege | `#1B2A4A` |
| Títulos de seção e rótulos de filtro | `#C9A227` (dourado) |
| Série "Entrada" | `#1B2A4A` |
| Série "Saída" | `#B08A3E` (bronze) |
| Conciliado / Pago | `#2E7D53` |
| Revisão / Vencido | `#C9A227` |
| Divergência / Erro | `#B3261E` |

Vermelho **só** para divergência e erro. Se aparecer em qualquer outro lugar, perde o significado e o usuário deixa de reagir a ele.

Tipografia: sem serifa, uma família só, pesos 400/600/700. Rótulos de KPI em caixa alta, peso 700.

## Layout

```
┌─────────────────────────────────────────────────┬──────────┐
│  ENTRADA  │  SAÍDA  │  SALDO  │  % MARGEM       │  [logo]  │
├─────────────────────────────────────────────────┼──────────┤
│  Entrada x Saída Mensal                         │  FILTROS │
│  (barras agrupadas + linha de valor total)      │          │
├──────────────────────┬──────────────────────────┤  Ano     │
│ Status de            │  Top Fornecedores        │  Mês     │
│ Recebimentos         │  (barras horizontais)    │  Banco   │
│ (rosca)              │                          │  Forma   │
├──────────────────────┤                          │  Cat.Ent │
│ Top Clientes         │                          │  Cat.Saí │
│ (barras horizontais) │                          │          │
│                      │                          │ [Limpar] │
└──────────────────────┴──────────────────────────┴──────────┘
```

Coluna de filtros fixa à direita, sobre o fundo marinho, rótulos em dourado. Rodapé da coluna traz "Última atualização: DD/MM/AAAA HH:MM".

## KPIs

| KPI | Cálculo |
|---|---|
| ENTRADA | Soma dos créditos conciliados no período |
| SAÍDA | Soma dos débitos conciliados no período |
| SALDO | Entrada − Saída |
| % MARGEM | (Entrada − Saída) / Entrada × 100 |

Saldo negativo em vermelho; positivo em marinho. Margem com uma casa decimal.

Se o período não tiver entrada, margem é "—", não 0% e nunca divisão por zero.

## Gráficos

**Entrada x Saída Mensal** — barras agrupadas por mês, uma para entrada e uma para saída, mais linha de valor total. Rótulo de valor em cada barra. Eixo Y em reais.

**Status de Recebimentos** — rosca com Pago, Vencido, A Vencer, Não Conciliado. Valor em reais por fatia. Legenda à direita.

**Top Fornecedores** — barras horizontais, até 15, ordem decrescente, rolagem se exceder. Nome truncado com reticências, valor ao lado da barra.

**Top Clientes** — mesma estrutura, até 10.

## Filtros

Ano · Mês · Banco · Forma de Pagamento · Categoria de Entrada · Categoria de Saída — todos com opção "Todos". Botão "Limpar Filtros" ao final.

Filtros são cumulativos e todos os blocos reagem juntos. Filtro que zera o conjunto mostra estado vazio ("Nenhum lançamento para os filtros selecionados"), não um painel de zeros — zero e "sem dados" significam coisas diferentes para quem lê.

## Formatação

- Moeda: `R$ 1.234.567,89`; abreviação só acima de 1 milhão (`R$ 1,2 Mi`)
- Datas: `DD/MM/AAAA`
- Percentual: vírgula decimal
- Sem CPF, CNPJ, conta ou agência visíveis; conta mascarada como `****1234`

## Estados

Carregando (esqueleto, nunca painel em branco) · Vazio (mensagem + ação) · Erro (o que falhou + como tentar de novo) · Sucesso.

## Responsividade

Desktop e tablet: layout acima. Celular: coluna de filtros vira gaveta recolhível; gráficos empilham; barras horizontais viram lista.

## Construção

React + TypeScript, Recharts quando disponível, SVG próprio como alternativa. Estado em memória; sem `localStorage` em artefato do Claude.ai (não é suportado e o artefato quebra).

Separe dados, regras e apresentação — a troca de dados de demonstração por dados reais da API deve tocar só a camada de dados.
