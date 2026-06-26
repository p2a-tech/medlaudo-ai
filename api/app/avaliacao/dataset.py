"""
Carregamento do conjunto de avaliação.

Manifesto JSON com a verdade-base (ground truth) anotada por especialista:

    [
      {
        "imagem": "caso001.dcm",
        "achados": { "pneumotorax": true, "derrame_pleural": false, ... }
      },
      ...
    ]

- `imagem` é um caminho relativo ao diretório do manifesto.
- `achados` mapeia o nome do campo (igual ao schema) -> presença real (bool).
  Campos omitidos são tratados como ausentes (false).

Aceita imagens DICOM (.dcm) — reusa o mesmo pipeline de de-id/janelamento da
produção — e imagens comuns (.png/.jpg) para datasets já exportados.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

from ..dicom.processamento import processar_dicom


@dataclass
class CasoAvaliacao:
    nome: str
    imagem_b64: str
    mime: str
    verdade: dict[str, bool]  # campo -> presente?


def _imagem_para_b64(caminho: str) -> tuple[str, str]:
    """Lê uma imagem do disco e retorna (base64, mime).

    DICOM passa pelo mesmo processamento da produção (de-id + janelamento).
    """
    ext = os.path.splitext(caminho)[1].lower()
    with open(caminho, "rb") as fh:
        conteudo = fh.read()

    if ext == ".dcm":
        exame = processar_dicom(conteudo)
        return exame.imagem_png_b64, "image/png"

    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    return base64.b64encode(conteudo).decode("ascii"), mime


def carregar_manifesto(caminho_manifesto: str) -> list[CasoAvaliacao]:
    """Carrega o manifesto e as imagens em memória."""
    base = os.path.dirname(os.path.abspath(caminho_manifesto))
    with open(caminho_manifesto, "r", encoding="utf-8") as fh:
        itens = json.load(fh)

    casos: list[CasoAvaliacao] = []
    for item in itens:
        caminho_img = os.path.join(base, item["imagem"])
        b64, mime = _imagem_para_b64(caminho_img)
        verdade = {k: bool(v) for k, v in (item.get("achados") or {}).items()}
        casos.append(
            CasoAvaliacao(nome=item["imagem"], imagem_b64=b64, mime=mime, verdade=verdade)
        )
    return casos
