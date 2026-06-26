"""Teste do poller de worklist do Orthanc (sem rede).

Usa um OrthancClient FALSO que devolve uma instância DICOM sintética. Chama
`_poll_uma_vez` direto (sem loop/sleep) e confirma:
 - o exame é ingerido automaticamente e processado (modo síncrono);
 - o `ultimo_seq` avança;
 - reprocessar a mesma instância NÃO duplica (dedup por SOPInstanceUID).

Roda com: python teste_orthanc.py
"""
import io
import os

os.environ["DATABASE_URL"] = "sqlite:///./teste_orthanc.db"
os.environ.pop("MEDGEMMA_BASE_URL", None)
os.environ["INFERENCIA_SINCRONA"] = "1"

import asyncio

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid
from sqlalchemy import func, select


def dicom_sintetico() -> bytes:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.Modality = "DX"
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


class OrthancFalso:
    """Faz o papel do Orthanc: uma instância nova 'inst1' no Seq 1."""

    def __init__(self, dicom: bytes) -> None:
        self.dicom = dicom

    async def get_changes(self, desde: int, limite: int = 50) -> dict:
        return {
            "Changes": [
                {"Seq": 1, "ChangeType": "NewInstance", "ResourceType": "Instance", "ID": "inst1"}
            ],
            "Last": 1,
            "Done": True,
        }

    async def get_instance_file(self, instance_id: str) -> bytes:
        return self.dicom


def main():
    if os.path.exists("teste_orthanc.db"):
        os.remove("teste_orthanc.db")
    from app.db import EstadoOrthanc, Exame, SessionLocal, StatusExame, init_db
    from app.main import _poll_uma_vez

    init_db()
    client = OrthancFalso(dicom_sintetico())

    db = SessionLocal()
    try:
        # 1) Primeira rodada: ingere 1 exame novo.
        novos = asyncio.run(_poll_uma_vez(client, db))
        assert novos == 1, novos
        total = db.scalar(select(func.count()).select_from(Exame))
        assert total == 1
        e = db.scalars(select(Exame)).first()
        assert e.status == StatusExame.rascunho_pronto.value and e.laudo_ia
        print("1. Poller ingeriu e processou 1 exame automaticamente (status:", e.status, ")")

        # 2) ultimo_seq avançou para 1.
        estado = db.get(EstadoOrthanc, 1)
        assert estado.ultimo_seq == 1, estado.ultimo_seq
        print("2. ultimo_seq avançou para", estado.ultimo_seq)

        # 3) Segunda rodada com a MESMA instância: dedup, nenhum exame novo.
        novos2 = asyncio.run(_poll_uma_vez(client, db))
        assert novos2 == 0, novos2
        total2 = db.scalar(select(func.count()).select_from(Exame))
        assert total2 == 1, "dedup falhou — exame duplicado"
        print("3. Reprocessar a mesma instância não duplicou (dedup OK)")
    finally:
        db.close()

    print("\nTODOS OS PASSOS OK")


if __name__ == "__main__":
    main()
