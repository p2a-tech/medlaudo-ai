#!/usr/bin/env bash
#
# Provisiona uma VM Ubuntu (22.04/24.04) com GPU NVIDIA para o MedLaudo-AI:
# driver NVIDIA -> Docker -> nvidia-container-toolkit -> sobe a stack (GPU).
#
# Idempotente e re-executável: rode quantas vezes precisar. Se faltar o driver,
# ele instala e pede um reboot; depois do reboot, rode de novo e ele continua.
#
# Uso (numa VM Ubuntu limpa com GPU):
#   git clone https://github.com/p2a-tech/medlaudo-ai.git
#   cd medlaudo-ai
#   sudo bash deploy/provisionar-vm.sh
#
# Flags:
#   --skip-gpu-check   não roda o teste de GPU dentro do Docker (pula o pull do cuda)
#   --apenas-stack     pula instalações, só (re)sobe a stack
#
set -euo pipefail

# ---- helpers de log ----
c_az=$'\033[0;36m'; c_vd=$'\033[0;32m'; c_am=$'\033[0;33m'; c_vm=$'\033[0;31m'; c_0=$'\033[0m'
info() { echo "${c_az}==>${c_0} $*"; }
ok()   { echo "${c_vd}OK ${c_0} $*"; }
aviso(){ echo "${c_am}!! ${c_0} $*"; }
erro() { echo "${c_vm}ERRO${c_0} $*" >&2; }

SKIP_GPU_CHECK=0
APENAS_STACK=0
for arg in "$@"; do
  case "$arg" in
    --skip-gpu-check) SKIP_GPU_CHECK=1 ;;
    --apenas-stack) APENAS_STACK=1 ;;
    *) erro "flag desconhecida: $arg"; exit 1 ;;
  esac
done

# ---- pré-checagens ----
if [[ $EUID -ne 0 ]]; then
  erro "Rode como root: sudo bash deploy/provisionar-vm.sh"
  exit 1
fi
if ! command -v apt-get >/dev/null 2>&1; then
  erro "Este script é para Ubuntu/Debian (apt). Adapte para outra distro."
  exit 1
fi

# Raiz do repositório = pasta-mãe de deploy/.
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USUARIO_REAL="${SUDO_USER:-root}"
cd "$RAIZ"
info "Repositório: $RAIZ"

# Usa 'docker compose' (v2) ou 'docker-compose' (v1).
compose() { if docker compose version >/dev/null 2>&1; then docker compose "$@"; else docker-compose "$@"; fi; }

instalar_tudo() {
  # ---- Fase 1: pré-requisitos ----
  info "Fase 1/4 — pré-requisitos do sistema"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg git lsb-release >/dev/null
  ok "pré-requisitos instalados"

  # ---- Fase 2: driver NVIDIA ----
  info "Fase 2/4 — driver NVIDIA"
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    ok "driver NVIDIA já ativo ($(nvidia-smi --query-gpu=name --format=csv,noheader | head -1))"
  else
    aviso "driver NVIDIA não detectado — instalando (vai exigir REBOOT)"
    apt-get install -y -qq ubuntu-drivers-common >/dev/null
    ubuntu-drivers autoinstall
    echo
    aviso "Driver instalado. REINICIE a VM e rode este script de novo:"
    echo "    sudo reboot"
    echo "    # após o boot:"
    echo "    cd $RAIZ && sudo bash deploy/provisionar-vm.sh"
    exit 0
  fi

  # ---- Fase 3: Docker ----
  info "Fase 3/4 — Docker"
  if command -v docker >/dev/null 2>&1; then
    ok "Docker já instalado ($(docker --version))"
  else
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
    if [[ "$USUARIO_REAL" != "root" ]]; then
      usermod -aG docker "$USUARIO_REAL" || true
      aviso "Usuário '$USUARIO_REAL' adicionado ao grupo docker (saia/entre p/ valer sem sudo)"
    fi
    ok "Docker instalado"
  fi

  # ---- Fase 4: nvidia-container-toolkit ----
  info "Fase 4/4 — nvidia-container-toolkit (GPU no Docker)"
  if docker info 2>/dev/null | grep -qi nvidia; then
    ok "runtime NVIDIA já configurado no Docker"
  else
    install -m 0755 -d /usr/share/keyrings
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
      | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
      | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
      > /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update -qq
    apt-get install -y -qq nvidia-container-toolkit >/dev/null
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
    ok "nvidia-container-toolkit instalado e Docker configurado"
  fi

  # Verificação de GPU dentro do Docker (opcional).
  if [[ "$SKIP_GPU_CHECK" -eq 0 ]]; then
    info "Verificando acesso à GPU dentro do Docker..."
    if docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi >/dev/null 2>&1; then
      ok "GPU acessível dentro de contêineres"
    else
      aviso "Não consegui validar a GPU no Docker (siga assim mesmo; o vLLM revalida)"
    fi
  fi
}

[[ "$APENAS_STACK" -eq 0 ]] && instalar_tudo

# ---- Configuração (.env) ----
info "Configuração do backend (api/.env)"
if [[ ! -f api/.env ]]; then
  cp api/.env.example api/.env
  chown "$USUARIO_REAL":"$USUARIO_REAL" api/.env 2>/dev/null || true
  echo
  aviso "Criei api/.env a partir do exemplo. EDITE-O antes de subir a stack:"
  echo "    - DATABASE_URL   = string do Neon"
  echo "    - JWT_SECRET     = $(command -v openssl >/dev/null && openssl rand -hex 32 || echo 'gere um valor forte')"
  echo "    - HF_TOKEN       = token do Hugging Face (acesso ao medgemma-4b-it)"
  echo "    - CORS_ORIGINS   = https://medlaudo-ai.vercel.app"
  echo "    - MEDGEMMA_BASE_URL = http://vllm:8000/v1"
  echo
  echo "  nano api/.env   # edite e rode este script de novo (ou com --apenas-stack)"
  exit 0
fi
ok "api/.env encontrado"

# Carrega as variáveis para a substituição do docker compose.
set -a
# shellcheck disable=SC1091
source api/.env
set +a

# ---- Sobe a stack ----
# Sem 'db' (usamos Neon): --no-deps evita subir o Postgres local.
info "Subindo a stack (orthanc + api + vllm) com GPU..."
compose --profile gpu up -d --build --no-deps orthanc api vllm
ok "contêineres iniciados"

# ---- Health check ----
info "Aguardando a API responder em http://localhost:8080/saude ..."
for i in $(seq 1 30); do
  if curl -fs http://localhost:8080/saude >/dev/null 2>&1; then
    ok "API no ar: $(curl -s http://localhost:8080/saude)"
    break
  fi
  sleep 2
  [[ "$i" -eq 30 ]] && aviso "API ainda não respondeu — veja: compose logs api"
done

echo
ok "Provisionamento concluído."
echo "${c_az}Próximos passos:${c_0}"
echo "  1. Crie o primeiro médico:"
echo "       $(command -v docker >/dev/null && echo 'docker') compose exec api python criar_medico.py \"Dra. Ana\" ana@clinica.com SENHA --crm 12345-RS"
echo "  2. O vLLM baixa o MedGemma (vários GB) no 1º boot — acompanhe:"
echo "       compose logs -f vllm        # espere 'Application startup complete'"
echo "  3. Smoke test do modelo real:"
echo "       compose exec api python -m app.avaliacao.verificar_modelo"
echo "  4. Coloque a API atrás de HTTPS (Caddy/Nginx) e aponte VITE_API_URL no Vercel."
echo "  5. Mantenha Orthanc (4242/8042) e o banco em rede PRIVADA — só a API exposta."
