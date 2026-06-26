"""
Gera um PDF de DEMONSTRAÇÃO TÉCNICA do sistema (não é laudo médico).

Documenta, com honestidade: o estado atual (modo mock, sem GPU), o resultado
bruto que o sistema produz nesse estado, a prova de que esse resultado NÃO
deriva da imagem, e o caminho para uma leitura real. Embute as imagens da
demonstração.

Uso:
    python gerar_demonstracao_pdf.py --saida ../saida/demonstracao.pdf [--raiox CAMINHO]
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os

import numpy as np
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.inference.client import MedGemmaClient


def _png(matriz: np.ndarray, caminho: str) -> None:
    PILImage.fromarray(matriz.astype(np.uint8)).convert("L").save(caminho)


def _achados_str(laudo) -> str:
    presentes = [
        f"{c} ({a['presenca']})"
        for c, a in laudo.achados.model_dump().items()
        if a["presenca"] != "ausente"
    ]
    return ", ".join(presentes) or "nenhum"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--saida", default="../saida/demonstracao.pdf")
    p.add_argument("--raiox", default=None, help="caminho de uma radiografia real (opcional)")
    args = p.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.saida)), exist_ok=True)
    tmpdir = os.path.dirname(os.path.abspath(args.saida))

    # Imagens da demonstração (as mesmas que provam a independência da imagem).
    img_a = os.path.join(tmpdir, "_demo_a.png")
    img_b = os.path.join(tmpdir, "_demo_b.png")
    _png(np.full((256, 256), 15), img_a)
    _png(np.add.outer(range(256), range(256)) % 256, img_b)

    cli = MedGemmaClient()

    def b64(path):
        import base64
        with open(path, "rb") as fh:
            return base64.b64encode(fh.read()).decode()

    laudo_a = asyncio.run(cli.gerar_laudo(b64(img_a)))
    laudo_b = asyncio.run(cli.gerar_laudo(b64(img_b)))

    # ---- monta o PDF ----
    est = getSampleStyleSheet()
    titulo = ParagraphStyle("t", parent=est["Title"], fontSize=16, spaceAfter=2)
    h3 = ParagraphStyle("h3", parent=est["Heading4"],
                        textColor=colors.HexColor("#334155"), spaceBefore=12, spaceAfter=3)
    corpo = est["BodyText"]
    pequeno = ParagraphStyle("p", parent=corpo, fontSize=8,
                            textColor=colors.HexColor("#64748b"))

    el: list = []
    el.append(Paragraph("MedLaudo-AI", pequeno))
    el.append(Paragraph("Demonstração Técnica do Sistema", titulo))
    el.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cbd5e1")))

    # Banner de aviso — em destaque.
    aviso = (
        "<b>ESTE DOCUMENTO NÃO É UM LAUDO MÉDICO.</b> O sistema está rodando em "
        "modo de demonstração (sem o modelo MedGemma em GPU). Nesse modo, a saída "
        "é um <b>placeholder fixo que NÃO analisa os pixels</b> da imagem. Nenhum "
        "achado abaixo deve ser interpretado clinicamente. Diagnóstico por imagem "
        "exige um médico radiologista habilitado."
    )
    el.append(Spacer(1, 6))
    el.append(Paragraph(aviso, ParagraphStyle(
        "aviso", parent=corpo, textColor=colors.HexColor("#991b1b"),
        backColor=colors.HexColor("#fef2f2"), borderColor=colors.HexColor("#fecaca"),
        borderWidth=1, borderPadding=8, leading=14)))

    # Seção 1 — estado
    el.append(Paragraph("1. Estado do sistema", h3))
    modo = "MOCK (sem GPU / sem MedGemma)" if cli.modo_mock else "MedGemma real"
    el.append(Paragraph(f"Modo de inferência: <b>{modo}</b>. Para uma leitura real, "
                        "é necessário servir o MedGemma 4B em GPU (ver seção 4).", corpo))

    # Seção 2 — análise (prova de independência da imagem)
    el.append(Paragraph("2. Análise: o resultado não deriva da imagem", h3))
    el.append(Paragraph(
        "Submetemos ao sistema duas imagens propositalmente opostas. O resultado "
        "foi idêntico — prova de que, neste modo, a saída é um texto fixo, não uma "
        "leitura da imagem.", corpo))
    el.append(Spacer(1, 6))

    tabela = Table([
        [Image(img_a, width=55 * mm, height=55 * mm),
         Image(img_b, width=55 * mm, height=55 * mm)],
        [Paragraph("<b>Imagem A</b> (quase preta)", pequeno),
         Paragraph("<b>Imagem B</b> (gradiente)", pequeno)],
        [Paragraph(f"Achados: {_achados_str(laudo_a)}", pequeno),
         Paragraph(f"Achados: {_achados_str(laudo_b)}", pequeno)],
    ], colWidths=[80 * mm, 80 * mm])
    tabela.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    el.append(tabela)
    el.append(Spacer(1, 4))
    el.append(Paragraph("→ Saídas idênticas para imagens opostas: confirma o placeholder.",
                        ParagraphStyle("nota", parent=pequeno,
                                       textColor=colors.HexColor("#b45309"))))

    # Seção 3 — resultado bruto (placeholder)
    el.append(Paragraph("3. Resultado bruto do sistema (placeholder)", h3))
    el.append(Paragraph(
        f"Impressão devolvida (idêntica para qualquer imagem, não validada): "
        f"<i>{laudo_a.impressao}</i>", corpo))

    # Radiografia real (se fornecida) — apenas exibição, SEM análise.
    if args.raiox and os.path.exists(args.raiox):
        el.append(Paragraph("Radiografia fornecida (apenas exibição — sem análise)", h3))
        el.append(Image(args.raiox, width=90 * mm, height=90 * mm))
        el.append(Paragraph("Esta imagem NÃO foi analisada clinicamente por este "
                            "documento. Encaminhe a um radiologista.", pequeno))

    # Seção 4 — leitura real
    el.append(Paragraph("4. Como obter uma leitura real", h3))
    el.append(Paragraph(
        "1) GPU NVIDIA + HF_TOKEN com acesso a google/medgemma-4b-it.<br/>"
        "2) <font face='Courier'>docker compose --profile gpu up --build</font> "
        "(MEDGEMMA_BASE_URL apontando para o vLLM).<br/>"
        "3) Cada exame passa a gerar um rascunho derivado da imagem, que o "
        "radiologista revisa, corrige e assina.", corpo))

    # Seção 5 — segurança
    el.append(Paragraph("5. Garantias de segurança do sistema", h3))
    el.append(Paragraph(
        "• Nunca auto-assina: todo rascunho fica marcado como 'gerado por IA — não "
        "validado' até a assinatura de um médico.<br/>"
        "• Médico sempre no loop; a responsabilidade diagnóstica é do profissional.<br/>"
        "• Imagens de-identificadas; processamento on-premise (LGPD).", corpo))

    el.append(Spacer(1, 14))
    el.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))
    el.append(Paragraph("Documento gerado automaticamente pelo MedLaudo-AI para fins de "
                        "demonstração técnica. Não constitui ato médico.", pequeno))

    SimpleDocTemplate(args.saida, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                      topMargin=16 * mm, bottomMargin=16 * mm,
                      title="MedLaudo-AI — Demonstração Técnica").build(el)

    # limpa as imagens temporárias da demo
    for f in (img_a, img_b):
        try:
            os.remove(f)
        except OSError:
            pass
    print(f"PDF gerado: {os.path.abspath(args.saida)} ({os.path.getsize(args.saida)} bytes)")


if __name__ == "__main__":
    main()
