"""
MedLaudo-AI — API do assistente de laudo de raio-X de tórax.

Fluxo coberto por estas rotas:
  POST /exames            -> recebe DICOM, de-identifica, gera rascunho (IA)
  GET  /exames            -> worklist (críticos primeiro)
  GET  /exames/{id}       -> detalhe + rascunho
  GET  /exames/{id}/imagem-> PNG de-identificado para o viewer
  PUT  /exames/{id}/laudo -> médico edita o laudo
  POST /exames/{id}/assinar -> médico assina (laudo final)
  POST /exames/{id}/rejeitar-> médico descarta o rascunho
  GET  /metricas          -> indicadores de ROI (aceitação, edição, tempo)
"""

from __future__ import annotations

import asyncio
import base64
import os
import uuid

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auditoria.registro import registrar
from .auth.seguranca import conferir_senha, criar_token, get_medico_atual
from .db import Exame, Medico, SessionLocal, StatusExame, init_db
from .dicom.processamento import processar_dicom
from .inference.client import MedGemmaClient
from .inference.schema import Laudo, extrair_criticos
from .laudos.documento import gerar_dicom_pdf, gerar_pdf
from .laudos.pacs import enviar_ao_pacs, envio_automatico_ligado

app = FastAPI(title="MedLaudo-AI", version="0.1.0")

# Em produção on-prem, restringir ao host da clínica.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

cliente_ia = MedGemmaClient()

# Inferência: por padrão assíncrona (fila + worker em processo). Em testes,
# INFERENCIA_SINCRONA=1 roda inline, deixando o resultado determinístico.
INFERENCIA_SINCRONA = os.getenv("INFERENCIA_SINCRONA", "0") in ("1", "true", "True")

# Fila de inferência (preenchida no startup quando assíncrona).
_fila: asyncio.Queue[str] | None = None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def _processar_inferencia(exame_id: str) -> None:
    """Roda a IA sobre um exame e grava o rascunho. Usa sessão própria —
    é chamada tanto inline (modo síncrono) quanto pelo worker (assíncrono)."""
    db = SessionLocal()
    try:
        e = db.get(Exame, exame_id)
        if not e:
            return
        imagem = _IMAGENS.get(exame_id)
        if not imagem:
            return
        laudo = await cliente_ia.gerar_laudo(imagem)
        e.laudo_ia = laudo.model_dump()
        e.status = StatusExame.rascunho_pronto.value
        e.critico = len(laudo.achados_criticos) > 0
        db.commit()
        registrar(
            db,
            exame_id,
            "rascunho_gerado",
            ator="ia",
            detalhe=", ".join(laudo.achados_criticos) or "sem achados críticos",
        )
    finally:
        db.close()


async def _worker() -> None:
    """Consome a fila de inferência indefinidamente."""
    assert _fila is not None
    while True:
        exame_id = await _fila.get()
        try:
            await _processar_inferencia(exame_id)
        except Exception as exc:  # noqa: BLE001 — worker não pode morrer
            print(f"[worker] falha ao processar {exame_id}: {exc}")
        finally:
            _fila.task_done()


@app.on_event("startup")
async def _startup() -> None:
    init_db()
    global _fila
    if not INFERENCIA_SINCRONA:
        _fila = asyncio.Queue()
        asyncio.create_task(_worker())


@app.get("/saude")
def saude() -> dict:
    return {
        "ok": True,
        "modo_ia": "mock" if cliente_ia.modo_mock else "medgemma",
        "inferencia": "sincrona" if INFERENCIA_SINCRONA else "assincrona",
    }


# ---- autenticação ---------------------------------------------------------

class LoginEntrada(BaseModel):
    email: str
    senha: str


@app.post("/auth/login")
def login(dados: LoginEntrada, db: Session = Depends(get_db)) -> dict:
    medico = db.scalar(select(Medico).where(Medico.email == dados.email.lower()))
    if not medico or not medico.ativo or not conferir_senha(dados.senha, medico.senha_hash):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    return {
        "token": criar_token(medico),
        "medico": {"id": medico.id, "nome": medico.nome, "crm": medico.crm},
    }


