"""
Métricas de avaliação por achado.

Para cada campo do laudo montamos uma matriz de confusão (TP/FP/FN/TN) e
derivamos sensibilidade (recall) e especificidade.

Foco clínico: em rastreio, **sensibilidade em achados críticos** é o número que
mais importa — perder um pneumotórax é muito pior que um falso positivo. Por
isso, na conversão da saída do modelo para "positivo/negativo", os achados
críticos usam política conservadora: `indeterminado` conta como POSITIVO
(na dúvida, sinaliza para o médico). Achados não-críticos usam `indeterminado`
como negativo, para não inflar falsos positivos.
"""

from __future__ import annotations

from dataclasses import dataclass

# Campos considerados críticos (devem priorizar sensibilidade).
CRITICOS = {"pneumotorax", "derrame_pleural"}


def pred_positiva(presenca: str, critico: bool) -> bool:
    """Converte a presença do modelo em decisão binária positivo/negativo."""
    if presenca == "presente":
        return True
    if presenca == "indeterminado":
        return critico  # crítico: na dúvida, positivo
    return False


@dataclass
class Contagem:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def add(self, gt: bool, pred: bool) -> None:
        if gt and pred:
            self.tp += 1
        elif gt and not pred:
            self.fn += 1
        elif not gt and pred:
            self.fp += 1
        else:
            self.tn += 1

    @property
    def suporte(self) -> int:
        """Número de casos positivos na verdade-base."""
        return self.tp + self.fn

    @property
    def sensibilidade(self) -> float | None:
        d = self.tp + self.fn
        return self.tp / d if d else None

    @property
    def especificidade(self) -> float | None:
        d = self.tn + self.fp
        return self.tn / d if d else None

    def somar(self, outra: "Contagem") -> None:
        self.tp += outra.tp
        self.fp += outra.fp
        self.fn += outra.fn
        self.tn += outra.tn


def _fmt(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:5.1f}%"


def tabela_texto(por_campo: dict[str, Contagem]) -> str:
    """Formata as métricas por campo numa tabela legível."""
    linhas = [
        f"{'achado':<24} {'n+':>4} {'TP':>4} {'FP':>4} {'FN':>4} "
        f"{'sens':>7} {'espec':>7}{'  crítico' :>9}"
    ]
    linhas.append("-" * 72)
    # Críticos primeiro.
    campos = sorted(por_campo, key=lambda c: (c not in CRITICOS, c))
    for campo in campos:
        c = por_campo[campo]
        marca = "  << critico" if campo in CRITICOS else ""
        linhas.append(
            f"{campo:<24} {c.suporte:>4} {c.tp:>4} {c.fp:>4} {c.fn:>4} "
            f"{_fmt(c.sensibilidade):>7} {_fmt(c.especificidade):>7}{marca}"
        )
    return "\n".join(linhas)


def resumo(por_campo: dict[str, Contagem]) -> dict:
    """Agrega métricas globais e específicas de críticos para o JSON de saída."""
    geral = Contagem()
    criticos = Contagem()
    for campo, c in por_campo.items():
        geral.somar(c)
        if campo in CRITICOS:
            criticos.somar(c)
    return {
        "geral": {
            "sensibilidade": geral.sensibilidade,
            "especificidade": geral.especificidade,
            "tp": geral.tp, "fp": geral.fp, "fn": geral.fn, "tn": geral.tn,
        },
        "criticos": {
            "sensibilidade": criticos.sensibilidade,
            "especificidade": criticos.especificidade,
            "perdidos": criticos.fn,  # achados críticos NÃO detectados
            "suporte": criticos.suporte,
        },
        "por_campo": {
            campo: {
                "sensibilidade": c.sensibilidade,
                "especificidade": c.especificidade,
                "tp": c.tp, "fp": c.fp, "fn": c.fn, "tn": c.tn,
            }
            for campo, c in por_campo.items()
        },
    }
