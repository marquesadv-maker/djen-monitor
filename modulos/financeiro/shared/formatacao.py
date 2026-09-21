"""
Formatação de moeda em reais — utilitário sem estado, comum às duas abas.

Fica em `shared/` porque é apresentação (como formatar um número), não
regra de negócio das abas (como uma conta é conciliada ou uma nota é
validada) — não conflita com a separação de `conciliacao/` e `nfse/`
documentada no README, que é sobre lógica de domínio, não sobre um
formatador de string.
"""

from __future__ import annotations


def brl(centavos: int | None, abreviar: bool = False) -> str:
    """`R$ 1.234.567,89`. Negativo vira `-R$ ...`. Abreviação só acima de
    1 milhão, quando pedida. `None` vira "—" (dado ausente, não zero)."""
    if centavos is None:
        return "—"
    negativo = centavos < 0
    valor = abs(centavos) / 100
    if abreviar and valor >= 1_000_000:
        texto = f"R$ {valor / 1_000_000:.1f} Mi".replace(".", ",")
    else:
        inteiro = f"{valor:,.2f}".replace(",", "~").replace(".", ",").replace("~", ".")
        texto = f"R$ {inteiro}"
    return f"-{texto}" if negativo else texto
