"""
Transmissão de NFS-e ao web service WebISS de Araguaína/TO (ABRASF 2.02).

Bloqueado por padrão. Em Araguaína não há cancelamento de NFS-e por web
service — a correção exige substituição de nota pelo portal. Uma nota
transmitida por engano vira obrigação tributária e documento errado na
mão do cliente.

Habilitar exige, nesta ordem:
  1. URL do WSDL obtida da prefeitura (não adivinhada) e registrada em URLS;
  2. homologação liberada pela prefeitura e notas de teste conferidas;
  3. instanciar com ambiente="producao" e aprovação item a item.

Dependências de assinatura XML (lxml, signxml ou equivalente) não estão
incluídas aqui: a assinatura precisa ser validada contra o schema real na
homologação antes de ser fixada em código.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# URLs do web service. Preencher SOMENTE com valor obtido da Secretaria da
# Fazenda ou da documentação oficial do provedor. Caminho adivinhado pode
# falhar de um jeito que parece sucesso.
URLS: dict[str, str] = {
    # "homologacao": "",
    # "producao": "",
}

AMBIENTES = ("homologacao", "producao")


class TransmissaoBloqueada(RuntimeError):
    """Transmissão sem habilitação explícita."""


class UrlNaoConfirmada(RuntimeError):
    """URL do web service ainda não obtida de fonte oficial."""


class CertificadoIndisponivel(RuntimeError):
    """Certificado A1 ausente, vencido ou sem senha."""


@dataclass
class RegistroEmissao:
    momento: str
    usuario: str
    ambiente: str
    tarefa_origem: str
    tomador_documento: str
    valor_centavos: int
    numero_rps: int
    serie_rps: str
    numero_nfse: str = ""
    codigo_verificacao: str = ""
    resultado: str = "pendente"
    resposta: str = ""


@dataclass
class ControleNumeracao:
    """Numeração de RPS por série, persistida em disco.

    Reiniciar a contagem gera rejeição por RPS duplicado; pular números
    levanta pergunta em fiscalização. Por isso a numeração vive em arquivo,
    não em memória.
    """
    caminho: Path
    _estado: dict = field(default_factory=dict)

    def __post_init__(self):
        self.caminho = Path(self.caminho)
        if self.caminho.exists():
            self._estado = json.loads(self.caminho.read_text(encoding="utf-8"))

    def proximo(self, serie: str) -> int:
        return int(self._estado.get(serie, 0)) + 1

    def confirmar(self, serie: str, numero: int) -> None:
        """Registra o número como usado. Chame SOMENTE após transmissão
        bem-sucedida — confirmar antes cria lacuna se o envio falhar."""
        atual = int(self._estado.get(serie, 0))
        if numero <= atual:
            raise ValueError(
                f"Número {numero} da série {serie} já foi usado (último: {atual})."
            )
        self._estado[serie] = numero
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho.write_text(json.dumps(self._estado, indent=2), encoding="utf-8")


class NfseWebISS:
    def __init__(self, *, ambiente: str = "homologacao",
                 certificado_pfx: str | Path,
                 senha_certificado: str,
                 numeracao: ControleNumeracao,
                 permitir_transmissao: bool = False):
        if ambiente not in AMBIENTES:
            raise ValueError(f"Ambiente inválido: {ambiente}. Use {AMBIENTES}.")

        self.ambiente = ambiente
        self.permitir_transmissao = permitir_transmissao
        self.numeracao = numeracao
        self._pfx = Path(certificado_pfx)
        self._senha = senha_certificado
        self.log: list[RegistroEmissao] = []

        self._conferir_certificado()

    # ------------------------------------------------------------ segurança

    def _conferir_certificado(self) -> None:
        if not self._pfx.exists():
            raise CertificadoIndisponivel(
                f"Certificado não encontrado em {self._pfx}. O .pfx fica no "
                "repositório comum de certificados, com permissão restrita — "
                "não dentro do módulo nem na pasta de outro robô."
            )
        if not self._senha:
            raise CertificadoIndisponivel(
                "Senha do certificado não informada. Use variável de ambiente "
                "ou cofre; nunca arquivo versionado."
            )

    def validade_certificado(self) -> Optional[datetime]:
        """Data de expiração do A1, quando a leitura for possível.

        O A1 vale 1 ano e a falha por vencimento aparece como erro genérico
        de assinatura — vale alertar 30 dias antes.
        """
        try:
            from cryptography.hazmat.primitives.serialization import pkcs12
            _, cert, _ = pkcs12.load_key_and_certificates(
                self._pfx.read_bytes(), self._senha.encode()
            )
            return cert.not_valid_after if cert else None
        except ImportError:
            return None

    def _url(self) -> str:
        url = URLS.get(self.ambiente)
        if not url:
            raise UrlNaoConfirmada(
                f"URL do web service para '{self.ambiente}' não registrada. "
                "Obtenha da Secretaria Municipal da Fazenda de Araguaína junto "
                "com a liberação de homologação e registre em URLS. Ver "
                "references/nfse/webiss-araguaina.md."
            )
        return url

    # -------------------------------------------------------------- consulta

    def consultar_por_rps(self, numero_rps: int, serie: str,
                          prestador_cnpj: str, inscricao_municipal: str) -> dict | None:
        """Verifica se já existe NFS-e para este RPS.

        Rode antes de cada transmissão: é a defesa contra emitir a mesma
        nota duas vezes quando a tarefa não foi concluída no Projuris.
        """
        self._url()   # falha cedo se a URL não estiver registrada
        raise NotImplementedError(
            "ConsultarNfsePorRps precisa ser implementado contra o WSDL real, "
            "validado em homologação. Ver references/nfse/webiss-araguaina.md."
        )

    # ------------------------------------------------------------ transmissão

    def gerar_nfse(self, *, xml_rps: str, numero_rps: int, serie: str,
                   tarefa_origem: str, tomador_documento: str,
                   valor_centavos: int, usuario: str) -> dict:
        """Transmite uma nota. Exige permitir_transmissao=True.

        Uma nota por chamada — lote dá menos rastreabilidade e pode ficar
        parcialmente processado.
        """
        if not self.permitir_transmissao:
            raise TransmissaoBloqueada(
                "Transmissão bloqueada. Em Araguaína a NFS-e não pode ser "
                "cancelada por web service (só substituição, pelo portal), "
                "então o envio exige URL oficial registrada, homologação "
                "conferida e aprovação explícita desta nota."
            )

        url = self._url()

        registro = RegistroEmissao(
            momento=datetime.now().isoformat(timespec="seconds"),
            usuario=usuario,
            ambiente=self.ambiente,
            tarefa_origem=tarefa_origem,
            tomador_documento=tomador_documento,
            valor_centavos=valor_centavos,
            numero_rps=numero_rps,
            serie_rps=serie,
        )
        self.log.append(registro)

        raise NotImplementedError(
            f"GerarNfse precisa ser implementado contra o WSDL real ({url}), "
            "com assinatura XML-DSig validada primeiro no validador da Receita "
            "Federal e depois em homologação. Ver references/nfse/webiss-araguaina.md."
        )

    # ------------------------------------------------------------- auditoria

    def exportar_log(self, caminho: str | Path) -> None:
        """Append-only. O campo 'ambiente' é o que distingue nota de teste
        de nota real quando o log for revisto meses depois."""
        caminho = Path(caminho)
        existente = []
        if caminho.exists():
            try:
                existente = json.loads(caminho.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existente = []
        existente.extend(vars(r) for r in self.log)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(existente, ensure_ascii=False, indent=2),
                           encoding="utf-8")


if __name__ == "__main__":
    print(__doc__)
    print("Ambientes com URL registrada:",
          [a for a in AMBIENTES if URLS.get(a)] or "nenhum — obter da prefeitura")
