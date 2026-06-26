"""
Envio do laudo ao PACS via DICOM C-STORE (pynetdicom).

Ao assinar, o laudo (DICOM Encapsulated PDF) é empurrado de volta ao PACS,
agrupado no mesmo estudo da imagem. Sem isso, o radiologista teria que baixar
e reenviar manualmente.

Design defensivo: o envio é *best-effort*. Se o PACS estiver fora do ar, a
ASSINATURA NÃO FALHA — registramos a falha na auditoria e deixamos para reenvio
manual (endpoint dedicado). O documento clínico já está assinado e válido no
nosso banco independentemente do PACS.

Configuração por ambiente:
  PACS_ENVIO_AUTO  -> "1" para enviar automaticamente ao assinar (default: off)
  PACS_HOST        -> host do PACS (default: orthanc)
  PACS_PORT        -> porta DICOM (default: 4242)
  PACS_AE_TITLE    -> AE title do PACS (default: ORTHANC)
  PACS_CALLING_AE  -> nosso AE title (default: MEDLAUDO)
"""

from __future__ import annotations

import io
import os

import pydicom
from pynetdicom import AE
from pynetdicom.sop_class import EncapsulatedPDFStorage


class ResultadoEnvio:
    def __init__(self, ok: bool, detalhe: str) -> None:
        self.ok = ok
        self.detalhe = detalhe


def envio_automatico_ligado() -> bool:
    return os.getenv("PACS_ENVIO_AUTO", "0") in ("1", "true", "True")


def enviar_ao_pacs(dcm_bytes: bytes) -> ResultadoEnvio:
    """Faz C-STORE do objeto DICOM no PACS configurado.

    Não levanta exceção: sempre retorna um ResultadoEnvio (o chamador decide o
    que fazer). Timeouts curtos para não travar a assinatura.
    """
    host = os.getenv("PACS_HOST", "orthanc")
    port = int(os.getenv("PACS_PORT", "4242"))
    ae_title = os.getenv("PACS_AE_TITLE", "ORTHANC")
    calling = os.getenv("PACS_CALLING_AE", "MEDLAUDO")

    try:
        ds = pydicom.dcmread(io.BytesIO(dcm_bytes))
    except Exception as exc:  # noqa: BLE001
        return ResultadoEnvio(False, f"DICOM inválido: {exc}")

    ae = AE(ae_title=calling)
    ae.add_requested_context(EncapsulatedPDFStorage)
    # Timeouts curtos: assinar não pode ficar pendurado por causa do PACS.
    ae.acse_timeout = 10
    ae.dimse_timeout = 10
    ae.connection_timeout = 5

    try:
        assoc = ae.associate(host, port, ae_title=ae_title)
    except Exception as exc:  # noqa: BLE001
        return ResultadoEnvio(False, f"Falha ao conectar em {host}:{port}: {exc}")

    if not assoc.is_established:
        return ResultadoEnvio(False, f"Associação recusada por {host}:{port}")

    try:
        status = assoc.send_c_store(ds)
    except Exception as exc:  # noqa: BLE001
        return ResultadoEnvio(False, f"Erro no C-STORE: {exc}")
    finally:
        assoc.release()

    if status and getattr(status, "Status", None) == 0x0000:
        return ResultadoEnvio(True, f"Armazenado em {ae_title}@{host}:{port}")
    codigo = getattr(status, "Status", "sem resposta")
    return ResultadoEnvio(False, f"PACS retornou status {codigo}")
