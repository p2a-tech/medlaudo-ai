"""
Constrói o índice de referência para o grounding.

Lê um manifesto anotado (mesmo formato do harness de avaliação: imagem +
achados reais), codifica cada imagem com o Encoder (MedSigLIP em produção,
histograma no mock) e salva o índice JSON consumido pelo MedGemmaClient.

Uso:
    # com MedSigLIP no ar:
    MEDSIGLIP_BASE_URL=http://localhost:8001 \
        python scripts/construir_indice_referencia.py manifesto.json indice.json

    # sem GPU (encoder mock por histograma):
    python scripts/construir_indice_referencia.py manifesto.json indice.json

Use SEMPRE casos anonimizados e respeite a licença do dataset de origem.
"""

from __future__ import annotations

import argparse
import os
import sys

# Permite rodar o script direto (coloca a pasta api/ no path para achar 'app').
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.avaliacao.dataset import carregar_manifesto
from app.inference.grounding import CasoReferencia, Encoder, IndiceReferencia

# Rótulos para o resumo textual de cada caso de referência.
ROTULOS = {
    "consolidacao": "consolidação",
    "opacidade_intersticial": "opacidade intersticial",
    "nodulo_ou_massa": "nódulo/massa",
    "atelectasia": "atelectasia",
    "derrame_pleural": "derrame pleural",
    "pneumotorax": "pneumotórax",
    "cardiomegalia": "cardiomegalia",
    "alargamento_mediastinal": "alargamento mediastinal",
    "congestao_pulmonar": "congestão pulmonar",
    "fratura": "fratura",
    "dispositivos": "dispositivos",
}


def _resumo(verdade: dict) -> str:
    presentes = [ROTULOS[c] for c, v in verdade.items() if v and c in ROTULOS]
    if not presentes:
        return "tórax sem achados relevantes"
    return "achados: " + ", ".join(presentes)


def main() -> None:
    p = argparse.ArgumentParser(description="Constrói índice de referência (grounding)")
    p.add_argument("manifesto", help="manifesto JSON anotado (imagem + achados)")
    p.add_argument("saida", help="índice JSON de saída")
    args = p.parse_args()

    casos = carregar_manifesto(args.manifesto)
    encoder = Encoder()
    print(f"Codificando {len(casos)} caso(s) "
          f"({'mock/histograma' if encoder.modo_mock else 'MedSigLIP'})...")

    indice = IndiceReferencia()
    for caso in casos:
        emb = encoder.encode(caso.imagem_b64)
        indice.adicionar(CasoReferencia(id=caso.nome, embedding=emb, resumo=_resumo(caso.verdade)))

    indice.salvar(args.saida)
    print(f"Índice com {len(indice.casos)} caso(s) salvo em {args.saida}")


if __name__ == "__main__":
    main()
