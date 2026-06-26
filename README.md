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

## Autenticação e médicos

As rotas que mudam o laudo (editar/assinar/rejeitar/enviar ao PACS) exigem um
médico autenticado (JWT Bearer). A identidade do signatário vem do token, não de
um parâmetro — o CRM é gravado no laudo assinado.

Crie um médico:

```bash
cd api
python criar_medico.py "Dra. Ana Souza" ana@clinica.com SENHA --crm 12345-RS
```

A web mostra uma tela de login; o token fica no navegador e é enviado nas ações.

## Inferência assíncrona

Por padrão a inferência é **assíncrona**: o upload responde na hora (status
`aguardando`) e um worker em processo (fila `asyncio`) gera o rascunho logo em
seguida — o upload nunca trava esperando a GPU. A worklist faz polling e mostra
o exame virar `rascunho_pronto`. Para um modo determinístico (testes), use
`INFERENCIA_SINCRONA=1` (processa inline e devolve o rascunho na resposta).

## Worklist automática (Orthanc)

O caminho normal não tem upload manual: o equipamento envia o DICOM ao Orthanc
(C-STORE) e um **poller** observa a API `/changes` do Orthanc, puxa cada
instância nova e a injeta no pipeline (de-id → fila → MedGemma). O último `Seq`
processado fica persistido (`EstadoOrthanc`) para retomar após restart sem
reprocessar, e há **dedup por SOPInstanceUID**. Ligado por `ORTHANC_POLL=1`
(default na stack Docker). O upload manual continua disponível como alternativa.

## Fluxo de uso

1. Equipamento envia DICOM ao Orthanc → o poller ingere automaticamente
   (ou faça upload pela web — "+ Enviar DICOM").
2. A API de-identifica, converte a imagem e pede o rascunho ao MedGemma.
3. O radiologista abre a worklist (críticos no topo), revê imagem + achados,
   e **assina** ou **rejeita**.
4. Cada ação fica registrada na auditoria e nas métricas (`GET /metricas`).

## Colocar o MedGemma real em produção (runbook)

Toda a base roda em modo mock sem GPU. Para ligar o modelo de verdade:

1. **GPU + token.** Máquina com GPU NVIDIA e `HF_TOKEN` com acesso a
   `google/medgemma-4b-it` (aceite os termos no Hugging Face).
2. **Suba a stack com vLLM:**
   ```bash
   export HF_TOKEN=...   # acesso ao modelo
   export MEDGEMMA_BASE_URL=http://vllm:8000/v1
   docker compose --profile gpu up --build
   ```
3. **Smoke test** (confirma conexão + saída restrita ao schema):
   ```bash
   cd api
   MEDGEMMA_BASE_URL=http://localhost:8000/v1 \
     python -m app.avaliacao.verificar_modelo caminho/imagem.png
   ```
4. **Meça a qualidade** contra um dataset anotado (ver harness abaixo). Para
   datasets públicos estilo CheXpert/MIMIC-CXR, converta os rótulos:
   ```bash
   python scripts/chexpert_para_manifesto.py train.csv manifesto.json \
       --base-imagens CheXpert-v1.0 --incerto ausente
   MEDGEMMA_BASE_URL=http://localhost:8000/v1 \
     python -m app.avaliacao.executar manifesto.json --saida resultado.json
   ```
   > Respeite a licença do dataset; use só para validação interna, anonimizado.

## Avaliação de qualidade (harness)

Antes de confiar o MedGemma a uma clínica, é preciso **medir** a qualidade dos
achados contra um conjunto anotado por especialista. O harness em
`api/app/avaliacao/` faz isso.

1. Monte um manifesto JSON (veja `app/avaliacao/exemplo_manifesto.json`):
   cada item aponta uma imagem (`.dcm`/`.png`/`.jpg`) e os achados reais.
2. Rode (sem `MEDGEMMA_BASE_URL` usa o mock; com ela, mede o modelo real):

```bash
cd api
python -m app.avaliacao.executar caminho/do/manifesto.json --saida resultado.json
```

Saída: tabela por achado com **sensibilidade** e **especificidade** (críticos no
topo), agregados gerais e de críticos, e a lista de **achados críticos perdidos**
(falsos negativos em pneumotórax/derrame) — o erro que mais importa evitar.

Política de decisão: em achados críticos, `indeterminado` conta como POSITIVO
(na dúvida, sinaliza ao médico); em não-críticos, conta como negativo.

## Roadmap

- [x] Edição campo a campo do laudo na web
- [x] Geração de PDF + DICOM (Encapsulated PDF) do laudo final
- [x] Envio automático do laudo ao PACS na assinatura (C-STORE) + reenvio manual
- [x] Harness de avaliação (sensibilidade/especificidade por achado, foco em críticos)
- [x] Worker assíncrono (fila em processo) para inferência
- [x] Autenticação de médicos (JWT) + CRM no laudo assinado
- [ ] Rodar o MedGemma real em GPU e medir contra dataset anotado
- [x] Worklist automática via poller do Orthanc (sem upload manual) + dedup
- [ ] Grounding por recuperação de casos similares (MedSigLIP)
- [ ] Captura de correções → fine-tuning local (LoRA)
- [ ] Assinatura digital com certificado ICP-Brasil

## Aviso

Software assistivo em desenvolvimento. **Não** é dispositivo médico certificado.
Uso clínico exige validação, responsabilidade médica e adequação regulatória
(ANVISA/CFM) antes de qualquer emprego em produção.
