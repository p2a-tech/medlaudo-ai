"""
Smoke test do MedGemma real (uma imagem -> laudo estruturado).

Confirma, assim que a GPU/vLLM estiver de pé, que toda a cadeia funciona:
conexão com o endpoint, prompt clínico, e a saída restrita ao schema
(`guided_json`). É o primeiro check antes de rodar a avaliação completa.

Uso:
    # com o vLLM no ar:
    MEDGEMMA_BASE_URL=http://localhost:8000/v1 \
        python -m app.avaliacao.verificar_modelo caminho/imagem.png

    # sem argumento, gera uma imagem sintética só para exercitar a cadeia.
    python -m app.avaliacao.verificar_modelo
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import sys

from ..inference.client import MedGemmaClient


def _imagem_demo_b64() -> str:
    """Gera um PNG sintético (gradiente) quando nenhuma imagem é fornecida."""
    import numpy as np
    from PIL import Image

    arr = (np.add.outer(range(256), range(256)) % 256).astype("uint8")
    buf = io.BytesIO()
    Image.fromarray(arr).convert("L").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _carregar_b64(caminho: str) -> tuple[str, str]:
    import os

    ext = os.path.splitext(caminho)[1].lower()
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    with open(caminho, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii"), mime


async def _run(caminho: str | None) -> None:
    cliente = MedGemmaClient()
    modo = "MOCK (defina MEDGEMMA_BASE_URL)" if cliente.modo_mock else "MedGemma real"
    print(f"Modo de inferência: {modo}\n")

    if caminho:
        b64, mime = _carregar_b64(caminho)
    else:
        b64, mime = _imagem_demo_b64(), "image/png"

    laudo = await cliente.gerar_laudo(b64, mime)

    # A própria validação Pydantic já garante aderência ao schema.
    print("Laudo estruturado válido recebido. Resumo:")
    print("  qualidade:", laudo.qualidade_tecnica.incidencia,
          "| adequada:", laudo.qualidade_tecnica.adequada)
    presentes = [
        campo
        for campo, a in laudo.achados.model_dump().items()
        if a["presenca"] != "ausente"
    ]
    print("  achados não-ausentes:", presentes or "nenhum")
    print("  achados críticos:", laudo.achados_criticos or "nenhum")
    print("  impressão:", (laudo.impressao or "")[:120])
    print("\nOK: cadeia de inferência -> schema funcionando.")


def main() -> None:
    p = argparse.ArgumentParser(description="Smoke test do MedGemma")
    p.add_argument("imagem", nargs="?", default=None, help="imagem .png/.jpg (opcional)")
    args = p.parse_args()
    try:
        asyncio.run(_run(args.imagem))
    except Exception as exc:  # noqa: BLE001
        print(f"FALHOU: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
