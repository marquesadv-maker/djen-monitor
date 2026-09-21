# Dados do RPS — campos e mapeamento

## Cadastro do prestador (preencher uma vez, confirmado com o contador)

Estes valores são do escritório e não mudam por nota. Enquanto estiverem em branco, a emissão não avança — e isso é proposital: nota emitida com enquadramento errado gera passivo tributário.

```
CNPJ:                    ____________________
Inscrição municipal:     ____________________
Razão social:            Marques Advogados S/S
Regime tributário:       ____________________  (Simples Nacional / Lucro Presumido / ...)
Optante Simples:         ____________________  (sim / não)
Incentivador cultural:   ____________________
Item LC 116/2003 padrão: ____________________  (serviços advocatícios)
Alíquota ISS:            ____________________  (% ou regime fixo por profissional)
Natureza da operação:    ____________________
Exigibilidade ISS:       ____________________
Município de incidência: 1702109 (Araguaína/TO)
```

**Sobre a alíquota:** sociedade de advogados pode ter recolhimento fixo por profissional habilitado, em vez de percentual sobre o faturamento, a depender do regime e do tratamento municipal. Isso é definição do contador, não da skill. Registre aqui o que ele confirmar, com a data.

**Sobre o código de serviço:** em Araguaína, tanto o Código de Serviço quanto o Código da Atividade usam o item da LC 116/2003 **sem ponto**. O campo CTISS não é preenchido.

## Campos por nota

### Tomador — obrigatórios

| Campo | Observação |
|---|---|
| CNPJ ou CPF | Só dígitos; validar dígito verificador antes de montar |
| Razão social / nome | Como consta no cadastro do cliente |
| Endereço | Logradouro, número, bairro, município (IBGE), UF, CEP |
| E-mail | Opcional no schema, mas é por onde o cliente recebe a nota |

Tomador fora de Araguaína continua com incidência no município do prestador, salvo nas hipóteses do art. 3º da LC 116/2003. Se o caso do escritório cair numa dessas hipóteses, confirme com o contador antes de emitir.

### Serviço — obrigatórios

| Campo | Observação |
|---|---|
| Item LC 116/2003 | Sem ponto |
| Discriminação | Texto do que foi prestado — ver abaixo |
| Valor do serviço | **Bruto**, antes de qualquer retenção |
| Competência | Mês da prestação, não da emissão |
| Município da prestação | Código IBGE |

### Tributos

| Campo | Observação |
|---|---|
| Alíquota ISS | Do cadastro do prestador |
| ISS retido | Sim/não — depende do tomador e da natureza |
| Valor do ISS | Calculado em centavos inteiros |
| Retenções federais | IR, PIS, COFINS, CSLL, INSS quando aplicável |
| Deduções / descontos | Quando houver |

Retenção não reduz o valor do serviço. Reduz o líquido a receber. Confundir os dois produz nota com valor menor que o contratado.

## Discriminação do serviço

É o campo que o cliente lê e que o fisco fiscaliza. Precisa descrever o serviço sem expor o que é sigiloso.

**Evite:** número de processo com parte identificada, matéria sensível, estratégia, nome de terceiros envolvidos. O dever de sigilo (art. 34, VII, da Lei 8.906/94) não cede porque o campo é de um documento fiscal, e a NFS-e é consultável por terceiros com o código de verificação.

**Padrão sugerido:**

```
Honorários advocatícios contratuais — <área> — competência MM/AAAA.
Contrato <ref interna>.
```

Referência interna em vez de número de processo resolve a rastreabilidade sem expor a parte. Se o cliente exigir o número do processo na nota, é decisão dele sobre o próprio dado — registre que foi pedido.

## Mapeamento Projuris → RPS

Os campos de origem dependem dos endpoints do Projuris, que **ainda não foram confirmados** para o módulo financeiro/NF. Registre o mapeamento real depois da inspeção:

| Campo do RPS | Origem no Projuris | Confirmado |
|---|---|---|
| Tomador — documento | | ☐ |
| Tomador — razão social | | ☐ |
| Tomador — endereço | | ☐ |
| Valor do serviço | | ☐ |
| Competência | | ☐ |
| Discriminação | | ☐ |
| Referência interna | | ☐ |
| Item LC 116 | cadastro do prestador | ☐ |

Campos que o Projuris não fornecer precisam de origem definida — cadastro fixo, ou preenchimento manual na prévia. Campo sem origem é campo que vai chegar vazio na nota.

## Validações antes de transmitir

- [ ] CNPJ/CPF do tomador válido (dígito verificador)
- [ ] Valor maior que zero
- [ ] Competência não futura
- [ ] Item LC 116 preenchido e sem ponto
- [ ] Alíquota preenchida (ou regime fixo declarado)
- [ ] Discriminação sem dado sigiloso
- [ ] Endereço do tomador completo
- [ ] Consulta por RPS: não existe nota anterior para esta tarefa
- [ ] Valores em centavos inteiros, sem resíduo de arredondamento

Falhou qualquer item: bloqueie e mostre o que falta. Não transmita "o que dá para transmitir".

## Numeração de RPS

O número de RPS é sequencial e controlado pelo emitente, por série. Guarde o último número usado de forma persistente — reiniciar a contagem gera rejeição por RPS duplicado, e pular números levanta pergunta em fiscalização.

Registre, por nota: número do RPS, série, tarefa de origem, e depois o número da NFS-e retornado. Esse trio é o que liga o ERP ao fisco.
