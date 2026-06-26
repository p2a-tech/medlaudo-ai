"""
Grounding por recuperação de casos similares (MedSigLIP).

Ideia: antes de gerar o laudo, encontrar no banco de referência os casos mais
parecidos com a imagem atual (por similaridade de embedding) e injetar um
resumo deles no prompt. Isso ancora o modelo em exemplos reais e reduz
alucinação ("casos visualmente próximos costumam apresentar X").

Componentes:
- `Encoder`: transforma uma imagem (base64) num vetor de embedding.
    * modo real: chama o MedSigLIP servido em `MEDSIGLIP_BASE_URL`.
    * modo mock (sem GPU): histograma de intensidades normalizado — é um
      embedding baseado em CONTEÚDO, determinístico, então imagens parecidas
      ficam próximas e a recuperação funciona de verdade nos testes.
- `IndiceReferencia`: guarda embeddings + resumo dos achados dos casos de
  referência; busca os K mais similares por cosseno. Persiste em JSON.

O índice de referência deve ser construído a partir de casos ANOTADOS e
anonimizados (ver scripts/construir_indice_referencia.py).
"""

from __future__ import annotations

import base64
import io
import json
import os

import httpx
import numpy as np

MEDSIGLIP_BASE_URL = os.getenv("MEDSIGLIP_BASE_URL")  # ex.: http://medsiglip:8001
# Histograma grosso: bins largos toleram pequenas variações de intensidade,
# então imagens visualmente próximas geram embeddings próximos (placeholder).
DIM_MOCK = 16


def grounding_ativo() -> bool:
    return os.getenv("GROUNDING_ATIVO", "0") in ("1", "true", "True")


class Encoder:
    """Codifica imagens em embeddings."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url if base_url is not None else MEDSIGLIP_BASE_URL
        self.modo_mock = not self.base_url

    def encode(self, imagem_b64: str) -> list[float]:
        if self.modo_mock:
            return self._mock(imagem_b64)
        return self._remoto(imagem_b64)

    def _mock(self, imagem_b64: str) -> list[float]:
        """Histograma de intensidades (64 bins) L2-normalizado.

        Placeholder baseado em conteúdo: imagens semelhantes geram vetores
        próximos, então a busca por similaridade já é exercitável sem GPU.
        """
        from PIL import Image

        dados = base64.b64decode(imagem_b64)
        img = Image.open(io.BytesIO(dados)).convert("L")
        arr = np.asarray(img, dtype=np.float32).ravel()
        hist, _ = np.histogram(arr, bins=DIM_MOCK, range=(0, 255))
        v = hist.astype(np.float32)
        norma = np.linalg.norm(v)
        if norma > 0:
            v = v / norma
        return v.tolist()

    def _remoto(self, imagem_b64: str) -> list[float]:
        """Pede o embedding ao MedSigLIP (endpoint próprio).

        Contrato esperado: POST {base_url}/embed {"image_b64": ...}
        -> {"embedding": [floats]}.
        """
        with httpx.Client(timeout=60) as cli:
            resp = cli.post(f"{self.base_url}/embed", json={"image_b64": imagem_b64})
            resp.raise_for_status()
            return list(resp.json()["embedding"])


class CasoReferencia:
    def __init__(self, id: str, embedding: list[float], resumo: str) -> None:
        self.id = id
        self.embedding = embedding
        self.resumo = resumo

    def to_dict(self) -> dict:
        return {"id": self.id, "embedding": self.embedding, "resumo": self.resumo}


class IndiceReferencia:
    """Índice em memória de casos de referência, com persistência em JSON."""

    def __init__(self, casos: list[CasoReferencia] | None = None) -> None:
        self.casos = casos or []
        self._matriz: np.ndarray | None = None
        self._reindexar()

    def _reindexar(self) -> None:
        if self.casos:
            self._matriz = np.array([c.embedding for c in self.casos], dtype=np.float32)
        else:
            self._matriz = None

    def adicionar(self, caso: CasoReferencia) -> None:
        self.casos.append(caso)
        self._reindexar()

    def buscar_similares(self, embedding: list[float], k: int = 3) -> list[tuple[CasoReferencia, float]]:
        """Retorna os k casos mais similares (cosseno), do mais para o menos."""
        if self._matriz is None or not self.casos:
            return []
        q = np.array(embedding, dtype=np.float32)
        qn = np.linalg.norm(q)
        if qn == 0:
            return []
        mn = np.linalg.norm(self._matriz, axis=1)
        mn[mn == 0] = 1e-9
        sims = (self._matriz @ q) / (mn * qn)
        ordem = np.argsort(-sims)[:k]
        return [(self.casos[i], float(sims[i])) for i in ordem]

    # ---- persistência ----
    def salvar(self, caminho: str) -> None:
        with open(caminho, "w", encoding="utf-8") as fh:
            json.dump([c.to_dict() for c in self.casos], fh, ensure_ascii=False)

    @classmethod
    def carregar(cls, caminho: str) -> "IndiceReferencia":
        with open(caminho, "r", encoding="utf-8") as fh:
            itens = json.load(fh)
        casos = [CasoReferencia(i["id"], i["embedding"], i["resumo"]) for i in itens]
        return cls(casos)


def formatar_contexto(similares: list[tuple[CasoReferencia, float]]) -> str:
    """Monta o trecho de contexto a injetar no prompt a partir dos casos."""
    if not similares:
        return ""
    linhas = ["Casos de referência visualmente semelhantes (apenas para apoio, "
              "não copie — avalie a imagem atual):"]
    for caso, score in similares:
        linhas.append(f"- (similaridade {score:.2f}) {caso.resumo}")
    return "\n".join(linhas)
