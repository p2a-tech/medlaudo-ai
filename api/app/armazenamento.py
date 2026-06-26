"""
Armazenamento das imagens de-identificadas.

Antes ficavam só em memória (perdidas no restart) — o que impedia treino
posterior. Agora persistem em disco como PNG, em `DADOS_DIR/imagens/`.

Guardamos a imagem JÁ de-identificada (sem PHI), que é a mesma enviada ao
modelo e exibida no viewer. A imagem DICOM original continua no PACS/Orthanc.
"""

from __future__ import annotations

import base64
import os

DADOS_DIR = os.getenv("DADOS_DIR", "./dados")
_IMAGENS_DIR = os.path.join(DADOS_DIR, "imagens")


def _caminho(exame_id: str) -> str:
    return os.path.join(_IMAGENS_DIR, f"{exame_id}.png")


def salvar_imagem(exame_id: str, imagem_b64: str) -> None:
    os.makedirs(_IMAGENS_DIR, exist_ok=True)
    with open(_caminho(exame_id), "wb") as fh:
        fh.write(base64.b64decode(imagem_b64))


def ler_imagem_b64(exame_id: str) -> str | None:
    caminho = _caminho(exame_id)
    if not os.path.exists(caminho):
        return None
    with open(caminho, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def ler_imagem_bytes(exame_id: str) -> bytes | None:
    caminho = _caminho(exame_id)
    if not os.path.exists(caminho):
        return None
    with open(caminho, "rb") as fh:
        return fh.read()
