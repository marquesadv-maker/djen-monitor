# Formatos de extrato

## Ordem de preferência

1. **OFX / OFC** — formato bancário padrão, com identificador único por lançamento (`FITID`). É o melhor: o `FITID` permite detectar reimportação com certeza, sem heurística.
2. **CSV** — universal, mas cada banco usa um layout. Exige mapeamento de colunas.
3. **XLSX** — igual ao CSV, com o custo extra de abas e células formatadas.
4. **PDF** — só quando for PDF de texto. PDF escaneado exige OCR e o resultado não é confiável para valores.

## Regra de honestidade

Se o arquivo não puder ser efetivamente lido, **diga**. Nunca apresente como "processado" um arquivo cujo conteúdo não foi extraído, e nunca preencha lançamentos por dedução a partir de um total.

Frase útil: "Não consegui extrair os lançamentos deste PDF — parece ser digitalizado. Exporte o extrato em CSV ou OFX pelo internet banking e eu processo."

## Campos mínimos

Para conciliar, cada lançamento precisa de:

- **data** — obrigatória
- **valor** — obrigatório
- **tipo** — crédito ou débito (ou sinal no valor)
- **descrição / histórico** — obrigatória na prática; sem ela só R1 e R2 funcionam

Opcionais que melhoram muito o resultado:

- **documento** — CPF/CNPJ da contraparte, número do comprovante
- **identificador do lançamento** — `FITID` no OFX
- **contraparte** — quando o banco separa do histórico

## CSV — mapeamento de colunas

Layouts variam. Não assuma; inspecione o cabeçalho e mapeie. Cabeçalhos comuns por campo:

| Campo | Variações |
|---|---|
| data | Data, Data Lançamento, Data Movimento, DT_LANC |
| descrição | Histórico, Descrição, Lançamento, Memo |
| valor | Valor, Valor (R$), Montante, VLR |
| tipo | Tipo, D/C, Natureza, Débito/Crédito |
| documento | Documento, Doc, Nº Documento, CPF/CNPJ |
| saldo | Saldo, Saldo Após |

Se o cabeçalho não for reconhecido, mostre as primeiras linhas ao usuário e pergunte qual coluna é qual. Perguntar custa uma mensagem; adivinhar errado custa a conciliação inteira.

## Sinal e tipo

Três convenções circulam:

1. Coluna `tipo` com `C`/`D`
2. Valor com sinal (negativo = débito)
3. Colunas separadas de entrada e saída

Detecte qual está em uso antes de somar. Inverter o sinal produz um dashboard plausível e errado — o tipo de erro que passa despercebido.

## Encoding e separadores

- Bancos brasileiros exportam muito em **ISO-8859-1 (latin-1)**, não UTF-8. Tente UTF-8, caia para latin-1.
- Separador pode ser `;` (comum no Brasil) ou `,`.
- Decimal com vírgula e milhar com ponto: `1.234,56` = 1234.56.

## Linhas que não são lançamento

Extratos trazem cabeçalho institucional, linhas de saldo anterior, saldo final, totalizadores e rodapé. Descarte linhas sem data válida ou sem valor numérico — mas **conte quantas descartou** e informe. "Li 47 lançamentos e ignorei 6 linhas de cabeçalho/saldo" é verificável; "li 47 lançamentos" esconde um possível erro de parsing.

## Reimportação

Antes de cruzar, verifique se o extrato já foi importado:

- Com OFX: compare `FITID`.
- Sem `FITID`: a chave é (data, valor, descrição normalizada). Colisão nos três campos em importações diferentes = provável reimportação.

Se detectar, pergunte antes de prosseguir: reprocessar tudo ou só o que é novo?

## Erros a tratar sem quebrar

| Situação | Comportamento |
|---|---|
| Linha sem data | Descartar e contar |
| Valor não numérico | Descartar e contar |
| Data futura | Aceitar, sinalizar |
| Valor zero | Aceitar, sinalizar |
| Arquivo vazio | Informar; não prosseguir |
| Arquivo acima de 10 MB | Avisar e processar em blocos |
| Duas datas na mesma coluna (lançamento/efetivação) | Usar a de efetivação para o match |
