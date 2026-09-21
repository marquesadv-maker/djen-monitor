"""
Leitura das tarefas de Nota Fiscal pendentes, a partir de arquivo
exportado do Projuris.

Mesma razão do leitor de títulos: os endpoints de tarefas de NF **não
estão confirmados** (SKILL.md, "Estado atual"). Até a inspeção real
acontecer, a lista de pendentes vem da exportação da própria tela — dado
real, sem endpoint adivinhado.

Cada linha vira uma `TarefaNF`, que a aba converte em Tomador + Serviço
do `rps_builder`. Campo que o arquivo não trouxer fica vazio e vira
bloqueio na prévia, nunca preenchimento por dedução.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

CABECALHOS = {
    "tarefa": ("tarefa", "id tarefa", "codigo tarefa", "id", "codigo",
               "numero tarefa"),
    "tomador_nome": ("cliente", "tomador", "razao social", "nome",
                     "nome cliente", "contraparte"),
    "tomador_documento": ("cnpj", "cpf", "cpf cnpj", "cnpj cpf", "documento",
                          "documento cliente"),
    "valor": ("valor", "valor servico", "valor honorarios", "honorarios",
              "valor r", "valor bruto"),
    "competencia": ("competencia", "mes competencia", "referencia mes",
                    "data competencia", "mes referencia"),
    "descricao": ("descricao", "discriminacao", "servico", "observacao",
                  "detalhamento"),
    "referencia_interna": ("contrato", "referencia", "ref interna",
                           "referencia interna", "ref contrato"),
    "area": ("area", "materia", "area atuacao", "especialidade"),
    "responsavel": ("responsavel", "advogado", "usuario"),
    "email": ("email", "e mail", "email cliente"),
}

FORMATOS_COMPETENCIA = ("%m/%Y", "%Y-%m", "%m-%Y", "%d/%m/%Y", "%Y-%m-%d")


@dataclass
class TarefaNF:
    tarefa: str
    tomador_nome: str = ""
    tomador_documento: str = ""
    valor_centavos: int = 0
    competencia: date | None = None
    descricao: str = ""
    referencia_interna: str = ""
    area: str = ""
    responsavel: str = ""
    email: str = ""

    @property
    def faltando(self) -> list[str]:
        """O que impede montar o RPS desta tarefa, em português de tela."""
        faltas = []
        if not self.tomador_documento:
            faltas.append("CNPJ/CPF do tomador")
        if not self.tomador_nome:
            faltas.append("nome do tomador")
        if self.valor_centavos <= 0:
            faltas.append("valor do serviço")
        if self.competencia is None:
            faltas.append("competência")
        return faltas


@dataclass
class ResultadoTarefas:
    tarefas: list[TarefaNF] = field(default_factory=list)
    ignoradas: int = 0
    avisos: list[str] = field(default_factory=list)
    erro: str = ""

    @property
    def ok(self) -> bool:
        return not self.erro

    def resumo(self) -> str:
        if self.erro:
            return self.erro
        completas = len([t for t in self.tarefas if not t.faltando])
        texto = (f"Li {len(self.tarefas)} tarefa(s) de nota fiscal, "
                 f"{completas} com todos os campos obrigatórios")
        if self.ignoradas:
            texto += f"; ignorei {self.ignoradas} linha(s) sem dados"
        return texto + "."


def ler_tarefas(conteudo: bytes, nome_arquivo: str = "") -> ResultadoTarefas:
    resultado = ResultadoTarefas()
    if not conteudo:
        resultado.erro = "Arquivo de tarefas vazio."
        return resultado

    if (nome_arquivo or "").lower().endswith((".xlsx", ".xlsm")) or conteudo[:2] == b"PK":
        resultado.erro = ("Exporte as tarefas de nota fiscal em CSV. "
                          "A leitura de XLSX nesta aba ainda não está implementada.")
        return resultado

    texto = _decodificar(conteudo)
    linhas = [l for l in texto.splitlines() if l.strip()]
    if not linhas:
        resultado.erro = "Arquivo de tarefas sem conteúdo legível."
        return resultado

    separador = max((";", ",", "\t"), key=lambda s: "\n".join(linhas[:10]).count(s))
    tabela = list(csv.reader(io.StringIO("\n".join(linhas)), delimiter=separador))

    indices = _mapear_cabecalho(tabela[0] if tabela else [])
    obrigatorias = [c for c in ("tomador_documento", "valor") if c not in indices]
    if obrigatorias:
        resultado.erro = (
            "Não reconheci as colunas mínimas do arquivo de tarefas "
            f"({', '.join(obrigatorias)}). Esperado ao menos documento do "
            "tomador e valor; competência, discriminação e contrato evitam "
            "preenchimento manual depois."
        )
        return resultado

    for bruta in tabela[1:]:
        if not any(str(c).strip() for c in bruta):
            continue

        documento = re.sub(r"\D", "", _col(bruta, indices.get("tomador_documento")))
        valor = _centavos(_col(bruta, indices.get("valor")))
        if not documento and valor == 0:
            resultado.ignoradas += 1
            continue

        resultado.tarefas.append(TarefaNF(
            tarefa=_col(bruta, indices.get("tarefa")) or f"NF{len(resultado.tarefas) + 1:04d}",
            tomador_nome=_col(bruta, indices.get("tomador_nome")),
            tomador_documento=documento,
            valor_centavos=valor,
            competencia=_competencia(_col(bruta, indices.get("competencia"))),
            descricao=_col(bruta, indices.get("descricao")),
            referencia_interna=_col(bruta, indices.get("referencia_interna")),
            area=_col(bruta, indices.get("area")),
            responsavel=_col(bruta, indices.get("responsavel")),
            email=_col(bruta, indices.get("email")),
        ))

    if "competencia" not in indices:
        resultado.avisos.append(
            "O arquivo não traz competência. Ela é o mês da prestação, não o "
            "da emissão, e precisa ser informada nota a nota."
        )
    if "referencia_interna" not in indices:
        resultado.avisos.append(
            "Sem referência de contrato, a discriminação tende a citar o "
            "processo — o que expõe a parte numa nota consultável por terceiros."
        )
    incompletas = [t.tarefa for t in resultado.tarefas if t.faltando]
    if incompletas:
        resultado.avisos.append(
            f"{len(incompletas)} tarefa(s) com campo obrigatório ausente: "
            f"{', '.join(incompletas[:8])}{'…' if len(incompletas) > 8 else ''}."
        )
    return resultado


# --------------------------------------------------------------------------
# Auxiliares
# --------------------------------------------------------------------------

def _decodificar(conteudo: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return conteudo.decode(encoding)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("latin-1", errors="replace")


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto or "")
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", texto)).strip()


def _mapear_cabecalho(linha: list[str]) -> dict[str, int]:
    indices: dict[str, int] = {}
    for exato in (True, False):
        for j, celula in enumerate(linha):
            alvo = _normalizar(str(celula))
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
    return indices


def _col(linha: list[str], indice: int | None) -> str:
    if indice is None or indice >= len(linha):
        return ""
    return str(linha[indice]).strip()


def _centavos(bruto: str) -> int:
    if not re.search(r"\d", bruto or ""):
        return 0
    s = re.sub(r"[^\d,.-]", "", bruto)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return int(round(float(s) * 100))
    except ValueError:
        return 0


def _competencia(bruto: str) -> date | None:
    bruto = (bruto or "").strip()
    if not bruto:
        return None
    for formato in FORMATOS_COMPETENCIA:
        try:
            convertida = datetime.strptime(bruto, formato).date()
            return convertida.replace(day=1)
        except ValueError:
            continue
    return None
