"""
Registro de eventos de auditoria.

Wrapper fino sobre a tabela `Auditoria`. Centralizar aqui garante que todo
evento relevante seja gravado de forma consistente.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..db import Auditoria


def registrar(
    db: Session,
    exame_id: str,
    evento: str,
    ator: str = "sistema",
    detalhe: str | None = None,
) -> None:
    db.add(Auditoria(exame_id=exame_id, evento=evento, ator=ator, detalhe=detalhe))
    db.commit()
