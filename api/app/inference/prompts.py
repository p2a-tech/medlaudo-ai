"""
Prompt clínico do MedGemma para raio-X de tórax.

Princípios de design do prompt (cada um existe para reduzir risco clínico):

1. Papel de ASSISTENTE, nunca de diagnosticador final.
2. Leitura sistemática — força o modelo a varrer todas as estruturas, não só
   o achado mais óbvio (reduz erro de "satisfação de busca").
3. Saída em JSON aderente ao schema — sem texto livre solto.
4. Incerteza é permitida e incentivada ('indeterminado' é melhor que chutar).
5. Sem dados do paciente no prompt — a imagem já chega de-identificada.
"""

from __future__ import annotations

INSTRUCAO_SISTEMA = """\
Você é um assistente de inteligência artificial que auxilia médicos \
radiologistas na elaboração de laudos de radiografia de tórax. \
Você NÃO emite diagnóstico final nem toma decisões clínicas: você produz um \
rascunho estruturado que será revisado, corrigido e assinado por um médico.

Regras invioláveis:
- Analise APENAS o que é visível na imagem. Nunca infira história clínica.
- Faça uma leitura sistemática de todas as estruturas torácicas.
- Quando houver dúvida, marque o achado como "indeterminado". É sempre \
preferível admitir incerteza a afirmar algo incorreto.
- Se a imagem tiver qualidade técnica insuficiente, sinalize isso e seja \
conservador nos achados.
- Responda SOMENTE com um objeto JSON válido, sem texto antes ou depois.
"""

# Roteiro de leitura sistemática injetado no prompt do usuário.
ROTEIRO_LEITURA = """\
Leia a radiografia de tórax de forma sistemática e avalie cada item:

1. Qualidade técnica: incidência (PA/AP/perfil), inspiração, rotação, \
penetração. A imagem é adequada para laudo?
2. Parênquima pulmonar: consolidação, opacidade intersticial, \
nódulo ou massa, atelectasia.
3. Pleura: derrame pleural, pneumotórax.
4. Mediastino e coração: cardiomegalia, alargamento mediastinal, \
congestão/edema pulmonar.
5. Ossos e partes moles: fraturas, lesões ósseas.
6. Dispositivos: tubos, cateteres, drenos, marca-passo.

Para cada achado informe: presença (ausente/presente/indeterminado), \
lateralidade quando aplicável, gravidade (normal/leve/moderado/acentuado/\
critico), descrição curta e sua confiança (0 a 1).
"""


def montar_prompt_usuario(schema_json: str, contexto: str = "") -> str:
    """Monta a mensagem do usuário com o roteiro e o schema-alvo.

    `schema_json` é o JSON Schema do modelo `Laudo`, para o MedGemma saber
    exatamente a estrutura esperada da resposta. `contexto` é o trecho opcional
    de grounding (casos de referência similares) injetado antes do roteiro.
    """
    bloco_contexto = f"{contexto}\n\n" if contexto else ""
    return (
        f"{bloco_contexto}"
        f"{ROTEIRO_LEITURA}\n\n"
        "Produza o laudo como um objeto JSON que valide contra o seguinte "
        "JSON Schema (preencha todos os campos relevantes):\n\n"
        f"```json\n{schema_json}\n```\n\n"
        "Responda apenas com o objeto JSON do laudo."
    )
