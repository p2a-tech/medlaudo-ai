# MedLaudo-AI

Assistente de inteligência artificial para **laudo de raio-X de tórax**, voltado
a **clínicas de imagem**, rodando **on-premise** (a imagem do paciente nunca sai
do ambiente da clínica). Baseado no **MedGemma 4B** multimodal.

> ⚠️ **Posicionamento clínico-regulatório:** este sistema **não emite diagnóstico
> final**. Ele gera um *rascunho estruturado de laudo* que é **revisado, editado e
> assinado por um médico**. Nada é assinado automaticamente. Todo rascunho é
> marcado como "gerado por IA — não validado" até a assinatura.

## Por que esta arquitetura

- **On-premise / LGPD:** MedGemma tem peso aberto e roda na GPU local. Diferencial
  de venda e conformidade — concorrentes em nuvem estrangeira não conseguem prometer
  isso para um hospital/clínica brasileiro.
- **Saída estruturada (não texto livre):** o modelo preenche um schema clínico
  (`api/app/inference/schema.py`), reduzindo alucinação e tornando cada achado
  auditável.
- **Priorização de críticos:** achados como pneumotórax/derrame volumoso furam a
  fila da worklist. A regra de criticidade é **determinística, em código** — não
  confiamos no modelo para isso.
- **Médico no loop + auditoria + métricas:** cada exame tem trilha de auditoria e
  alimenta indicadores de ROI (taxa de aproveitamento, críticos detectados).

## Componentes

| Serviço | O que é | Porta |
|---|---|---|
| `api` | FastAPI — ingestão DICOM, de-id, inferência, laudos, auditoria | 8080 |
| `web` | React + Vite — worklist, viewer e revisão do laudo | 5173 |
| `db` | PostgreSQL — laudos, auditoria, métricas | 5432 |
| `orthanc` | PACS / receptor DICOM dos equipamentos | 8042 / 4242 |
| `vllm` | (perfil `gpu`) serve o MedGemma 4B na GPU local | 8000 |

## Rodando

### Tudo via Docker (modo MOCK, sem GPU)

```bash
docker compose up --build
# web:    http://localhost:5173
# api:    http://localhost:8080/docs
```

Sem `MEDGEMMA_BASE_URL`, a API roda em **modo mock**: gera um laudo sintético para
exercitar todo o fluxo (upload DICOM → rascunho → revisão → assinatura) sem GPU.

### Com MedGemma de verdade (GPU NVIDIA)

```bash
export HF_TOKEN=seu_token_huggingface   # acesso ao google/medgemma-4b-it
export MEDGEMMA_BASE_URL=http://vllm:8000/v1
docker compose --profile gpu up --build
```

### Desenvolvimento local da API

```bash
cd api
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# sem Postgres? aponte para SQLite ou suba só o serviço db do compose
uvicorn app.main:app --reload --port 8080
```

### Desenvolvimento local da web

```bash
cd web
npm install
npm run dev   # http://localhost:5173
```

## Fluxo de uso

1. Equipamento envia DICOM ao Orthanc (ou faça upload pela web — "+ Enviar DICOM").
2. A API de-identifica, converte a imagem e pede o rascunho ao MedGemma.
3. O radiologista abre a worklist (críticos no topo), revê imagem + achados,
   e **assina** ou **rejeita**.
4. Cada ação fica registrada na auditoria e nas métricas (`GET /metricas`).

## Roadmap

- [ ] Edição campo a campo do laudo na web (hoje: assinar/rejeitar)
- [ ] Geração de DICOM SR + PDF do laudo final
- [ ] Worker assíncrono (fila) para inferência em vez de síncrono
- [ ] Grounding por recuperação de casos similares (MedSigLIP)
- [ ] Captura de correções → fine-tuning local (LoRA)
- [ ] Integração de worklist direto do Orthanc (sem upload manual)
- [ ] Autenticação de médicos + assinatura digital

## Aviso

Software assistivo em desenvolvimento. **Não** é dispositivo médico certificado.
Uso clínico exige validação, responsabilidade médica e adequação regulatória
(ANVISA/CFM) antes de qualquer emprego em produção.
