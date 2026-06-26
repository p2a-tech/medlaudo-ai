"""Teste do grounding (encoder mock + índice + injeção no prompt).

Sem GPU: o encoder mock usa histograma de intensidades, então imagens com
conteúdo diferente geram embeddings distintos e a busca por similaridade
recupera o caso correto. Roda com: python teste_grounding.py
"""
import base64
import io
import os
import tempfile

import numpy as np
from PIL import Image

from app.inference.grounding import (
    CasoReferencia,
    Encoder,
    IndiceReferencia,
    formatar_contexto,
)
from app.inference.prompts import montar_prompt_usuario


def png_b64(matriz: np.ndarray) -> str:
    buf = io.BytesIO()
    Image.fromarray(matriz.astype(np.uint8)).convert("L").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def main():
    enc = Encoder()
    assert enc.modo_mock, "esperado modo mock (sem MEDSIGLIP_BASE_URL)"

    # Três imagens com distribuições de intensidade BEM distintas.
    escura = png_b64(np.full((32, 32), 10))
    clara = png_b64(np.full((32, 32), 245))
    gradiente = png_b64((np.add.outer(range(32), range(32)) * 4 % 256))

    indice = IndiceReferencia()
    indice.adicionar(CasoReferencia("escura", enc.encode(escura), "achados: derrame pleural"))
    indice.adicionar(CasoReferencia("clara", enc.encode(clara), "tórax sem achados relevantes"))
    indice.adicionar(CasoReferencia("gradiente", enc.encode(gradiente), "achados: cardiomegalia"))

    # 1) Consulta com uma imagem clara -> vizinho mais próximo deve ser 'clara'.
    consulta = png_b64(np.full((32, 32), 240))  # parecida com 'clara'
    similares = indice.buscar_similares(enc.encode(consulta), k=3)
    top_id, top_score = similares[0][0].id, similares[0][1]
    assert top_id == "clara", f"esperado 'clara', veio '{top_id}'"
    print(f"1. Retrieval correto: vizinho mais próximo = '{top_id}' (sim {top_score:.3f})")

    # 2) Persistência: salvar e recarregar mantém o resultado.
    with tempfile.TemporaryDirectory() as d:
        caminho = os.path.join(d, "indice.json")
        indice.salvar(caminho)
        recarregado = IndiceReferencia.carregar(caminho)
        assert len(recarregado.casos) == 3
        sim2 = recarregado.buscar_similares(enc.encode(consulta), k=1)
        assert sim2[0][0].id == "clara"
        print("2. Índice salvo e recarregado, busca consistente")

    # 3) Contexto formatado entra no prompt do usuário.
    contexto = formatar_contexto(similares)
    assert "referência" in contexto and "similaridade" in contexto
    prompt = montar_prompt_usuario("{}", contexto)
    assert contexto.split("\n")[0] in prompt, "contexto deveria estar no prompt"
    assert "JSON Schema" in prompt
    print("3. Contexto de grounding injetado no prompt do usuário")

    # 4) Sem contexto, o prompt continua válido (grounding é opcional).
    prompt_sem = montar_prompt_usuario("{}", "")
    assert "Casos de referência" not in prompt_sem
    print("4. Prompt sem grounding permanece válido")

    print("\nTODOS OS PASSOS OK")


if __name__ == "__main__":
    main()
