"""Teste de integração do fluxo completo (mock, SQLite in-process).

Prova: upload DICOM -> rascunho IA -> médico edita adicionando pneumotórax
acentuado -> criticidade recalculada -> assinatura. Não precisa de GPU nem
Postgres. Roda com: python teste_fluxo.py
"""
import io
import os

# DB SQLite e modo mock (sem MEDGEMMA_BASE_URL) ANTES de importar o app.
os.environ["DATABASE_URL"] = "sqlite:///./teste_fluxo.db"
os.environ.pop("MEDGEMMA_BASE_URL", None)

import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid
from fastapi.testclient import TestClient


def dicom_sintetico() -> bytes:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.PatientName = "TESTE^PACIENTE"
    ds.PatientID = "12345"
    ds.Modality = "DX"
    ds.ViewPosition = "PA"
    ds.StudyInstanceUID = generate_uid()
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.Rows = ds.Columns = 32
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = (np.arange(32 * 32) % 256).astype(np.uint8).tobytes()
    buf = io.BytesIO()
    ds.save_as(buf, write_like_original=False)
    return buf.getvalue()


def main():
    if os.path.exists("teste_fluxo.db"):
        os.remove("teste_fluxo.db")
    from app.db import init_db
    from app.main import app

    init_db()  # cria as tabelas (startup não dispara fora do context manager)
    cli = TestClient(app)

    assert cli.get("/saude").json()["modo_ia"] == "mock"

    # 1) Upload do DICOM -> rascunho da IA
    r = cli.post("/exames", files={"arquivo": ("ex.dcm", dicom_sintetico(), "application/dicom")})
    assert r.status_code == 200, r.text
    exame_id = r.json()["id"]
    print("1. Rascunho IA gerado. crítico inicial:", r.json()["critico"])

    # 2) Médico edita: zera o derrame do mock e adiciona PNEUMOTÓRAX ACENTUADO
    laudo = cli.get(f"/exames/{exame_id}").json()["laudo_ia"]
    laudo["achados"]["derrame_pleural"]["presenca"] = "ausente"
    laudo["achados"]["pneumotorax"] = {
        "presenca": "presente",
        "lateralidade": "esquerda",
        "gravidade": "acentuado",
        "descricao": "Pneumotórax à esquerda.",
        "confianca": 0.9,
    }
    laudo["impressao"] = "Pneumotórax acentuado à esquerda. Comunicação imediata."
    r = cli.put(f"/exames/{exame_id}/laudo?medico=Dr.%20Teste", json=laudo)
    assert r.status_code == 200, r.text
    print("2. Após edição, achados_criticos:", r.json()["achados_criticos"])
    assert "Pneumotórax" in r.json()["achados_criticos"], "deveria ter virado crítico"

    # confirma que a worklist marcou como crítico
    det = cli.get(f"/exames/{exame_id}").json()
    assert det["critico"] is True
    print("3. Worklist marcou exame como crítico:", det["critico"])

    # 3) Assinatura
    cli.post(f"/exames/{exame_id}/assinar?medico=Dr.%20Teste")
    final = cli.get(f"/exames/{exame_id}").json()
    assert final["laudo_final"]["validado_por_medico"] is True
    assert final["status"] == "assinado"
    print("4. Laudo assinado por:", final["medico_responsavel"], "| status:", final["status"])

    print("5. Métricas:", cli.get("/metricas").json())
    print("\nTODOS OS PASSOS OK")


if __name__ == "__main__":
    main()
