"""Teste do worker assíncrono de inferência e da autenticação.

- Modo ASSÍNCRONO (default): o upload retorna na hora com status 'aguardando'
  e o worker em processo gera o rascunho em seguida. Usamos o TestClient como
  context manager para disparar o startup (que sobe a fila + worker).
- Autenticação: rota protegida sem token => 401/403; com token => OK.

Roda com: python teste_async_auth.py
"""
import io
import os
import time

os.environ["DATABASE_URL"] = "sqlite:///./teste_async.db"
os.environ.pop("MEDGEMMA_BASE_URL", None)
os.environ["INFERENCIA_SINCRONA"] = "0"  # força o caminho assíncrono (fila+worker)

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid
from fastapi.testclient import TestClient


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


def main():
    if os.path.exists("teste_async.db"):
        os.remove("teste_async.db")
    from app.main import app

    # Context manager dispara o startup => sobe fila + worker no loop do app.
    with TestClient(app) as cli:
        assert cli.get("/saude").json()["inferencia"] == "assincrona"

        # 1) Upload retorna IMEDIATAMENTE como 'aguardando' (não bloqueia).
        r = cli.post(
            "/exames", files={"arquivo": ("ex.dcm", dicom_sintetico(), "application/dicom")}
        ).json()
        exame_id = r["id"]
        assert r["status"] == "aguardando", r
        assert r["laudo"] is None
        print("1. Upload retornou na hora com status 'aguardando'")

        # 2) O worker processa em background -> status vira 'rascunho_pronto'.
        pronto = False
        for _ in range(50):  # até ~5s
            det = cli.get(f"/exames/{exame_id}").json()
            if det["status"] == "rascunho_pronto" and det["laudo_ia"]:
                pronto = True
                break
            time.sleep(0.1)
        assert pronto, "worker não processou o exame a tempo"
        print("2. Worker processou em background -> 'rascunho_pronto' com laudo")

        # 3) Auth: rota protegida sem token deve barrar.
        sem = cli.post(f"/exames/{exame_id}/assinar")
        assert sem.status_code in (401, 403), sem.status_code
        print("3. Assinar sem token barrado:", sem.status_code)

        # 4) Com login válido, assina normalmente.
        import uuid as _uuid
        from app.auth.seguranca import hash_senha
        from app.db import Medico, SessionLocal
        _db = SessionLocal()
        _db.add(Medico(id=str(_uuid.uuid4()), nome="Dra. Ana", email="ana@c.com",
                       crm="9-RS", senha_hash=hash_senha("senha")))
        _db.commit(); _db.close()
        token = cli.post("/auth/login", json={"email": "ana@c.com", "senha": "senha"}).json()["token"]
        ok = cli.post(f"/exames/{exame_id}/assinar", headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200, ok.text
        final = cli.get(f"/exames/{exame_id}").json()
        assert final["medico_responsavel"] == "Dra. Ana"
        assert final["laudo_final"]["assinado_por_crm"] == "9-RS"
        print("4. Assinado com token por:", final["medico_responsavel"], "CRM no laudo OK")

        # 5) Senha errada é rejeitada.
        bad = cli.post("/auth/login", json={"email": "ana@c.com", "senha": "errada"})
        assert bad.status_code == 401
        print("5. Login com senha errada rejeitado:", bad.status_code)

    print("\nTODOS OS PASSOS OK")


if __name__ == "__main__":
    main()
