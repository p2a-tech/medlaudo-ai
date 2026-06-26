"""
Cliente de inferência do MedGemma.

Servimos o MedGemma 4B multimodal via vLLM (API compatível com OpenAI) na GPU
on-premise. Este módulo isola toda a comunicação com o modelo.

Modo MOCK: se `MEDGEMMA_BASE_URL` não estiver configurada, retornamos um laudo
sintético. Isso permite rodar e testar todo o fluxo (DICOM -> laudo -> revisão)
sem GPU, durante o desenvolvimento.
"""

from __future__ import annotations

import json
import os
from typing import Optional

import httpx

from .prompts import INSTRUCAO_SISTEMA, montar_prompt_usuario
from .schema import (
    Achado,
    AchadosTorax,
    Gravidade,
    Lateralidade,
    Laudo,
    Presenca,
    QualidadeTecnica,
    extrair_criticos,
)

MEDGEMMA_BASE_URL = os.getenv("MEDGEMMA_BASE_URL")  # ex.: http://vllm:8000/v1
MEDGEMMA_MODEL = os.getenv("MEDGEMMA_MODEL", "google/medgemma-4b-it")
MEDGEMMA_API_KEY = os.getenv("MEDGEMMA_API_KEY", "nao-utilizado")
TIMEOUT_S = float(os.getenv("MEDGEMMA_TIMEOUT_S", "120"))


class MedGemmaClient:
    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = base_url or MEDGEMMA_BASE_URL
        self.modo_mock = not self.base_url

    async def gerar_laudo(self, imagem_b64: str, mime: str = "image/png") -> Laudo:
        """Gera um rascunho de laudo a partir de uma imagem (base64).

        Retorna sempre um `Laudo` validado e com os achados críticos
        recalculados em código (não confiamos no modelo para a regra de
        criticidade).
        """
        if self.modo_mock:
            laudo = self._laudo_mock()
        else:
            laudo = await self._inferir(imagem_b64, mime)

        # A regra de criticidade é determinística e roda em código.
        laudo.achados_criticos = extrair_criticos(laudo.achados)
        laudo.gerado_por_ia = True
        laudo.validado_por_medico = False
        return laudo

    async def _inferir(self, imagem_b64: str, mime: str) -> Laudo:
        schema_json = json.dumps(Laudo.model_json_schema(), ensure_ascii=False)
        payload = {
            "model": MEDGEMMA_MODEL,
            "messages": [
                {"role": "system", "content": INSTRUCAO_SISTEMA},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": montar_prompt_usuario(schema_json),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{imagem_b64}"
                            },
                        },
                    ],
                },
            ],
            "temperature": 0.0,  # determinismo: laudo não é tarefa criativa
            "max_tokens": 1500,
            # vLLM aceita guided JSON; força a saída a aderir ao schema.
            "extra_body": {"guided_json": Laudo.model_json_schema()},
        }

        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {MEDGEMMA_API_KEY}"},
            )
            resp.raise_for_status()
            conteudo = resp.json()["choices"][0]["message"]["content"]

        return Laudo.model_validate_json(conteudo)

    @staticmethod
    def _laudo_mock() -> Laudo:
        """Laudo sintético para desenvolvimento sem GPU.

        Simula um caso com pequeno derrame à direita, para exercitar a
        priorização e a UI de revisão.
        """
        achados = AchadosTorax(
            derrame_pleural=Achado(
                presenca=Presenca.presente,
                lateralidade=Lateralidade.direita,
                gravidade=Gravidade.moderado,
                descricao="Velamento do seio costofrênico direito.",
                confianca=0.78,
            ),
            cardiomegalia=Achado(
                presenca=Presenca.indeterminado,
                gravidade=Gravidade.leve,
                descricao="Índice cardiotorácico no limite superior.",
                confianca=0.55,
            ),
        )
        return Laudo(
            qualidade_tecnica=QualidadeTecnica(
                adequada=True, incidencia="PA", observacoes="Inspiração adequada."
            ),
            achados=achados,
            impressao=(
                "Derrame pleural de pequeno a moderado volume à direita. "
                "Área cardíaca no limite superior da normalidade. "
                "Correlacionar clinicamente. [RASCUNHO GERADO POR IA — NÃO VALIDADO]"
            ),
        )
