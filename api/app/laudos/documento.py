"""
Geração de documentos do laudo: PDF (legível) e DICOM (para o PACS).

Duas saídas a partir do mesmo laudo estruturado:

1. PDF — documento clínico legível, com identificação, achados, impressão,
   responsável e avisos. É o que a clínica entrega/imprime.
2. DICOM Encapsulated PDF — embrulha o PDF num objeto DICOM (SOP Class
   "Encapsulated PDF Storage") para devolver ao PACS, agrupado no MESMO estudo
   da imagem original (mesmo StudyInstanceUID). É a forma mais interoperável
   de mandar laudo ao PACS — praticamente todo PACS aceita.

NOTA DE PRODUÇÃO sobre identificação do paciente: como de-identificamos a
imagem antes da inferência, o laudo não carrega o paciente real. Em produção,
o PatientID/PatientName REAIS devem vir de um mapa seguro mantido fora do
caminho do modelo (ex.: a partir do StudyInstanceUID original no PACS) e
preenchidos aqui, para o laudo filar no estudo correto. Os parâmetros
`paciente_*` existem justamente para isso.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ENCAPSULATED_PDF_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.104.1"

ROTULOS = {
    "consolidacao": "Consolidação",
    "opacidade_intersticial": "Opacidade intersticial",
    "nodulo_ou_massa": "Nódulo ou massa",
    "atelectasia": "Atelectasia",
    "derrame_pleural": "Derrame pleural",
    "pneumotorax": "Pneumotórax",
    "cardiomegalia": "Cardiomegalia",
    "alargamento_mediastinal": "Alargamento mediastinal",
    "congestao_pulmonar": "Congestão pulmonar",
    "fratura": "Fratura",
    "dispositivos": "Dispositivos",
}


def _achados_legiveis(achados: dict) -> list[str]:
    """Transforma os achados estruturados em frases para o laudo."""
    linhas: list[str] = []
    for campo, rotulo in ROTULOS.items():
        a = achados.get(campo) or {}
        if a.get("presenca", "ausente") == "ausente":
            continue
        partes = [rotulo]
        if a.get("presenca") == "indeterminado":
            partes.append("(indeterminado)")
        if a.get("lateralidade") and a["lateralidade"] != "nao_aplicavel":
            partes.append(f"à {a['lateralidade']}")
        if a.get("gravidade") and a["gravidade"] != "normal":
            partes.append(f"— {a['gravidade']}")
        frase = " ".join(partes)
        if a.get("descricao"):
            frase += f". {a['descricao']}"
        linhas.append(frase)
    return linhas


def gerar_pdf(
    laudo: dict,
    *,
    modalidade: str = "DX",
    incidencia: str | None = None,
    medico: str | None = None,
    paciente_nome: str = "Paciente não identificado",
    clinica: str = "Clínica de Imagem",
) -> bytes:
    """Renderiza o laudo como PDF (bytes)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="Laudo Radiológico",
    )
    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle(
        "titulo", parent=estilos["Title"], fontSize=15, spaceAfter=2
    )
    h3 = ParagraphStyle(
        "h3", parent=estilos["Heading4"], textColor=colors.HexColor("#334155"),
        spaceBefore=10, spaceAfter=2,
    )
    corpo = estilos["BodyText"]
    pequeno = ParagraphStyle("pequeno", parent=corpo, fontSize=8,
                             textColor=colors.HexColor("#64748b"))

    validado = bool(laudo.get("validado_por_medico"))
    el: list = []

    el.append(Paragraph(clinica, pequeno))
    el.append(Paragraph("LAUDO RADIOLÓGICO — Raio-X de Tórax", titulo))
    el.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cbd5e1")))

    if not validado:
        el.append(Spacer(1, 4))
        el.append(
            Paragraph(
                "<b>RASCUNHO — NÃO VALIDADO POR MÉDICO</b>",
                ParagraphStyle("aviso", parent=corpo,
                               textColor=colors.HexColor("#b45309")),
            )
        )

    # Identificação
    agora = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    meta = [
        ["Paciente:", paciente_nome, "Exame:", f"{modalidade} {incidencia or ''}".strip()],
        ["Data do laudo:", agora, "Médico:", medico or "—"],
    ]
    tabela = Table(meta, colWidths=[28 * mm, 60 * mm, 22 * mm, 50 * mm])
    tabela.setStyle(
        TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#64748b")),
            ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#64748b")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ])
    )
    el.append(Spacer(1, 6))
    el.append(tabela)

    # Achados críticos em destaque
    criticos = laudo.get("achados_criticos") or []
    if criticos:
        el.append(Spacer(1, 6))
        el.append(
            Paragraph(
                "⚠ ACHADO(S) CRÍTICO(S): " + ", ".join(criticos),
                ParagraphStyle("crit", parent=corpo, textColor=colors.HexColor("#b91c1c"),
                               backColor=colors.HexColor("#fef2f2"), borderPadding=4),
            )
        )

    # Qualidade técnica
    qt = laudo.get("qualidade_tecnica") or {}
    el.append(Paragraph("Qualidade técnica", h3))
    qt_txt = f"Incidência {qt.get('incidencia') or '—'}; " + (
        "adequada" if qt.get("adequada", True) else "inadequada"
    )
    if qt.get("observacoes"):
        qt_txt += f". {qt['observacoes']}"
    el.append(Paragraph(qt_txt, corpo))

    # Achados
    el.append(Paragraph("Achados", h3))
    linhas = _achados_legiveis(laudo.get("achados") or {})
    if linhas:
        for linha in linhas:
            el.append(Paragraph(f"• {linha}", corpo))
    else:
        el.append(Paragraph("Sem achados relevantes.", corpo))

    # Impressão
    el.append(Paragraph("Impressão diagnóstica", h3))
    el.append(Paragraph(laudo.get("impressao") or "—", corpo))

    # Rodapé / assinatura
    el.append(Spacer(1, 16))
    el.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))
    if validado:
        el.append(Paragraph(f"Assinado eletronicamente por <b>{medico or '—'}</b>.", pequeno))
    el.append(
        Paragraph(
            "Documento elaborado com auxílio de inteligência artificial (MedGemma) "
            "e revisado por médico responsável. A responsabilidade diagnóstica é "
            "do profissional signatário.",
            pequeno,
        )
    )

    doc.build(el)
    return buf.getvalue()


