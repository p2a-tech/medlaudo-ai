# Deploy — MedLaudo-AI (arquitetura híbrida)

O MedLaudo-AI não roda inteiro no Vercel: o backend precisa de **GPU** (MedGemma),
**PACS/DICOM** (Orthanc), **worker em background** e **disco persistente**. Então:

```
  Frontend (React/Vite)        Banco                Backend (FastAPI + MedGemma + Orthanc)
  ───────────────────────      ─────────            ──────────────────────────────────────
        Vercel        ──────►   Neon (Postgres)  ◄────────  VM com GPU NVIDIA
   (estático, global)          (gerenciado)               docker compose --profile gpu
        │                                                        │
        └────────────── HTTPS (VITE_API_URL) ───────────────────┘
```

- **Frontend → Vercel** (encaixe ideal).
- **Banco → Neon** (Postgres gerenciado; o código aceita a string do Neon direto).
- **Backend → VM com GPU** (on-prem ou cloud com NVIDIA).

> O que exige **login no navegador** (criar conta Neon, autorizar Vercel) é você
> quem faz — o código e a config abaixo já estão prontos.

---

## 1. Banco no Neon

Opção A (recomendada, integra billing/env com o Vercel):
1. No painel do projeto Vercel → **Storage → Create Database → Neon (Postgres)**.
2. Crie o banco `medlaudo`. O Vercel injeta `DATABASE_URL` no frontend, mas quem
   usa o banco é o **backend** — copie a connection string.

Opção B: crie em <https://neon.tech>, projeto `medlaudo`, e copie a connection
string (formato `postgresql://user:pass@ep-xxx.sa-east-1.aws.neon.tech/medlaudo?sslmode=require`).

> O backend aceita esse formato cru — `app/db.py` reescreve para o driver psycopg
> e o `sslmode=require` do Neon é respeitado.

---

## 2. Backend na VM com GPU

Requisitos: VM com **GPU NVIDIA**, Docker + **nvidia-container-toolkit**, e um
`HF_TOKEN` com acesso a `google/medgemma-4b-it`.

```bash
git clone https://github.com/p2a-tech/medlaudo-ai.git
cd medlaudo-ai

# configure o backend
cp api/.env.example api/.env
#  - DATABASE_URL = string do Neon
#  - JWT_SECRET   = openssl rand -hex 32
#  - HF_TOKEN     = token do Hugging Face
#  - CORS_ORIGINS = https://SEU-PROJETO.vercel.app
#  - MEDGEMMA_BASE_URL = http://vllm:8000/v1
export $(grep -v '^#' api/.env | xargs)   # ou use um env_file no compose

# sobe API + Orthanc + MedGemma na GPU (sem o Postgres local — usamos Neon)
docker compose --profile gpu up -d --build orthanc api vllm

# cria o primeiro médico
docker compose exec api python criar_medico.py "Dra. Ana" ana@clinica.com SENHA --crm 12345-RS
```

Coloque a API atrás de **HTTPS** (Caddy/Nginx/Traefik) num domínio, ex.:
`https://api.suaclinica.com` → contêiner `api:8080`. Esse domínio é o `VITE_API_URL`.

> Usando Neon, você não precisa do serviço `db` do compose — suba só
> `orthanc api vllm` como acima. Se preferir Postgres local, inclua `db`.

Smoke test do modelo real:
```bash
docker compose exec api python -m app.avaliacao.verificar_modelo
```

---

## 3. Frontend no Vercel

```bash
npm i -g vercel
cd medlaudo-ai
vercel login                 # (login no navegador — você faz)
vercel link                  # vincula a um projeto Vercel
```

No painel do projeto (ou no link), configure:
- **Root Directory:** `web`  (o `web/vercel.json` cuida de framework/SPA)
- **Environment Variable:** `VITE_API_URL = https://api.suaclinica.com` (Production)

Deploy:
```bash
vercel --prod                # ou: cd web && vercel --prod
```

Depois do primeiro deploy, ajuste `CORS_ORIGINS` no backend para o domínio que o
Vercel gerou e reinicie a API.

---

## 4. Checklist pós-deploy

- [ ] `https://api.suaclinica.com/saude` responde `{"ok": true, ...}`.
- [ ] Frontend Vercel abre a tela de login.
- [ ] Login com o médico criado funciona (token salvo).
- [ ] `CORS_ORIGINS` = domínio do Vercel (sem `*` em produção).
- [ ] `JWT_SECRET` forte e único (não o default).
- [ ] HTTPS na API; Orthanc **não** exposto publicamente (só rede interna).
- [ ] Backup do Neon habilitado.
- [ ] `MEDGEMMA_BASE_URL` setada (senão o sistema fica em modo MOCK).

---

## Notas de segurança/LGPD

- Em produção, mantenha o **Orthanc e o banco em rede privada** — só a API exposta.
- Imagens de paciente ficam na VM (`DADOS_DIR`) e no PACS; o Neon guarda apenas
  metadados/laudos. Avalie criptografia em repouso conforme a política da clínica.
- O sistema é **assistivo**: nenhum laudo é válido sem assinatura médica.
