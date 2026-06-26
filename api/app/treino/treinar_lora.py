"""
Fine-tuning LoRA do MedGemma a partir das correções dos médicos.

LoRA (Low-Rank Adaptation) treina apenas pequenos adaptadores, não o modelo
inteiro — cabe em uma GPU modesta e mantém o modelo-base intacto. A clínica
adapta o MedGemma aos seus próprios laudos sem reescrever o modelo.

ESTE SCRIPT EXIGE GPU e dependências pesadas (requirements-treino.txt:
torch, transformers, peft, trl, datasets, accelerate, bitsandbytes). Os imports
ficam dentro de main() de propósito, para o módulo ser importável (e testável)
sem essas libs instaladas.

Uso (na máquina com GPU):
    pip install -r requirements-treino.txt
    python -m app.treino.exportar_dataset --saida treino.jsonl
    python -m app.treino.treinar_lora treino.jsonl --saida ./medgemma-lora

Depois, sirva o modelo-base + adaptador no vLLM e aponte MEDGEMMA_BASE_URL.
"""

from __future__ import annotations

import argparse
import json


def carregar_exemplos(jsonl: str) -> list[dict]:
    exemplos = []
    with open(jsonl, "r", encoding="utf-8") as fh:
        for linha in fh:
            linha = linha.strip()
            if linha:
                exemplos.append(json.loads(linha))
    return exemplos


def main() -> None:
    p = argparse.ArgumentParser(description="Fine-tuning LoRA do MedGemma")
    p.add_argument("dataset", help="JSONL gerado por exportar_dataset")
    p.add_argument("--modelo-base", default="google/medgemma-4b-it")
    p.add_argument("--saida", default="./medgemma-lora")
    p.add_argument("--epocas", type=int, default=3)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--rank", type=int, default=16)
    args = p.parse_args()

    exemplos = carregar_exemplos(args.dataset)
    if not exemplos:
        raise SystemExit("Dataset vazio — gere com exportar_dataset primeiro.")
    print(f"{len(exemplos)} exemplo(s) carregado(s).")

    # Imports pesados aqui dentro (exigem GPU / libs de treino).
    import torch  # noqa: F401
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoModelForImageTextToText, AutoProcessor
    from trl import SFTConfig, SFTTrainer

    processor = AutoProcessor.from_pretrained(args.modelo_base)
    modelo = AutoModelForImageTextToText.from_pretrained(
        args.modelo_base, torch_dtype="bfloat16", device_map="auto"
    )

    lora = LoraConfig(
        r=args.rank,
        lora_alpha=args.rank * 2,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )

    dataset = Dataset.from_list(exemplos)

    def formatar(lote):
        # Carrega a imagem e aplica o chat template multimodal.
        from PIL import Image

        textos, imagens = [], []
        for msgs, img in zip(lote["messages"], lote["imagem"]):
            textos.append(processor.apply_chat_template(msgs, tokenize=False))
            imagens.append(Image.open(img).convert("RGB"))
        return processor(text=textos, images=imagens, return_tensors="pt", padding=True)

    cfg = SFTConfig(
        output_dir=args.saida,
        num_train_epochs=args.epocas,
        learning_rate=args.lr,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        logging_steps=10,
        save_strategy="epoch",
        bf16=True,
    )

    trainer = SFTTrainer(
        model=modelo,
        args=cfg,
        train_dataset=dataset,
        peft_config=lora,
        data_collator=formatar,
    )
    trainer.train()
    trainer.save_model(args.saida)
    print(f"Adaptador LoRA salvo em {args.saida}")


if __name__ == "__main__":
    main()