@app.post("/exames")
async def criar_exame(arquivo: UploadFile, db: Session = Depends(get_db)) -> dict:
    """Recebe um DICOM, processa e gera o rascunho de laudo com a IA."""
    conteudo = await arquivo.read()
    try:
        exame_dcm = processar_dicom(conteudo)
    except Exception as exc:  # noqa: BLE001 — superfície de entrada hostil
        raise HTTPException(status_code=400, detail=f"DICOM inválido: {exc}")

    exame_id = str(uuid.uuid4())
    # Guarda a imagem de-identificada para o viewer (no MVP, no próprio registro
    # via base64; em produção, no Orthanc/objeto). Mantido simples aqui.
    registro = Exame(
        id=exame_id,
        study_instance_uid=exame_dcm.study_instance_uid,
        sop_instance_uid=exame_dcm.sop_instance_uid,
        modalidade=exame_dcm.modalidade,
        incidencia=exame_dcm.incidencia,
        status=StatusExame.aguardando.value,
    )
    db.add(registro)
    # Guarda a imagem para o viewer/inferência (no MVP, em memória; em produção,
    # no Orthanc/objeto). Disponível antes de enfileirar.
    _IMAGENS[exame_id] = exame_dcm.imagem_png_b64
    db.commit()
    registrar(db, exame_id, "dicom_recebido", detalhe=exame_dcm.modalidade)

    if INFERENCIA_SINCRONA:
        # Modo determinístico (testes): processa inline e devolve o rascunho.
        await _processar_inferencia(exame_id)
        db.refresh(registro)
        return {
            "id": exame_id,
            "status": registro.status,
            "critico": registro.critico,
            "laudo": registro.laudo_ia,
        }

    # Modo assíncrono (produção): enfileira e responde já, sem bloquear o upload.
    assert _fila is not None
    await _fila.put(exame_id)
    return {"id": exame_id, "status": registro.status, "critico": False, "laudo": None}


@app.get("/exames")
def listar_exames(db: Session = Depends(get_db)) -> list[dict]:
    """Worklist: críticos primeiro, depois mais recentes."""
    stmt = (
        select(Exame)
        .order_by(Exame.critico.desc(), Exame.criado_em.desc())
        .limit(200)
    )
    exames = db.execute(stmt).scalars().all()
    return [
        {
            "id": e.id,
            "status": e.status,
            "critico": e.critico,
            "modalidade": e.modalidade,
            "incidencia": e.incidencia,
            "criado_em": e.criado_em.isoformat(),
        }
        for e in exames
    ]


@app.get("/exames/{exame_id}")
def obter_exame(exame_id: str, db: Session = Depends(get_db)) -> dict:
    e = db.get(Exame, exame_id)
    if not e:
        raise HTTPException(status_code=404, detail="Exame não encontrado")
    return {
        "id": e.id,
        "status": e.status,
        "critico": e.critico,
        "modalidade": e.modalidade,
        "incidencia": e.incidencia,
        "laudo_ia": e.laudo_ia,
        "laudo_final": e.laudo_final,
        "medico_responsavel": e.medico_responsavel,
    }


@app.get("/exames/{exame_id}/imagem")
def obter_imagem(exame_id: str) -> Response:
    """Retorna o PNG de-identificado para o viewer."""
    b64 = _IMAGENS.get(exame_id)
    if not b64:
        raise HTTPException(status_code=404, detail="Imagem não disponível")
    return Response(content=base64.b64decode(b64), media_type="image/png")


@app.put("/exames/{exame_id}/laudo")
def editar_laudo(
    exame_id: str,
    laudo: Laudo,
    db: Session = Depends(get_db),
    medico: Medico = Depends(get_medico_atual),
) -> dict:
    """Salva edições do médico autenticado (sem assinar).

    Recalcula a criticidade a partir dos achados editados — se o médico
    adicionar/remover um achado crítico, a prioridade da worklist acompanha.
    A regra continua determinística e em código.
    """
    e = db.get(Exame, exame_id)
    if not e:
        raise HTTPException(status_code=404, detail="Exame não encontrado")
    laudo.achados_criticos = extrair_criticos(laudo.achados)
    e.laudo_final = laudo.model_dump()
    e.critico = len(laudo.achados_criticos) > 0
    e.medico_responsavel = medico.nome
    e.status = StatusExame.em_revisao.value
    db.commit()
    registrar(db, exame_id, "laudo_editado", ator=medico.nome)
    return {"ok": True, "achados_criticos": laudo.achados_criticos}


@app.post("/exames/{exame_id}/assinar")
def assinar_laudo(
    exame_id: str,
    db: Session = Depends(get_db),
    medico: Medico = Depends(get_medico_atual),
) -> dict:
    """Assina o laudo final com a identidade do médico autenticado."""
    e = db.get(Exame, exame_id)
    if not e:
        raise HTTPException(status_code=404, detail="Exame não encontrado")
    # Se o médico não editou, parte do rascunho da IA como base.
    # Cria um NOVO dict: reatribuir a mesma referência não marca a coluna JSON
    # como suja no SQLAlchemy (mutação in-place não é detectada).
    final = dict(e.laudo_final or e.laudo_ia or {})
    final["validado_por_medico"] = True
    final["assinado_por_crm"] = medico.crm or ""
    e.laudo_final = final
    e.medico_responsavel = medico.nome
    e.status = StatusExame.assinado.value
    db.commit()
    registrar(db, exame_id, "laudo_assinado", ator=medico.nome)

    # Envio automático ao PACS (best-effort: não falha a assinatura).
    envio = None
    if envio_automatico_ligado():
        resultado = enviar_ao_pacs(_dicom_do_laudo(e))
        registrar(
            db,
            exame_id,
            "pacs_envio_ok" if resultado.ok else "pacs_envio_falha",
            ator="sistema",
            detalhe=resultado.detalhe,
        )
        envio = {"ok": resultado.ok, "detalhe": resultado.detalhe}

    return {"ok": True, "pacs": envio}