def gerar_dicom_pdf(
    pdf_bytes: bytes,
    *,
    study_instance_uid: str,
    paciente_id: str = "ANONIMIZADO",
    paciente_nome: str = "ANONIMIZADO",
    titulo: str = "Laudo Radiologico - Torax",
) -> bytes:
    """Embrulha o PDF num objeto DICOM Encapsulated PDF para enviar ao PACS.

    Reusa o `study_instance_uid` da imagem original para o laudo cair no mesmo
    estudo. Gera novos UIDs de série e instância.
    """
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = ENCAPSULATED_PDF_SOP_CLASS
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = ENCAPSULATED_PDF_SOP_CLASS
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study_instance_uid
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "DOC"
    ds.PatientID = paciente_id
    ds.PatientName = paciente_nome
    ds.SeriesNumber = "999"
    ds.InstanceNumber = "1"
    ds.DocumentTitle = titulo
    ds.ConceptNameCodeSequence = []
    ds.MIMETypeOfEncapsulatedDocument = "application/pdf"
    ds.BurnedInAnnotation = "YES"

    # EncapsulatedDocument deve ter tamanho par.
    if len(pdf_bytes) % 2:
        pdf_bytes += b"\x00"
    ds.EncapsulatedDocument = pdf_bytes

    out = io.BytesIO()
    ds.save_as(out, write_like_original=False)
    return out.getvalue()
