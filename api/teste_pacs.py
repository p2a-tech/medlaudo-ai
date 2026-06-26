"""Teste do envio ao PACS via C-STORE.

Sobe um SCP DICOM real in-process (pynetdicom), assina um exame com envio
automático ligado, e confirma que o PACS RECEBEU o laudo (Encapsulated PDF)
no estudo correto. Também testa o caminho de falha (PACS fora do ar).

Roda com: python teste_pacs.py
"""
import io
import os

os.environ["DATABASE_URL"] = "sqlite:///./teste_pacs.db"
os.environ.pop("MEDGEMMA_BASE_URL", None)
# Aponta o envio para o SCP local que vamos subir.
os.environ["PACS_ENVIO_AUTO"] = "1"
os.environ["PACS_HOST"] = "127.0.0.1"
os.environ["PACS_PORT"] = "11112"
os.environ["PACS_AE_TITLE"] = "TESTSCP"

import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid
from pynetdicom import AE, evt
from pynetdicom.sop_class import EncapsulatedPDFStorage
from fastapi.testclient import TestClient


def dicom_sintetico():
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
    if os.path.exists("teste_pacs.db"):
        os.remove("teste_pacs.db")

    recebidos = []

    def handle_store(event):
        ds = event.dataset
        ds.file_meta = event.file_meta
        recebidos.append(ds)
        return 0x0000

    # Sobe o SCP DICOM local (faz o papel do Orthanc).
    ae = AE(ae_title="TESTSCP")
    ae.add_supported_context(EncapsulatedPDFStorage)
    scp = ae.start_server(
        ("127.0.0.1", 11112), block=False, evt_handlers=[(evt.EVT_C_STORE, handle_store)]
    )

    try:
        from app.db import init_db
        from app.main import app

        init_db()
        cli = TestClient(app)

        dcm = dicom_sintetico()
        study_uid = str(pydicom.dcmread(io.BytesIO(dcm)).StudyInstanceUID)

        exame_id = cli.post(
            "/exames", files={"arquivo": ("ex.dcm", dcm, "application/dicom")}
        ).json()["id"]

        # Assina -> deve disparar C-STORE automático para o SCP.
        r = cli.post(f"/exames/{exame_id}/assinar?medico=Dr.%20Teste").json()
        print("1. Resposta da assinatura, bloco pacs:", r["pacs"])
        assert r["pacs"] and r["pacs"]["ok"], "envio automático deveria ter dado certo"

        assert len(recebidos) == 1, f"SCP deveria ter recebido 1 objeto, recebeu {len(recebidos)}"
        rec = recebidos[0]
        assert rec.SOPClassUID == "1.2.840.10008.5.1.4.1.1.104.1"
        assert str(rec.StudyInstanceUID) == study_uid, "laudo deve cair no mesmo estudo"
        assert bytes(rec.EncapsulatedDocument)[:5] == b"%PDF-"
        print(f"2. SCP recebeu Encapsulated PDF no estudo correto ({len(recebidos)} objeto)")

        # Reenvio manual também funciona.
        rr = cli.post(f"/exames/{exame_id}/enviar-pacs").json()
        assert rr["ok"]
        assert len(recebidos) == 2
        print("3. Reenvio manual OK, SCP agora com", len(recebidos), "objetos")
        # Caminho de falha: SCP desligado, assinar NÃO pode quebrar.
        # Reusa o mesmo app/cli; novo exame, agora com o SCP já parado.
        scp.shutdown()
        eid = cli.post(
            "/exames", files={"arquivo": ("ex.dcm", dicom_sintetico(), "application/dicom")}
        ).json()["id"]
        r2 = cli.post(f"/exames/{eid}/assinar?medico=Dr.%20Teste").json()
        assert r2["ok"] is True, "assinatura deve suceder mesmo com PACS fora"
        assert r2["pacs"]["ok"] is False, "envio deve reportar falha"
        print("4. PACS fora do ar: assinatura OK, envio reportou falha (best-effort)")
    finally:
        try:
            scp.shutdown()  # idempotente: já pode ter sido parado acima
        except Exception:
            pass

    print("\nTODOS OS PASSOS OK")


if __name__ == "__main__":
    main()
