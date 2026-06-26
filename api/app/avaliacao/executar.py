"""
Executor da avaliação do MedGemma sobre um conjunto rotulado.

Uso:
    python -m app.avaliacao.executar <manifesto.json> [--saida resultado.json]

Para cada caso: roda o modelo (ou o mock, se MEDGEMMA_BASE_URL não estiver
setada), compara os achados previstos com a verdade-base e acumula a matriz
de confusão por campo. Ao final imprime a tabela e, opcionalmente, salva o
JSON com o resumo.

Os achados perdidos críticos (falsos negativos em pneumotórax/derrame) são
destacados — é o erro que mais importa evitar.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from ..inference.client import MedGemmaClient
from ..inference.schema import AchadosTorax
from .dataset import carregar_manifesto
from .metricas import CRITICOS, Contagem, pred_positiva, resumo, tabela_texto

# Todos os campos de achado do schema.
CAMPOS = list(AchadosTorax.model_fields.keys())


async def avaliar(manifesto: str, saida: str | None = None) -> dict:
    casos = carregar_manifesto(manifesto)
    cliente = MedGemmaClient()
    modo = "MOCK" if cliente.modo_mock else "MedGemma"
    print(f"Avaliando {len(casos)} caso(s) em modo {modo}...\n")

    por_campo: dict[str, Contagem] = {campo: Contagem() for campo in CAMPOS}
    perdas_criticas: list[str] = []

    for caso in casos:
        laudo = await cliente.gerar_laudo(caso.imagem_b64, caso.mime)
        achados = laudo.achados.model_dump()
        for campo in CAMPOS:
            gt = caso.verdade.get(campo, False)
            presenca = achados[campo]["presenca"]
            pred = pred_positiva(presenca, campo in CRITICOS)
            por_campo[campo].add(gt, pred)
            if campo in CRITICOS and gt and not pred:
                perdas_criticas.append(f"{caso.nome}: {campo} não detectado")

    print(tabela_texto(por_campo))
    res = resumo(por_campo)

    crit = res["criticos"]
    print(
        f"\nCríticos — sensibilidade {crit['sensibilidade']} | "
        f"perdidos {crit['perdidos']}/{crit['suporte']}"
    )
    if perdas_criticas:
        print("\n[!] ACHADOS CRITICOS PERDIDOS:")
        for p in perdas_criticas:
            print("  -", p)

    if saida:
        with open(saida, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
        print(f"\nResumo salvo em {saida}")

    return res


def main() -> None:
    parser = argparse.ArgumentParser(description="Avaliação do MedGemma em tórax")
    parser.add_argument("manifesto", help="caminho do manifesto JSON")
    parser.add_argument("--saida", help="caminho do JSON de resultado", default=None)
    args = parser.parse_args()
    asyncio.run(avaliar(args.manifesto, args.saida))


if __name__ == "__main__":
    main()
