# WebISS Araguaína — web service NFS-e

## O que está confirmado

| Item | Valor | Fonte |
|---|---|---|
| Município | Araguaína/TO — código IBGE `1702109` | Actana / Sankhya |
| Provedor | WebISS | Invent Software, EspiãoNFe |
| Padrão | ABRASF 2.02 | Webmania, Invent Software |
| Autenticação | Certificado digital A1 | Webmania, Invent Software |
| Ambiente de homologação | Existe | Invent Software |
| Frase secreta / senha | Não necessária | Invent Software |
| Consulta NFS-e por RPS | Disponível | Invent Software |
| Cancelamento via web service | **Não disponível** — só por substituição, no portal | Invent Software |
| Código de Serviço | LC 116/2003, sem ponto | Invent Software |
| Código da Atividade | LC 116/2003, sem ponto | Invent Software |
| Código CTISS | Não preencher | Invent Software |

Fontes:
- https://docs.inventsoftware.info/TaxOne.NFSe/MunicipiosProducao/WebService/Araguaina.html
- https://webmaniabr.com/blog/nota-fiscal-de-servico-em-araguaina/
- https://araguaina.to.gov.br/servicos/emitir-nota-fiscal-de-servico-eletronica-e-nfs
- https://ajuda.sankhya.com.br/hc/pt-br/articles/22602141163031

## O que ainda precisa ser confirmado

A URL exata do WSDL de produção e de homologação do município **não deve ser adivinhada**. Padrões do provedor WebISS variam entre municípios e entre versões. Obtenha a URL oficial por um destes caminhos, nesta ordem de preferência:

1. Secretaria Municipal da Fazenda de Araguaína, junto com a liberação do ambiente de homologação
2. Portal do WebISS do município, área de integração/desenvolvedor
3. Documentação do provedor

Registre aqui, com data e origem, quando confirmar:

```
Produção:    ____________________  (confirmado em __/__/____, origem: __________)
Homologação: ____________________  (confirmado em __/__/____, origem: __________)
```

Transmitir para URL adivinhada é pior que não transmitir: o pedido pode ir ao município errado ou falhar de um jeito que parece sucesso.

## Homologação

A liberação para o ambiente de homologação precisa ser solicitada especificamente à prefeitura — não vem junto com o credenciamento de produção.

Roteiro:

1. Solicitar liberação de homologação à Secretaria da Fazenda
2. Emitir 2 ou 3 notas de teste cobrindo os casos reais do escritório (honorário contratual, honorário de êxito, serviço com retenção)
3. Conferir o XML retornado e o DANFSE
4. Só então apontar para produção

Toda alteração no layout do RPS repete esse ciclo. É rápido e evita descobrir um campo errado com uma nota real já no fisco.

## Operações ABRASF 2.02

As operações padrão do layout são: `GerarNfse`, `RecepcionarLoteRps`, `RecepcionarLoteRpsSincrono`, `ConsultarLoteRps`, `ConsultarNfsePorRps`, `ConsultarNfseServicoPrestado`, `CancelarNfse`, `SubstituirNfse`.

Para Araguaína:

- **`GerarNfse`** é a operação preferida para o escritório. Uma nota por chamada, resposta com o número da NFS-e — rastreabilidade por nota.
- **`ConsultarNfsePorRps`** é a defesa contra emissão duplicada. Consulte antes de transmitir: se já existe nota para aquele número de RPS, não transmita de novo.
- **`CancelarNfse`** não funciona neste município. Substituição é feita no portal.

## Assinatura digital

O XML é assinado com o certificado A1 no padrão XML-DSig, com algoritmo SHA-1 ou SHA-256 conforme o schema da versão 2.02.

Em ABRASF 2.02 com `GerarNfse`, o que se assina é o RPS (elemento `InfDeclaracaoPrestacaoServico`, atributo `Id`). O que exatamente deve ser assinado varia por provedor — confirme na homologação, testando com o validador de assinaturas da Receita Federal antes de enviar ao município:

https://servicos.receita.fazenda.gov.br/servicos/assinadoc/ValidadorAssinaturas.app/valida.aspx

Se o XML não passa no validador da Receita, também não vai passar no WebISS. Testar ali economiza rodadas de tentativa e erro.

## Guarda do certificado

- O `.pfx` fica num repositório de certificados com permissão restrita, **não** dentro do módulo e **não** dentro da pasta de outro robô. Acoplar módulos por diretório compartilhado quebra a regra de isolamento do painel.
- A senha vem de variável de ambiente ou cofre — nunca de arquivo versionado, nunca em log.
- Registrar a data de validade: A1 vale 1 ano. Certificado vencido derruba a emissão sem aviso prévio; um alerta 30 dias antes evita a surpresa.
- Confirmar que o certificado em uso é o **e-CNPJ da sociedade**, casado com a inscrição municipal do prestador. O e-CPF do advogado, usado no PJe, é outro documento.

## Erros comuns do web service

| Retorno | Causa típica |
|---|---|
| Erro de assinatura | Elemento assinado errado, ou algoritmo fora do schema |
| Schema inválido | Campo fora de ordem, ou tipo incorreto — validar contra o XSD antes de enviar |
| Prestador não encontrado | Inscrição municipal ou CNPJ divergente do credenciamento |
| RPS já existente | Nota já emitida para aquele número — consultar antes de reenviar |
| Código de serviço inválido | Item da LC 116/2003 com ponto, ou não habilitado para o prestador |
| Lote em processamento | Envio assíncrono — consultar o protocolo, não reenviar |

Reenviar em cima de "lote em processamento" é como notas duplicadas nascem. Consulte o protocolo.
