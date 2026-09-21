"""
Montagem e validação de RPS para NFS-e — padrão ABRASF 2.02, Araguaína/TO.

Este módulo monta e valida. Não transmite. A separação é proposital:
validar é barato e reversível, transmitir não é — em Araguaína a nota
não pode ser cancelada por web service.

Uso:
    from rps_builder import Prestador, Tomador, Servico, montar_rps, validar

    erros = validar(prestador, tomador, servico)
    if erros:
        for e in erros:
            print("BLOQUEIO:", e)
    else:
        xml = montar_rps(prestador, tomador, servico, numero_rps=101, serie="1")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from xml.etree.ElementTree import Element, SubElement, tostring

from ...shared.formatacao import brl

NAMESPACE = "http://www.abrasf.org.br/nfse.xsd"
IBGE_ARAGUAINA = "1702109"


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------

@dataclass
class Prestador:
    cnpj: str
    inscricao_municipal: str
    razao_social: str = ""
    optante_simples: bool | None = None       # None = não definido
    incentivador_cultural: bool = False
    regime_especial: str = ""


@dataclass
class Tomador:
    documento: str                 # CNPJ ou CPF
    nome: str
    logradouro: str = ""
    numero: str = ""
    bairro: str = ""
    municipio_ibge: str = ""
    uf: str = ""
    cep: str = ""
    email: str = ""


@dataclass
class Servico:
    item_lc116: str                # sem ponto — ex.: "1701"
    discriminacao: str
    valor_centavos: int            # bruto
    competencia: date
    aliquota_iss: float | None = None     # None = não definida
    iss_retido: bool = False
    municipio_incidencia: str = IBGE_ARAGUAINA
    valor_deducoes_centavos: int = 0
    valor_desconto_centavos: int = 0
    retencoes: dict = field(default_factory=dict)   # {"ir": centavos, ...}
    regime_fixo_declarado: bool = False   # sociedade com ISS fixo por profissional


# --------------------------------------------------------------------------
# Validação de documentos
# --------------------------------------------------------------------------

def so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def cpf_valido(cpf: str) -> bool:
    c = so_digitos(cpf)
    if len(c) != 11 or c == c[0] * 11:
        return False
    for corte in (9, 10):
        soma = sum(int(c[i]) * (corte + 1 - i) for i in range(corte))
        dv = (soma * 10) % 11 % 10
        if dv != int(c[corte]):
            return False
    return True


def cnpj_valido(cnpj: str) -> bool:
    c = so_digitos(cnpj)
    if len(c) != 14 or c == c[0] * 14:
        return False
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2],
                  [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        corte = len(pesos)
        soma = sum(int(c[i]) * pesos[i] for i in range(corte))
        resto = soma % 11
        dv = 0 if resto < 2 else 11 - resto
        if dv != int(c[corte]):
            return False
    return True


def documento_valido(doc: str) -> bool:
    d = so_digitos(doc)
    return cpf_valido(d) if len(d) == 11 else cnpj_valido(d) if len(d) == 14 else False


# --------------------------------------------------------------------------
# Sigilo na discriminação
# --------------------------------------------------------------------------

# Número de processo CNJ: NNNNNNN-DD.AAAA.J.TR.OOOO
PADRAO_CNJ = re.compile(r"\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}")

TERMOS_SENSIVEIS = (
    "segredo de justica", "sigiloso", "reclamada", "reclamante",
    "autor", "reu", "réu",
)


def alertas_sigilo(discriminacao: str) -> list[str]:
    """Avisos sobre exposição indevida na discriminação da nota.

    A NFS-e é consultável por terceiros com o código de verificação; o
    dever de sigilo (art. 34, VII, Lei 8.906/94) não cede por ser campo
    de documento fiscal. Estes são avisos, não bloqueios — a decisão é
    do advogado.
    """
    avisos = []
    if PADRAO_CNJ.search(discriminacao or ""):
        avisos.append(
            "A discriminação contém o que parece ser um número de processo. "
            "Considere usar a referência interna do contrato."
        )
    texto = (discriminacao or "").lower()
    achados = [t for t in TERMOS_SENSIVEIS if t in texto]
    if achados:
        avisos.append(
            f"A discriminação contém termo(s) que podem identificar a parte: "
            f"{', '.join(achados)}."
        )
    return avisos


# --------------------------------------------------------------------------
# Validação
# --------------------------------------------------------------------------

def validar(prestador: Prestador, tomador: Tomador, servico: Servico,
            hoje: date | None = None) -> list[str]:
    """Retorna a lista de bloqueios. Lista vazia = pode montar o RPS.

    Campo faltando vira bloqueio explícito, nunca campo vazio na nota.
    """
    hoje = hoje or date.today()
    erros: list[str] = []

    # Prestador
    if not cnpj_valido(prestador.cnpj):
        erros.append("CNPJ do prestador ausente ou inválido.")
    if not so_digitos(prestador.inscricao_municipal):
        erros.append("Inscrição municipal do prestador não informada.")
    if prestador.optante_simples is None:
        erros.append(
            "Opção pelo Simples Nacional não definida no cadastro do prestador "
            "— confirmar com o contador."
        )

    # Tomador
    if not documento_valido(tomador.documento):
        erros.append("CNPJ/CPF do tomador ausente ou com dígito verificador inválido.")
    if not (tomador.nome or "").strip():
        erros.append("Nome/razão social do tomador não informado.")
    for campo, rotulo in (("logradouro", "logradouro"), ("municipio_ibge", "município (IBGE)"),
                          ("uf", "UF")):
        if not (getattr(tomador, campo) or "").strip():
            erros.append(f"Endereço do tomador incompleto: {rotulo} ausente.")

    # Serviço
    item = so_digitos(servico.item_lc116)
    if not item:
        erros.append("Item da LC 116/2003 não informado.")
    elif "." in (servico.item_lc116 or ""):
        erros.append(
            "Item da LC 116/2003 com ponto — Araguaína exige o código sem ponto."
        )
    if not (servico.discriminacao or "").strip():
        erros.append("Discriminação do serviço não informada.")
    if servico.valor_centavos <= 0:
        erros.append("Valor do serviço deve ser maior que zero.")
    if servico.competencia > hoje:
        erros.append(
            f"Competência {servico.competencia:%m/%Y} é futura — a competência é "
            "o mês da prestação, não o da emissão."
        )
    if servico.aliquota_iss is None and not servico.regime_fixo_declarado:
        erros.append(
            "Alíquota de ISS não definida. Sociedade de advogados pode ter "
            "recolhimento fixo por profissional; confirmar o enquadramento com "
            "o contador e declarar o regime antes de emitir."
        )
    if servico.aliquota_iss is not None and not 0 <= servico.aliquota_iss <= 5:
        erros.append(
            f"Alíquota de ISS fora da faixa legal (0% a 5%): {servico.aliquota_iss}%."
        )

    # Valores
    if servico.valor_deducoes_centavos + servico.valor_desconto_centavos > servico.valor_centavos:
        erros.append("Deduções e descontos somados excedem o valor do serviço.")
    total_retencoes = sum(servico.retencoes.values())
    if total_retencoes > servico.valor_centavos:
        erros.append("Retenções somadas excedem o valor do serviço.")

    return erros


def base_calculo_centavos(servico: Servico) -> int:
    return (servico.valor_centavos
            - servico.valor_deducoes_centavos
            - servico.valor_desconto_centavos)


def valor_iss_centavos(servico: Servico) -> int:
    """ISS em centavos inteiros. Regime fixo devolve 0 — o valor é apurado
    fora da nota, por profissional habilitado."""
    if servico.regime_fixo_declarado or servico.aliquota_iss is None:
        return 0
    return round(base_calculo_centavos(servico) * servico.aliquota_iss / 100)


def valor_liquido_centavos(servico: Servico) -> int:
    """Líquido a receber. Não confundir com o valor do serviço, que é bruto."""
    liquido = servico.valor_centavos - servico.valor_desconto_centavos
    liquido -= sum(servico.retencoes.values())
    if servico.iss_retido:
        liquido -= valor_iss_centavos(servico)
    return liquido


# --------------------------------------------------------------------------
# Montagem do XML
# --------------------------------------------------------------------------

def _reais(centavos: int) -> str:
    return f"{centavos / 100:.2f}"


def montar_rps(prestador: Prestador, tomador: Tomador, servico: Servico,
               *, numero_rps: int, serie: str, tipo_rps: int = 1,
               data_emissao: date | None = None) -> str:
    """Monta o XML do RPS (ABRASF 2.02). Não assina e não transmite.

    Levanta ValueError se a validação não passar: montar XML a partir de
    dado incompleto só empurra o erro para mais perto da transmissão.
    """
    erros = validar(prestador, tomador, servico)
    if erros:
        raise ValueError("RPS não pode ser montado:\n- " + "\n- ".join(erros))

    data_emissao = data_emissao or date.today()
    rps_id = f"rps{numero_rps}{serie}"

    raiz = Element("Rps", xmlns=NAMESPACE)
    inf = SubElement(raiz, "InfDeclaracaoPrestacaoServico", Id=rps_id)

    ident = SubElement(SubElement(inf, "Rps"), "IdentificacaoRps")
    SubElement(ident, "Numero").text = str(numero_rps)
    SubElement(ident, "Serie").text = serie
    SubElement(ident, "Tipo").text = str(tipo_rps)

    SubElement(inf, "Competencia").text = servico.competencia.strftime("%Y-%m-%d")
    SubElement(inf, "DataEmissao").text = data_emissao.strftime("%Y-%m-%d")

    # Serviço
    serv = SubElement(inf, "Servico")
    valores = SubElement(serv, "Valores")
    SubElement(valores, "ValorServicos").text = _reais(servico.valor_centavos)
    if servico.valor_deducoes_centavos:
        SubElement(valores, "ValorDeducoes").text = _reais(servico.valor_deducoes_centavos)
    if servico.valor_desconto_centavos:
        SubElement(valores, "DescontoIncondicionado").text = _reais(servico.valor_desconto_centavos)
    for chave, tag in (("pis", "ValorPis"), ("cofins", "ValorCofins"),
                       ("inss", "ValorInss"), ("ir", "ValorIr"),
                       ("csll", "ValorCsll")):
        if servico.retencoes.get(chave):
            SubElement(valores, tag).text = _reais(servico.retencoes[chave])
    if servico.aliquota_iss is not None:
        SubElement(valores, "Aliquota").text = f"{servico.aliquota_iss:.2f}"
        SubElement(valores, "ValorIss").text = _reais(valor_iss_centavos(servico))

    SubElement(serv, "IssRetido").text = "1" if servico.iss_retido else "2"
    # Araguaína: código de serviço e código de atividade usam o item da
    # LC 116/2003 sem ponto; CTISS não é preenchido.
    SubElement(serv, "ItemListaServico").text = so_digitos(servico.item_lc116)
    SubElement(serv, "CodigoTributacaoMunicipio").text = so_digitos(servico.item_lc116)
    SubElement(serv, "Discriminacao").text = servico.discriminacao.strip()
    SubElement(serv, "CodigoMunicipio").text = servico.municipio_incidencia

    # Prestador
    prest = SubElement(inf, "Prestador")
    SubElement(prest, "CpfCnpj").append(_doc_element(prestador.cnpj))
    SubElement(prest, "InscricaoMunicipal").text = so_digitos(prestador.inscricao_municipal)

    # Tomador
    tom = SubElement(inf, "Tomador")
    ident_tom = SubElement(tom, "IdentificacaoTomador")
    SubElement(ident_tom, "CpfCnpj").append(_doc_element(tomador.documento))
    SubElement(tom, "RazaoSocial").text = tomador.nome.strip()

    end = SubElement(tom, "Endereco")
    SubElement(end, "Endereco").text = tomador.logradouro.strip()
    if tomador.numero:
        SubElement(end, "Numero").text = tomador.numero.strip()
    if tomador.bairro:
        SubElement(end, "Bairro").text = tomador.bairro.strip()
    SubElement(end, "CodigoMunicipio").text = so_digitos(tomador.municipio_ibge)
    SubElement(end, "Uf").text = tomador.uf.strip().upper()
    if tomador.cep:
        SubElement(end, "Cep").text = so_digitos(tomador.cep)
    if tomador.email:
        contato = SubElement(tom, "Contato")
        SubElement(contato, "Email").text = tomador.email.strip()

    SubElement(inf, "OptanteSimplesNacional").text = "1" if prestador.optante_simples else "2"
    SubElement(inf, "IncentivoFiscal").text = "1" if prestador.incentivador_cultural else "2"

    return tostring(raiz, encoding="unicode")


def _doc_element(documento: str) -> Element:
    d = so_digitos(documento)
    tag = "Cpf" if len(d) == 11 else "Cnpj"
    el = Element(tag)
    el.text = d
    return el


# --------------------------------------------------------------------------
# Prévia para conferência humana
# --------------------------------------------------------------------------

def previa(prestador: Prestador, tomador: Tomador, servico: Servico,
           origem: str = "") -> str:
    """Texto da prévia que o advogado confere antes de aprovar."""
    if servico.regime_fixo_declarado:
        iss = "regime fixo por profissional (declarado)"
    elif servico.aliquota_iss is None:
        iss = "ALÍQUOTA NÃO DEFINIDA"
    else:
        iss = (f"{servico.aliquota_iss:.2f}% — {brl(valor_iss_centavos(servico))} — "
               f"{'retido' if servico.iss_retido else 'não retido'}")

    linhas = [
        f"Tomador:      {tomador.nome} — {so_digitos(tomador.documento)}",
        f"Serviço:      item {so_digitos(servico.item_lc116)} (LC 116/2003)",
        f"Discriminação: {servico.discriminacao.strip()}",
        f"Competência:  {servico.competencia:%m/%Y}",
        f"Valor bruto:  {brl(servico.valor_centavos)}",
        f"ISS:          {iss}",
    ]
    if servico.retencoes:
        detalhe = ", ".join(f"{k.upper()} {brl(v)}" for k, v in servico.retencoes.items())
        linhas.append(f"Retenções:    {detalhe}")
    linhas.append(f"Líquido:      {brl(valor_liquido_centavos(servico))}")
    if origem:
        linhas.append(f"Origem:       {origem}")

    for aviso in alertas_sigilo(servico.discriminacao):
        linhas.append(f"⚠ {aviso}")
    for erro in validar(prestador, tomador, servico):
        linhas.append(f"✖ BLOQUEIO: {erro}")

    return "\n".join(linhas)


if __name__ == "__main__":
    p = Prestador(cnpj="11222333000181", inscricao_municipal="12345",
                  razao_social="Escritório Exemplo", optante_simples=True)
    t = Tomador(documento="11444777000161", nome="Cliente Exemplo Ltda",
                logradouro="Rua A", numero="100", bairro="Centro",
                municipio_ibge=IBGE_ARAGUAINA, uf="TO", cep="77800000")
    s = Servico(item_lc116="1701",
                discriminacao="Honorários advocatícios contratuais — trabalhista — competência 08/2026. Contrato REF-2026-014.",
                valor_centavos=500000, competencia=date(2026, 8, 1),
                aliquota_iss=2.0)

    print(previa(p, t, s, origem="tarefa 8821 · contrato REF-2026-014"))
    print()

    # Caso que deve bloquear: alíquota ausente e processo na discriminação.
    s2 = Servico(item_lc116="17.01",
                 discriminacao="Honorários — processo 0000123-45.2026.5.10.0821 — reclamante João",
                 valor_centavos=500000, competencia=date(2026, 8, 1))
    print(previa(p, t, s2))
