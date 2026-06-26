"""
Autenticação de médicos: hashing de senha + JWT.

Hashing com PBKDF2-HMAC-SHA256 (stdlib, sem dependência extra de bcrypt).
Token JWT Bearer assinado com `JWT_SECRET`. As rotas que mudam o laudo
(editar/assinar/rejeitar/enviar ao PACS) exigem um médico autenticado — a
identidade do signatário vem do token, não de um parâmetro manipulável.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..db import Medico, SessionLocal

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-trocar-em-producao")
JWT_ALG = "HS256"
JWT_EXPIRA_HORAS = int(os.getenv("JWT_EXPIRA_HORAS", "12"))
PBKDF2_ITER = 200_000

_bearer = HTTPBearer(auto_error=True)


# ---- senha ----------------------------------------------------------------

def hash_senha(senha: str) -> str:
    """Gera 'salt$hash' em hex."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt, PBKDF2_ITER)
    return f"{salt.hex()}${dk.hex()}"

def conferir_senha(senha: str, armazenado: str) -> bool:
    try:
        salt_hex, hash_hex = armazenado.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(salt_hex), PBKDF2_ITER)
    return hmac.compare_digest(dk.hex(), hash_hex)


# ---- token ----------------------------------------------------------------

def criar_token(medico: Medico) -> str:
    agora = datetime.now(timezone.utc)
    payload = {
        "sub": medico.id,
        "nome": medico.nome,
        "crm": medico.crm or "",
        "iat": agora,
        "exp": agora + timedelta(hours=JWT_EXPIRA_HORAS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


# ---- dependência de rota --------------------------------------------------

def _db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_medico_atual(
    cred: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(_db),
) -> Medico:
    try:
        payload = jwt.decode(cred.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")

    medico = db.get(Medico, payload.get("sub"))
    if not medico or not medico.ativo:
        raise HTTPException(status_code=401, detail="Médico não encontrado ou inativo")
    return medico
