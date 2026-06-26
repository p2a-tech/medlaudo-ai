"""Teste do harness de avaliação (modo mock).

Monta um mini-dataset sintético + manifesto e roda a avaliação. O mock sempre
retorna derrame moderado presente e cardiomegalia indeterminada, então com uma
verdade-base que inclui PNEUMOTÓRAX o harness deve acusar um achado crítico
PERDIDO — exatamente o erro que queremos flagrar.

Roda com: python teste_avaliacao.py
"""
import io
import json
import os
import tempfile

os.environ.pop("MEDGEMMA_BASE_URL", None)  # garante modo mock

import asyncio

import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid


def dicom_sintetico(path: str) -> None:
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
    ds.save_as(path, write_like_original=False)


def main():
    from app.avaliacao.executar import avaliar

    with tempfile.TemporaryDirectory() as d:
        dicom_sintetico(os.path.join(d, "caso1.dcm"))
        dicom_sintetico(os.path.join(d, "caso2.dcm"))
        manifesto = [
            # caso1: tem derrame (o mock acerta) e pneumotórax (o mock PERDE)
            {"imagem": "caso1.dcm", "achados": {"derrame_pleural": True, "pneumotorax": True}},
            # caso2: tórax normal (o mock erra ao marcar derrame -> falso positivo)
            {"imagem": "caso2.dcm", "achados": {}},
        ]
        manifesto_path = os.path.join(d, "manifesto.json")
        with open(manifesto_path, "w", encoding="utf-8") as fh:
            json.dump(manifesto, fh)

        saida = os.path.join(d, "resultado.json")
        res = asyncio.run(avaliar(manifesto_path, saida))

        print("\n--- asserções ---")
        # derrame: caso1 TP, caso2 FP -> sensibilidade 1.0, 1 falso positivo
        derrame = res["por_campo"]["derrame_pleural"]
        assert derrame["tp"] == 1 and derrame["fp"] == 1, derrame
        assert res["por_campo"]["derrame_pleural"]["fn"] == 0
        print("derrame_pleural:", derrame)

        # pneumotórax: caso1 era positivo e o mock não detectou -> 1 perdido
        pneumo = res["por_campo"]["pneumotorax"]
        assert pneumo["fn"] == 1, pneumo
        print("pneumotorax:", pneumo)

        # resumo de críticos deve acusar 1 perdido
        assert res["criticos"]["perdidos"] == 1, res["criticos"]
        print("criticos:", res["criticos"])

        assert os.path.exists(saida), "JSON de resultado não foi salvo"
        print("\nTODOS OS PASSOS OK")


if __name__ == "__main__":
    main()
