"""
Exporta o dataset de fine-tuning a partir dos laudos ASSINADOS.

A matéria-prima do fine-tuning é o que o médico de fato validou: cada exame
assinado vira um par (imagem de-identificada, laudo final corrigido). Esse é o
sinal mais valioso que o sistema gera — o modelo aprende com as correções dos
próprios especialistas da clínica, nos dados dela (privacidade preservada).

Saída: JSONL no formato de chat (system / user+imagem / assistant=laudo JSON),
pronto para SFT. Cada linha referencia a imagem PNG por caminho.

Uso:
    python -m app.treino.exportar_dataset --saida treino.jsonl [--apenas-corrigidos]
"""

from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import select

from ..armazenamento import _caminho as caminho_imagem
from ..db import Exame, SessionLocal, StatusExame
from ..inference.prompts import INSTRUCAO_SISTEMA, montar_prompt_usuario
from ..inference.schema import Laudo


def _foi_corrigido(e: Exame) -> bool:
    """True se o médico realmente alterou os achados em relação à IA."""
    if not (e.laudo_ia and e.laudo_final):
        return False
    return e.laudo_ia.get("achados") != e.laudo_final.get("achados")


def exportar(saida: str, apenas_corrigidos: bool = False) -> int:
    schema_json = json.dumps(Laudo.model_json_schema(), ensure_ascii=False)
    db = SessionLocal()
    n = 0
    try:
        exames = db.scalars(
            select(Exame).where(Exame.status == StatusExame.assinado.value)
        ).all()
        with open(saida, "w", encoding="utf-8") as fh:
            for e in exames:
                img = caminho_imagem(e.id)
                if not e.laudo_final or not os.path.exists(img):
                    continue
                if apenas_corrigidos and not _foi_corrigido(e):
                    continue
                # Alvo: o laudo final sem flags de UI.
                alvo = dict(e.laudo_final)
                alvo.pop("validado_por_medico", None)
                alvo.pop("assinado_por_crm", None)
                alvo.pop("gerado_por_ia", None)

                exemplo = {
                    "messages": [
                        {"role": "system", "content": INSTRUCAO_SISTEMA},
                        {"role": "user", "content": montar_prompt_usuario(schema_json)},
                        {"role": "assistant", "content": json.dumps(alvo, ensure_ascii=False)},
                    ],
                    "imagem": img,
                }
                fh.write(json.dumps(exemplo, ensure_ascii=False) + "\n")
                n += 1
    finally:
        db.close()
    return n


def main() -> None:
    p = argparse.ArgumentParser(description="Exporta dataset de fine-tuning (SFT)")
    p.add_argument("--saida", default="treino.jsonl")
    p.add_argument(
        "--apenas-corrigidos",
        action="store_true",
        help="só exemplos onde o médico mudou os achados (sinal mais forte)",
    )
    args = p.parse_args()
    n = exportar(args.saida, args.apenas_corrigidos)
    print(f"{n} exemplo(s) exportado(s) para {args.saida}")


if __name__ == "__main__":
    main()
