"""
Persistência (SQLAlchemy + PostgreSQL).

Guardamos metadados, o laudo estruturado (JSON), o status do fluxo de revisão
e a trilha de auditoria. A IMAGEM em si fica no PACS (Orthanc), não no banco —
o banco referencia pelos UIDs DICOM.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import JSON, DateTime, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://medlaudo:medlaudo@db:5432/medlaudo"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class StatusExame(str, Enum):
    aguardando = "aguardando"        # DICOM recebido, ainda não inferido
    rascunho_pronto = "rascunho_pronto"  # IA gerou rascunho, aguardando médico
    em_revisao = "em_revisao"        # médico abriu
    assinado = "assinado"            # laudo final assinado
    rejeitado = "rejeitado"          # médico descartou o rascunho


def _agora() -> datetime:
    return datetime.now(timezone.utc)


class Exame(Base):
    __tablename__ = "exames"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    study_instance_uid: Mapped[str] = mapped_column(String, index=True)
    sop_instance_uid: Mapped[str] = mapped_column(String, index=True)
    modalidade: Mapped[str] = mapped_column(String, default="DX")
    incidencia: Mapped[str | None] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(
        String, default=StatusExame.aguardando.value, index=True
    )
    critico: Mapped[bool] = mapped_column(default=False, index=True)

    # Rascunho gerado pela IA (snapshot imutável do que o modelo produziu).
    laudo_ia: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Laudo final editado/assinado pelo médico.
    laudo_final: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    medico_responsavel: Mapped[str | None] = mapped_column(String, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_agora, onupdate=_agora
    )


class Medico(Base):
    """Médico radiologista que revisa e assina laudos."""

    __tablename__ = "medicos"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    nome: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    crm: Mapped[str | None] = mapped_column(String, nullable=True)
    senha_hash: Mapped[str] = mapped_column(String)
    ativo: Mapped[bool] = mapped_column(default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora)


class Auditoria(Base):
    """Trilha de auditoria append-only. Cada evento relevante vira um registro.
    Essencial para conformidade e para medir ROI (tempo de laudo, edições)."""

    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exame_id: Mapped[str] = mapped_column(String, index=True)
    evento: Mapped[str] = mapped_column(String)  # ex.: 'rascunho_gerado'
    ator: Mapped[str] = mapped_column(String, default="sistema")
    detalhe: Mapped[str | None] = mapped_column(Text, nullable=True)
    em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora)


def init_db() -> None:
    Base.metadata.create_all(engine)
