"""
Ingestão e de-identificação de imagens DICOM.

Fluxo: recebe um DICOM -> remove dados identificáveis do paciente (PHI) ->
converte o pixel data para PNG (com janelamento) para enviar ao MedGemma.

A de-identificação acontece ANTES de qualquer inferência. A imagem que chega
ao modelo não carrega nome, data de nascimento, etc. Como rodamos on-premise,
o pixel nem sai da clínica — mas removemos PHI mesmo assim (defesa em
profundidade e higiene de logs/auditoria).
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

import numpy as np
import pydicom
from PIL import Image
from pydicom.dataset import FileDataset

# Tags de identificação do paciente a serem removidas/anonimizadas.
# Lista mínima; em produção usar perfil de de-id da DICOM PS3.15.
TAGS_PHI = [
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "OtherPatientIDs",
    "ReferringPhysicianName",
    "InstitutionAddress",
]


@dataclass
class ExameDicom:
    """Resultado do processamento de um DICOM."""

    sop_instance_uid: str
    study_instance_uid: str
    modalidade: str
    incidencia: str | None
    imagem_png_b64: str  # imagem de-identificada, pronta para inferência


def _normalizar_pixels(ds: FileDataset) -> np.ndarray:
    """Converte pixel data DICOM em array 8-bit aplicando janelamento.

    Usa Window Center/Width quando presentes (padrão para o radiologista);
    caso contrário, faz min-max do range real.
    """
    pixels = ds.pixel_array.astype(np.float32)

    # Aplica rescale slope/intercept se existirem (ex.: para Hounsfield/raw).
    slope = float(getattr(ds, "RescaleSlope", 1) or 1)
    intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
    pixels = pixels * slope + intercept

    centro = getattr(ds, "WindowCenter", None)
    largura = getattr(ds, "WindowWidth", None)
    if centro is not None and largura is not None:
        # Podem vir como MultiValue; pega o primeiro.
        centro = float(centro[0] if hasattr(centro, "__iter__") else centro)
        largura = float(largura[0] if hasattr(largura, "__iter__") else largura)
        minimo = centro - largura / 2
        maximo = centro + largura / 2
    else:
        minimo, maximo = float(pixels.min()), float(pixels.max())

    if maximo <= minimo:
        maximo = minimo + 1
    pixels = np.clip((pixels - minimo) / (maximo - minimo), 0, 1)

    # MONOCHROME1 tem escala invertida (branco = baixo).
    if getattr(ds, "PhotometricInterpretation", "") == "MONOCHROME1":
        pixels = 1.0 - pixels

    return (pixels * 255).astype(np.uint8)


def de_identificar(ds: FileDataset) -> None:
    """Remove PHI in-place do dataset DICOM."""
    for tag in TAGS_PHI:
        if tag in ds:
            setattr(ds, tag, "ANONIMIZADO")


def processar_dicom(conteudo: bytes) -> ExameDicom:
    """Processa um arquivo DICOM bruto e retorna o exame pronto p/ inferência."""
    ds = pydicom.dcmread(io.BytesIO(conteudo))

    sop_uid = str(getattr(ds, "SOPInstanceUID", ""))
    study_uid = str(getattr(ds, "StudyInstanceUID", ""))
    modalidade = str(getattr(ds, "Modality", "DX"))
    incidencia = getattr(ds, "ViewPosition", None)

    de_identificar(ds)

    arr = _normalizar_pixels(ds)
    img = Image.fromarray(arr).convert("L")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    png_b64 = base64.b64encode(buffer.getvalue()).decode("ascii")

    return ExameDicom(
        sop_instance_uid=sop_uid,
        study_instance_uid=study_uid,
        modalidade=modalidade,
        incidencia=str(incidencia) if incidencia else None,
        imagem_png_b64=png_b64,
    )
