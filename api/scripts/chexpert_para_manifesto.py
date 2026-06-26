"""
Converte rótulos estilo CheXpert/MIMIC-CXR no manifesto do harness.

CheXpert e MIMIC-CXR trazem um CSV com uma coluna de caminho da imagem e
colunas por achado com valores: 1.0 (presente), 0.0 (ausente), -1.0 (incerto),
vazio (não mencionado). Este script mapeia essas colunas para os campos do
nosso schema de tórax e gera o JSON consumido por `app.avaliacao.executar`.

Uso:
    python scripts/chexpert_para_manifesto.py train.csv manifesto.json \
        [--incerto ausente|presente|ignorar] [--base-imagens CheXpert-v1.0]

IMPORTANTE: respeite a licença do dataset (CheXpert/MIMIC têm termos de uso
próprios). Use apenas para validação interna, com dados anonimizados.

Sem dependências externas — só a stdlib.
"""

from __future__ import annotations

import argparse
import csv
import json
import os

# Coluna CheXpert -> campo do nosso schema. Colunas não mapeadas são ignoradas.
MAPA = {
    "Pleural Effusion": "derrame_pleural",
    "Pneumothorax": "pneumotorax",
    "Cardiomegaly": "cardiomegalia",
    "Atelectasis": "atelectasia",
    "Consolidation": "consolidacao",
    "Edema": "congestao_pulmonar",
    "Lung Opacity": "opacidade_intersticial",
    "Lung Lesion": "nodulo_ou_massa",
    "Fracture": "fratura",
    "Support Devices": "dispositivos",
}

COL_CAMINHO = "Path"  # CheXpert usa "Path"; MIMIC costuma usar "path"


def _achado_presente(valor: str, incerto: str) -> bool | None:
    """Interpreta um valor da célula. Retorna True/False, ou None p/ ignorar."""
    v = (valor or "").strip()
    if v in ("1", "1.0"):
        return True
    if v in ("0", "0.0", ""):
        return False
    if v in ("-1", "-1.0"):  # incerto
        if incerto == "presente":
            return True
        if incerto == "ausente":
            return False
        return None  # ignorar
    return False


def converter(csv_path: str, saida: str, incerto: str, base_imagens: str | None) -> int:
    with open(csv_path, newline="", encoding="utf-8") as fh:
        leitor = csv.DictReader(fh)
        col_caminho = COL_CAMINHO if COL_CAMINHO in (leitor.fieldnames or []) else "path"
        itens = []
        for linha in leitor:
            caminho = linha.get(col_caminho, "").strip()
            if not caminho:
                continue
            if base_imagens:
                caminho = os.path.join(base_imagens, caminho)
            achados: dict[str, bool] = {}
            for col, campo in MAPA.items():
                if col not in linha:
                    continue
                pres = _achado_presente(linha[col], incerto)
                if pres is None:
                    continue
                # Só registramos positivos; ausentes são o default no harness.
                if pres:
                    achados[campo] = True
            itens.append({"imagem": caminho, "achados": achados})

    with open(saida, "w", encoding="utf-8") as fh:
        json.dump(itens, fh, ensure_ascii=False, indent=2)
    return len(itens)


def main() -> None:
    p = argparse.ArgumentParser(description="CheXpert/MIMIC -> manifesto do harness")
    p.add_argument("csv", help="CSV de rótulos (ex.: CheXpert train.csv)")
    p.add_argument("saida", help="manifesto JSON de saída")
    p.add_argument(
        "--incerto",
        choices=["ausente", "presente", "ignorar"],
        default="ausente",
        help="como tratar rótulos incertos (-1.0); default: ausente",
    )
    p.add_argument("--base-imagens", default=None, help="prefixo de caminho das imagens")
    args = p.parse_args()

    n = converter(args.csv, args.saida, args.incerto, args.base_imagens)
    print(f"{n} caso(s) escritos em {args.saida}")


if __name__ == "__main__":
    main()
