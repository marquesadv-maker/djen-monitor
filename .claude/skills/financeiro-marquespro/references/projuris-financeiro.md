# Projuris ADV — módulo Financeiro

## Índice

1. Autenticação
2. Hosts e rede
3. Rate limit
4. Descoberta dos endpoints financeiros (obrigatória antes da primeira escrita)
5. Campos esperados
6. Escrita — regras e checklist
7. Troubleshooting

---

## 1. Autenticação

```
POST https://apigw.projurisadv.com.br/auth/token
grant_type=password
```

- Usuário no formato `email$$slug-do-tenant`
- Tenant do escritório: slug `marques-advogados3`, chave numérica `53034`
- Usuário funcional (03/09/2026): `aanacaroline514@gmail.com$$marques-advogados3`
- **A senha nunca é armazenada em arquivo, memória ou código.** Peça na conversa a cada sessão.
- Token expira em ~1500 s. Renove por sessão longa.

O usuário anterior (`mariaelisanolasco@outlook.com$$marques-advogados3`) passou a retornar HTTP 400 no login — não use.

## 2. Hosts e rede

| Finalidade | Host |
|---|---|
| Autenticação | `apigw.projurisadv.com.br` |
| Serviços (dados) | `adv-service.projurisadv.com.br` |

`api.projurisadv.com.br` **está errado** — retorna HTTP 400 em todos os endpoints e produz falso diagnóstico de "tenant nulo". Esse erro já custou tempo uma vez; não repita.

No chat do Claude, `adv-service.projurisadv.com.br` precisa estar na allowlist de egress. Sem isso, as chamadas retornam 403 `host_not_allowed` — o que é problema de rede, não de credencial. Nesse caso, oriente o usuário a liberar o host nas configurações de rede.

Para acesso a partir do navegador, existe o proxy local `projuris_proxy.py` na porta 8765, que contorna CORS.

## 3. Rate limit

- 480 requisições/minuto
- Manter 150 ms entre chamadas
- Em lote de baixas, isso é obrigatório: estourar o limite no meio de uma gravação deixa o lote pela metade

## 4. Descoberta dos endpoints financeiros

**Estado atual: os endpoints do módulo Financeiro não estão confirmados.** A integração documentada do escritório cobre processos, tarefas, andamentos e pessoas. Financeiro ainda não foi mapeado.

Isso significa: **não chute caminhos** como `/financeiro/contas-receber`. Um POST em caminho adivinhado pode gravar em lugar errado ou retornar 404 silencioso que parece sucesso.

Procedimento antes da primeira leitura:

1. Peça ao usuário que abra a aba Financeiro no Projuris no navegador, com o DevTools aberto na aba Network.
2. Peça que filtre por `adv-service` e faça a ação (listar contas a receber do mês).
3. Peça o caminho da requisição, o método e o corpo da resposta (com dados sensíveis mascarados).
4. Registre o endpoint confirmado neste arquivo, com a data e a origem da confirmação.
5. Só então implemente.

Para a escrita (baixa de título), o mesmo procedimento, observando a ação de dar baixa manualmente em um título de teste.

Alternativa: abrir chamado no suporte Projuris pedindo a documentação do módulo financeiro da API. Os chamados 94309 e 94968 já serviram de base para os endpoints de processo; o mesmo caminho funciona aqui.

### Endpoints confirmados

*(preencher conforme a descoberta — formato abaixo)*

```
| Método | Caminho | Finalidade | Confirmado em | Origem |
|--------|---------|------------|---------------|--------|
|        |         |            |               |        |
```

## 5. Campos esperados

O Projuris usa campos dinâmicos (`campoDinamicoDadoWs`) em várias entidades. Ao mapear o financeiro, verifique se centro de custo, categoria e banco são campos fixos ou dinâmicos — isso muda o payload da escrita.

Campos que a conciliação precisa ler, em cada título:

- identificador do título
- tipo (receber / pagar)
- cliente ou fornecedor (nome + documento)
- valor
- data de vencimento
- data de pagamento (se houver)
- status (aberto, pago, cancelado, parcial)
- número do documento / nota / referência
- processo vinculado, se houver
- banco e forma de pagamento, se houver

Se algum desses não existir na resposta da API, registre a ausência e adapte o motor de matching — a regra que depende do campo ausente simplesmente não pontua, em vez de gerar erro.

## 6. Escrita — regras e checklist

A integração do escritório é **read-only por padrão**. Já houve uma exceção aprovada (POST `/tarefa` para o SDR de WhatsApp) — exceções são pontuais, nominadas e aprovadas, não abertura geral.

Para a conciliação, a escrita precisa de:

- [ ] Endpoint de baixa confirmado por inspeção real (seção 4)
- [ ] Teste em um título de valor baixo, acompanhado pelo usuário, antes de qualquer lote
- [ ] Aprovação explícita do usuário para esta skill gravar no financeiro
- [ ] Log de auditoria funcionando
- [ ] Procedimento de estorno conhecido (como desfazer uma baixa errada no Projuris)

Enquanto qualquer item acima estiver aberto, a skill opera em **modo simulação**: mostra o que gravaria, não grava. Diga isso claramente ao usuário em vez de silenciosamente não fazer nada.

## 7. Troubleshooting

| Sintoma | Causa provável |
|---|---|
| HTTP 400 em todo endpoint | Host errado — trocar `api.` por `adv-service.` |
| HTTP 403 `host_not_allowed` | Host fora da allowlist de egress do ambiente |
| HTTP 400 no login | Usuário desativado — conferir qual usuário está em uso |
| 401 no meio da sessão | Token expirou (~1500 s) — renovar |
| 429 | Rate limit — aumentar o intervalo entre chamadas |
| CORS no navegador | Subir `projuris_proxy.py` na 8765 |
