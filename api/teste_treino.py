"""Teste do pipeline de fine-tuning (export do dataset).

Roda o fluxo até a assinatura (com correção do médico) e exporta o dataset SFT,
validando: imagem persistida em disco, formato de chat, e o alvo = laudo final
corrigido (sem flags de UI). Não treina (isso exige GPU).

Roda com: python teste_treino.py
"""
import io
import json
import os
import tempfile

# Isola dados/DB num diretório temporário ANTES de importar o app.
_TMP = tempfile.mkdtemp()
os.environ["DADOS_DIR"] = os.path.join(_TMP, "dados")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'treino.db')}"
os.environ.pop("MEDGEMMA_BASE_URL", None)
os.environ["INFERENCIA_SINCRONA"] = "1"

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
    from app.db import Medico, SessionLocal, init_db
    from app.auth.seguranca import hash_senha
    from app.main import app
    from app.treino.exportar_dataset import exportar
    import uuid

    init_db()
    db = SessionLocal()
    db.add(Medico(id=str(uuid.uuid4()), nome="Dr. Treino", email="tr@c.com",
                  crm="7-RS", senha_hash=hash_senha("s")))
    db.commit(); db.close()

    cli = TestClient(app)
    token = cli.post("/auth/login", json={"email": "tr@c.com", "senha": "s"}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}

    # Upload (síncrono) -> rascunho pronto. Confirma imagem em disco.
    exame_id = cli.post(
        "/exames", files={"arquivo": ("ex.dcm", dicom_sintetico(), "application/dicom")}
    ).json()["id"]
    assert cli.get(f"/exames/{exame_id}/imagem").status_code == 200
    print("1. Imagem de-identificada persistida em disco (endpoint 200)")

    # Médico corrige (adiciona pneumotórax) e assina.
    laudo = cli.get(f"/exames/{exame_id}").json()["laudo_ia"]
    laudo["achados"]["pneumotorax"] = {
        "presenca": "presente", "lateralidade": "direita",
        "gravidade": "acentuado", "descricao": "pneumotórax à direita", "confianca": 0.9,
    }
    cli.put(f"/exames/{exame_id}/laudo", json=laudo, headers=auth)
    cli.post(f"/exames/{exame_id}/assinar", headers=auth)
    print("2. Laudo corrigido e assinado")

    # Exporta o dataset SFT (apenas corrigidos).
    saida = os.path.join(_TMP, "treino.jsonl")
    n = exportar(saida, apenas_corrigidos=True)
    assert n == 1, f"esperado 1 exemplo, veio {n}"
    linha = json.loads(open(saida, encoding="utf-8").read().strip())
    print("3. Dataset exportado:", n, "exemplo(s)")

    # Valida o formato.
    papeis = [m["role"] for m in linha["messages"]]
    assert papeis == ["system", "user", "assistant"], papeis
    assert os.path.exists(linha["imagem"]), "imagem referenciada não existe"
    alvo = json.loads(linha["messages"][2]["content"])
    assert alvo["achados"]["pneumotorax"]["presenca"] == "presente"
    assert "validado_por_medico" not in alvo, "flags de UI não deviam ir ao alvo"
    print("4. Formato de chat OK; alvo = laudo corrigido; imagem referenciada existe")

    print("\nTODOS OS PASSOS OK")


if __name__ == "__main__":
    main()
