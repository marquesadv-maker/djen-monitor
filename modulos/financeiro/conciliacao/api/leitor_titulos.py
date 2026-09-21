"""
Leitura de títulos (contas a receber e a pagar) a partir de arquivo
exportado do Projuris.

Existe porque os endpoints financeiros do Projuris **não foram
confirmados** (references/projuris-financeiro.md, seção 4) e caminho
adivinhado pode ler — ou gravar — no lugar errado. Enquanto a inspeção
no DevTools não acontece, o módulo trabalha com o arquivo que a própria
tela do Projuris exporta, que é dado real sem chute de integração.

Quando os endpoints forem confirmados, `shared/projuris_financeiro.py`
passa a alimentar as mesmas estruturas `Titulo` e nada aqui precisa mudar.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date

from .leitor_extrato import (_converter_data, _decodificar, _detectar_separador,
                             _numerico)
from .motor_conciliacao import Titulo, normalizar_texto, parse_valor_br

CABECALHOS = {
    "id": ("id", "codigo", "codigo titulo", "numero titulo", "titulo",
           "identificador", "cod"),
    "tipo": ("tipo", "natureza", "especie", "receber pagar", "movimento"),
    "descricao": ("descricao", "historico", "observacao", "complemento",
                  "referencia"),
    "contraparte": ("cliente", "fornecedor", "contraparte", "nome",
                    "razao social", "cliente fornecedor", "parte", "favorecido"),
    "valor": ("valor", "valor titulo", "valor r", "vlr", "valor original",
              "valor previsto"),
    "vencimento": ("vencimento", "data vencimento", "dt vencimento", "vence em",
                   "data de vencimento"),
    "documento": ("documento", "cpf cnpj", "cnpj cpf", "doc", "n documento",
                  "numero documento", "nf", "nota fiscal"),
    "status": ("status", "situacao", "situacao titulo", "baixado", "pago"),
    # Opcionais: alimentam os filtros do dashboard quando a exportação os traz.
    "banco": ("banco", "conta", "conta bancaria", "instituicao"),
    "forma_pagamento": ("forma", "forma pagamento", "forma de pagamento",
                        "meio pagamento", "modalidade"),
    "categoria": ("categoria", "centro de custo", "centro custo", "classificacao",
                  "plano de contas", "conta contabil"),
}

OPCIONAIS = ("banco", "forma_pagamento", "categoria")

RECEBER = ("receber", "recebimento", "receita", "entrada", "credito", "r")
PAGAR = ("pagar", "pagamento", "despesa", "saida", "debito", "p")

ABERTOS = ("aberto", "em aberto", "pendente", "a receber", "a pagar",
           "nao pago", "vencido", "a vencer", "previsto")
PAGOS = ("pago", "baixado", "liquidado", "quitado", "recebido", "conciliado")
CANCELADOS = ("cancelado", "estornado", "inativo")


@dataclass
class ResultadoTitulos:
    titulos: list[Titulo] = field(default_factory=list)
    ignoradas: int = 0
    motivos_ignoradas: dict[str, int] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    erro: str = ""
    colunas: list[str] = field(default_factory=list)
    # Dimensões que o motor não usa, mas que o dashboard filtra: {id: {campo: valor}}
    extras: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.erro

    def resumo(self) -> str:
        if self.erro:
            return self.erro
        abertos = len([t for t in self.titulos if t.status in ("aberto", "parcial")])
        partes = [f"Li {len(self.titulos)} título(s), {abertos} em aberto"]
        if self.ignoradas:
            detalhe = ", ".join(f"{qtd} {motivo}"
                                for motivo, qtd in sorted(self.motivos_ignoradas.items()))
            partes.append(f"ignorei {self.ignoradas} linha(s) ({detalhe})")
        return " e ".join(partes) + "."

    def _ignorar(self, motivo: str) -> None:
        self.ignoradas += 1
        self.motivos_ignoradas[motivo] = self.motivos_ignoradas.get(motivo, 0) + 1


def ler_titulos(conteudo: bytes, nome_arquivo: str = "",
                tipo_padrao: str = "") -> ResultadoTitulos:
    """CSV ou XLSX exportado da tela financeira do Projuris.

    `tipo_padrao` ("receber" ou "pagar") é usado quando o arquivo não tem
    coluna de tipo — o caso de quem exporta as duas listas separadamente.
    """
    resultado = ResultadoTitulos()
    if not conteudo:
        resultado.erro = "Arquivo de títulos vazio."
        return resultado

    nome = (nome_arquivo or "").lower()
    if nome.endswith((".xlsx", ".xlsm")) or conteudo[:2] == b"PK":
        tabela = _tabela_de_xlsx(conteudo, resultado)
        if resultado.erro:
            return resultado
    else:
        texto, _ = _decodificar(conteudo)
        linhas = [l for l in texto.splitlines() if l.strip()]
        if not linhas:
            resultado.erro = "Arquivo de títulos sem conteúdo legível."
            return resultado
        separador = _detectar_separador(linhas)
        tabela = list(csv.reader(io.StringIO("\n".join(linhas)), delimiter=separador))

    linha_cab, indices = _localizar_cabecalho(tabela)
    resultado.colunas = list(tabela[linha_cab]) if 0 <= linha_cab < len(tabela) else []

    faltando = [c for c in ("valor", "vencimento") if c not in indices]
    if faltando:
        resultado.erro = (
            "Não reconheci as colunas obrigatórias do arquivo de títulos: "
            f"{', '.join(faltando)}. Esperado, no mínimo, valor e vencimento; "
            "contraparte e documento melhoram muito o cruzamento."
        )
        return resultado

    if "tipo" not in indices and tipo_padrao not in ("receber", "pagar"):
        resultado.erro = (
            "O arquivo não tem coluna de tipo (receber/pagar) e nenhum tipo "
            "foi informado. Indique se esta lista é de contas a receber ou a pagar."
        )
        return resultado

    for bruta in tabela[linha_cab + 1:]:
        if not any(str(c).strip() for c in bruta):
            continue

        vencimento = _converter_data(_col(bruta, indices.get("vencimento")))
        if vencimento is None:
            resultado._ignorar("sem vencimento válido")
            continue

        bruto_valor = _col(bruta, indices.get("valor"))
        if not _numerico(bruto_valor):
            resultado._ignorar("valor não numérico")
            continue
        valor = abs(parse_valor_br(bruto_valor))

        tipo = _classificar_tipo(_col(bruta, indices.get("tipo")), tipo_padrao)
        if not tipo:
            resultado._ignorar("tipo indefinido")
            continue

        identificador = (_col(bruta, indices.get("id"))
                         or f"T{len(resultado.titulos) + 1:05d}")
        resultado.extras[identificador] = {
            campo: _col(bruta, indices.get(campo))
            for campo in OPCIONAIS if campo in indices
        }
        resultado.titulos.append(Titulo(
            id=identificador,
            tipo=tipo,
            descricao=_col(bruta, indices.get("descricao")),
            contraparte=_col(bruta, indices.get("contraparte")),
            valor_centavos=valor,
            vencimento=vencimento,
            documento=_col(bruta, indices.get("documento")),
            status=_classificar_status(_col(bruta, indices.get("status"))),
        ))

    if "documento" not in indices:
        resultado.avisos.append(
            "Os títulos vieram sem CPF/CNPJ. A regra R1 (documento exato), que "
            "é a mais forte do motor, não vai pontuar neste cruzamento."
        )
    if "contraparte" not in indices:
        resultado.avisos.append(
            "Os títulos vieram sem nome de cliente/fornecedor. Só valor e data "
            "vão sustentar o cruzamento."
        )
    if "status" not in indices:
        resultado.avisos.append(
            "Sem coluna de situação, tratei todos os títulos como em aberto — "
            "confira se algum já estava baixado antes de aprovar qualquer item."
        )
    return resultado


def _tabela_de_xlsx(conteudo: bytes, resultado: ResultadoTitulos) -> list[list[str]]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        resultado.erro = ("Não consigo ler XLSX neste ambiente (openpyxl ausente). "
                          "Exporte os títulos em CSV.")
        return []
    try:
        planilha = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception as erro:
        resultado.erro = f"Não consegui abrir a planilha de títulos: {erro}"
        return []
    aba = planilha[planilha.sheetnames[0]]
    tabela = [["" if c is None else str(c).strip() for c in linha]
              for linha in aba.iter_rows(values_only=True)]
    planilha.close()
    return tabela


def _localizar_cabecalho(tabela: list[list[str]]) -> tuple[int, dict[str, int]]:
    melhor_linha, melhores = -1, {}
    for i, linha in enumerate(tabela[:15]):
        indices: dict[str, int] = {}
        # Duas passagens: o nome exato tem prioridade sobre o prefixo, senão
        # "conta contábil" cairia em "conta" (banco) por ser mais curto.
        for exato in (True, False):
            for j, celula in enumerate(linha):
                alvo = normalizar_texto(str(celula))
                if not alvo or j in indices.values():
                    continue
                for campo, variacoes in CABECALHOS.items():
                    if campo in indices:
                        continue
                    casa = (alvo in variacoes if exato
                            else any(alvo.startswith(v) for v in variacoes))
                    if casa:
                        indices[campo] = j
                        break
        if len(indices) > len(melhores):
            melhor_linha, melhores = i, indices
    return melhor_linha, melhores


def _col(linha: list[str], indice: int | None) -> str:
    if indice is None or indice >= len(linha):
        return ""
    return str(linha[indice]).strip()


def _classificar_tipo(bruto: str, padrao: str) -> str:
    alvo = normalizar_texto(bruto)
    if alvo:
        if any(alvo.startswith(p) for p in RECEBER):
            return "receber"
        if any(alvo.startswith(p) for p in PAGAR):
            return "pagar"
    return padrao if padrao in ("receber", "pagar") else ""


def _classificar_status(bruto: str) -> str:
    """Status desconhecido vira 'aberto' e o aviso correspondente é emitido:
    tratar um título já baixado como aberto é o caminho da dupla baixa."""
    alvo = normalizar_texto(bruto)
    if not alvo:
        return "aberto"
    if any(alvo.startswith(p) for p in CANCELADOS):
        return "cancelado"
    if any(alvo.startswith(p) for p in PAGOS):
        return "pago"
    if "parcial" in alvo:
        return "parcial"
    if any(alvo.startswith(p) for p in ABERTOS):
        return "aberto"
    return "aberto"


def vencidos(titulos: list[Titulo], referencia: date | None = None) -> list[Titulo]:
    """Títulos em aberto com vencimento passado — usado no gráfico de status."""
    referencia = referencia or date.today()
    return [t for t in titulos
            if t.status in ("aberto", "parcial") and t.vencimento < referencia]
