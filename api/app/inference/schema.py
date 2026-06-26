"""
Schema estruturado do laudo de raio-X de tórax.

Este é o coração da qualidade do produto: em vez de deixar o modelo gerar
texto livre (onde alucinações se escondem com facilidade), forçamos a saída
a preencher um schema clínico padronizado. Cada achado vira um campo
auditável, com presença/ausência explícita e nível de confiança.

O médico revisa campo a campo. Nada é assinado automaticamente.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Presenca(str, Enum):
    """Presença de um achado. 'indeterminado' é um valor de primeira classe:
    é melhor o modelo admitir incerteza do que inventar uma certeza."""

    ausente = "ausente"
    presente = "presente"
    indeterminado = "indeterminado"


class Lateralidade(str, Enum):
    nao_aplicavel = "nao_aplicavel"
    direita = "direita"
    esquerda = "esquerda"
    bilateral = "bilateral"


class Gravidade(str, Enum):
    """Usada para priorização da worklist. 'critico' fura a fila."""

    normal = "normal"
    leve = "leve"
    moderado = "moderado"
    acentuado = "acentuado"
    critico = "critico"


class Achado(BaseModel):
    """Um achado individual e auditável."""

    presenca: Presenca = Presenca.ausente
    lateralidade: Lateralidade = Lateralidade.nao_aplicavel
    gravidade: Gravidade = Gravidade.normal
    descricao: Optional[str] = Field(
        default=None,
        description="Descrição livre curta do achado, quando presente.",
    )
    # Confiança auto-reportada pelo modelo (0-1). NÃO é probabilidade calibrada;
    # serve para ordenar a atenção do médico, não para decisão clínica.
    confianca: float = Field(default=0.0, ge=0.0, le=1.0)


class QualidadeTecnica(BaseModel):
    """Avaliação da qualidade da imagem. Imagem ruim => laudo não confiável.
    Sinalizar isso é um diferencial de segurança."""

    adequada: bool = True
    incidencia: Optional[str] = Field(
        default=None, description="PA, AP, perfil, etc."
    )
    observacoes: Optional[str] = None


class AchadosTorax(BaseModel):
    """Conjunto padronizado de achados de raio-X de tórax.

    A lista segue a leitura sistemática clássica (ABCDE / campos pulmonares,
    mediastino, silhueta cardíaca, ossos, partes moles, dispositivos).
    """

    # Achados de via aérea / parênquima
    consolidacao: Achado = Field(default_factory=Achado)
    opacidade_intersticial: Achado = Field(default_factory=Achado)
    nodulo_ou_massa: Achado = Field(default_factory=Achado)
    atelectasia: Achado = Field(default_factory=Achado)

    # Pleura
    derrame_pleural: Achado = Field(default_factory=Achado)
    pneumotorax: Achado = Field(default_factory=Achado)

    # Mediastino / coração
    cardiomegalia: Achado = Field(default_factory=Achado)
    alargamento_mediastinal: Achado = Field(default_factory=Achado)
    congestao_pulmonar: Achado = Field(default_factory=Achado)

    # Ossos / partes moles
    fratura: Achado = Field(default_factory=Achado)

    # Dispositivos (tubos, cateteres, marca-passo) — relevante em hospital,
    # mantido aqui para o schema já nascer completo.
    dispositivos: Achado = Field(default_factory=Achado)


class Laudo(BaseModel):
    """Rascunho de laudo gerado pela IA. SEMPRE marcado como não validado
    até a assinatura do médico."""

    qualidade_tecnica: QualidadeTecnica = Field(default_factory=QualidadeTecnica)
    achados: AchadosTorax = Field(default_factory=AchadosTorax)
    impressao: str = Field(
        default="",
        description="Síntese diagnóstica em texto, derivada dos achados.",
    )
    achados_criticos: list[str] = Field(
        default_factory=list,
        description=(
            "Lista de achados que exigem comunicação imediata "
            "(ex.: pneumotórax hipertensivo, pneumotórax, derrame volumoso)."
        ),
    )
    gerado_por_ia: bool = True
    validado_por_medico: bool = False


# Achados que, se presentes, disparam priorização crítica na worklist.
ACHADOS_CRITICOS = {
    "pneumotorax": "Pneumotórax",
    "derrame_pleural": "Derrame pleural volumoso",
}


def extrair_criticos(achados: AchadosTorax) -> list[str]:
    """Deriva a lista de achados críticos a partir dos achados estruturados.

    Centraliza a regra de criticidade em código (não confiamos no modelo para
    isso) — assim a priorização é determinística e auditável.
    """
    criticos: list[str] = []
    for campo, rotulo in ACHADOS_CRITICOS.items():
        achado: Achado = getattr(achados, campo)
        if achado.presenca == Presenca.presente and achado.gravidade in (
            Gravidade.moderado,
            Gravidade.acentuado,
            Gravidade.critico,
        ):
            criticos.append(rotulo)
    return criticos
