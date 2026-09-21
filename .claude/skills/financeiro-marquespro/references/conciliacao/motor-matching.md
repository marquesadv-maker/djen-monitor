# Motor de matching

## Princípio

O motor é determinístico e explicável. Duas execuções sobre os mesmos dados produzem o mesmo resultado, e todo match vem acompanhado da regra que o gerou. Isso existe porque conciliação é auditada: o usuário precisa conseguir defender por que um título foi baixado.

Nenhuma regra usa aleatoriedade, e nenhuma pontuação é "intuição do modelo". Use `scripts/motor_conciliacao.py`.

## Normalização (antes de qualquer comparação)

**Texto:** minúsculas → remover acentos → remover pontuação → colapsar espaços. `"PGTO. TRANSPORTES SÃO JOÃO LTDA"` → `"pgto transportes sao joao ltda"`.

**Documento:** manter só dígitos. CNPJ `12.345.678/0001-90` → `12345678000190`. Comparar também por raiz de CNPJ (8 primeiros dígitos) quando o match exato falhar — filiais diferentes da mesma empresa.

**Valor:** converter para centavos inteiros. Nunca comparar float com `==`.

**Data:** ISO `AAAA-MM-DD` internamente; exibir `DD/MM/AAAA`.

**Ruído bancário:** remover prefixos que não identificam nada — `TED`, `PIX`, `DOC`, `TRANSF`, `PGTO`, `RECEB`, `CRED`, `DEB`, `LIQ`. Eles aparecem em quase todo lançamento e poluem a similaridade.

## Regras, em ordem

A primeira regra que atingir o limiar encerra a busca para aquele par.

### R1 — Documento exato → 95

Documento do lançamento igual ao documento do título, ambos não vazios. É a regra mais forte: documento raramente coincide por acaso.

Se o valor também bater exatamente, sobe para 98.

### R2 — Valor exato + data dentro da tolerância → 90

Valor idêntico ao centavo e diferença de data dentro da tolerância (padrão ±5 dias corridos).

Penalidade por distância: −1 ponto por dia de diferença. Valor exato no mesmo dia = 90; com 5 dias = 85.

Atenção: se **mais de um** título em aberto tiver exatamente o mesmo valor na janela, R2 não decide nada. Nesse caso, não pontue 90 — marque como ambíguo e mande para revisão com a lista de candidatos. Match automático em ambiguidade é como a baixa errada acontece.

### R3 — Valor exato + descrição similar → 80

Valor idêntico, data fora da tolerância, mas a descrição normalizada do lançamento contém o nome da contraparte do título (ou vice-versa).

Similaridade por tokens: quantos tokens significativos (≥4 caracteres) do nome da contraparte aparecem na descrição. Metade ou mais = similar.

### R4 — Contraparte + valor próximo → 75

Documento ou nome da contraparte confere, e o valor está dentro da tolerância percentual (padrão ±2%).

Registre a diferença em reais e o provável motivo, sem concluir: tarifa, retenção, juros, desconto. Diferença pequena e negativa costuma ser tarifa; positiva costuma ser juros.

### R5 — Combinação fraca → 50–70

Nenhuma regra anterior fechou, mas há sinais: valor próximo + data próxima + fragmento de referência em comum. Soma-se o que houver:

- valor dentro de ±2%: +30
- data dentro de ±5 dias: +20
- fragmento de documento ou referência em comum: +20

Teto de 70. Na prática, quase tudo que cai aqui vira divergência — e está certo.

## Limiares

| Faixa | Destino | Comportamento |
|---|---|---|
| 90–100 | Conciliado automaticamente | Listado ao usuário; gravação ainda depende de aprovação |
| 70–89 | Sugestão | Exige aceite item a item |
| < 70 | Divergência | Exige tratamento humano |

Configuráveis: tolerância de data (padrão 5 dias), tolerância de valor (padrão 2%), limiar automático (padrão 90).

Elevar o limiar automático deixa o processo mais lento e mais seguro. Baixá-lo abaixo de 85 é desaconselhável — abaixo disso, R3 e R4 entram no automático, e nenhuma das duas tem força para justificar baixa sem olho humano.

## Tipos de divergência

| Tipo | Como identificar | Severidade |
|---|---|---|
| Sem título correspondente | Nenhum candidato acima de 50 | Alta |
| Valor divergente | Contraparte confere, valor fora da tolerância | Média |
| Data divergente | Valor e contraparte conferem, data muito fora | Baixa |
| Possível duplicidade | Dois lançamentos, mesmo valor, mesma contraparte, ≤3 dias, um só título aberto | Alta |
| Ambiguidade | Vários títulos igualmente plausíveis | Média |
| Descrição insuficiente | Descrição sem contraparte identificável após normalização | Média |
| Já conciliado | Título com baixa no período | Baixa |

Severidade alta significa: pode indicar dinheiro não registrado ou registrado em duplicidade. É o que o usuário deve olhar primeiro.

## Saída por item

Cada resultado carrega:

```
lancamento: { data, descricao, valor, documento, contraparte, tipo }
titulo:     { id, descricao, valor, vencimento, documento, status } | null
confianca:  0-100
regra:      "R2 — valor exato + data próxima"
explicacao: "Valor idêntico (R$ 15.000,00) e vencimento 2 dias antes do crédito."
dif_valor:  0
dif_dias:   2
status:     automatico | sugestao | divergencia
tipo_diverg: null | "valor_divergente" | ...
candidatos: [...]   # quando ambíguo
```

A explicação é escrita para o usuário, não para o log. "Valor idêntico e vencimento 2 dias antes" comunica; "score=90 rule=R2" não.