@app.post("/exames/{exame_id}/enviar-pacs")
def enviar_pacs(
    exame_id: str,
    db: Session = Depends(get_db),
    medico: Medico = Depends(get_medico_atual),
) -> dict:
    """Reenvia manualmente o laudo assinado ao PACS (ex.: após PACS voltar)."""
    e = db.get(Exame, exame_id)
    if not e:
        raise HTTPException(status_code=404, detail="Exame não encontrado")
    resultado = enviar_ao_pacs(_dicom_do_laudo(e))
    registrar(
        db,
        exame_id,
        "pacs_envio_ok" if resultado.ok else "pacs_envio_falha",
        ator="sistema",
        detalhe=resultado.detalhe,
    )
    if not resultado.ok:
        raise HTTPException(status_code=502, detail=resultado.detalhe)
    return {"ok": True, "detalhe": resultado.detalhe}


@app.post("/exames/{exame_id}/rejeitar")
def rejeitar(
    exame_id: str,
    db: Session = Depends(get_db),
    medico: Medico = Depends(get_medico_atual),
) -> dict:
    e = db.get(Exame, exame_id)
    if not e:
        raise HTTPException(status_code=404, detail="Exame não encontrado")
    e.status = StatusExame.rejeitado.value
    db.commit()
    registrar(db, exame_id, "rascunho_rejeitado", ator=medico.nome)
    return {"ok": True}


def _laudo_atual(e: Exame) -> dict:
    """Laudo a ser documentado: o final (assinado/editado) ou o rascunho da IA."""
    laudo = e.laudo_final or e.laudo_ia
    if not laudo:
        raise HTTPException(status_code=409, detail="Exame ainda sem laudo")
    return laudo


def _dicom_do_laudo(e: Exame) -> bytes:
    """Gera o DICOM Encapsulated PDF do laudo assinado. Exige assinatura."""
    if not (e.laudo_final and e.laudo_final.get("validado_por_medico")):
        raise HTTPException(
            status_code=409, detail="Laudo precisa estar assinado para gerar DICOM"
        )
    pdf = gerar_pdf(
        e.laudo_final,
        modalidade=e.modalidade,
        incidencia=e.incidencia,
        medico=e.medico_responsavel,
    )
    return gerar_dicom_pdf(pdf, study_instance_uid=e.study_instance_uid)


@app.get("/exames/{exame_id}/laudo.pdf")
def baixar_pdf(exame_id: str, db: Session = Depends(get_db)) -> Response:
    """PDF legível do laudo (com aviso de rascunho se não assinado)."""
    e = db.get(Exame, exame_id)
    if not e:
        raise HTTPException(status_code=404, detail="Exame não encontrado")
    pdf = gerar_pdf(
        _laudo_atual(e),
        modalidade=e.modalidade,
        incidencia=e.incidencia,
        medico=e.medico_responsavel,
    )
    registrar(db, exame_id, "pdf_gerado", ator=e.medico_responsavel or "sistema")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="laudo_{exame_id[:8]}.pdf"'
        },
    )


@app.get("/exames/{exame_id}/laudo.dcm")
def baixar_dicom(exame_id: str, db: Session = Depends(get_db)) -> Response:
    """Laudo como DICOM Encapsulated PDF, pronto para enviar ao PACS.

    Só liberado após assinatura — não devolvemos rascunho não validado ao PACS.
    """
    e = db.get(Exame, exame_id)
    if not e:
        raise HTTPException(status_code=404, detail="Exame não encontrado")
    dcm = _dicom_do_laudo(e)
    registrar(db, exame_id, "dicom_sr_gerado", ator=e.medico_responsavel or "sistema")
    return Response(
        content=dcm,
        media_type="application/dicom",
        headers={
            "Content-Disposition": f'attachment; filename="laudo_{exame_id[:8]}.dcm"'
        },
    )


@app.get("/metricas")
def metricas(db: Session = Depends(get_db)) -> dict:
    """Indicadores de ROI — o que vende a próxima clínica."""
    total = db.scalar(select(func.count()).select_from(Exame)) or 0
    assinados = (
        db.scalar(
            select(func.count())
            .select_from(Exame)
            .where(Exame.status == StatusExame.assinado.value)
        )
        or 0
    )
    rejeitados = (
        db.scalar(
            select(func.count())
            .select_from(Exame)
            .where(Exame.status == StatusExame.rejeitado.value)
        )
        or 0
    )
    criticos = (
        db.scalar(select(func.count()).select_from(Exame).where(Exame.critico))
        or 0
    )
    return {
        "total_exames": total,
        "assinados": assinados,
        "rejeitados": rejeitados,
        "criticos_detectados": criticos,
        "taxa_aproveitamento": round(assinados / total, 3) if total else 0.0,
    }


# Armazenamento simples de imagens para o MVP (em produção: Orthanc/objeto).
_IMAGENS: dict[str, str] = {}
