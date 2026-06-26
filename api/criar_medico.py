"""Cria (ou atualiza a senha de) um médico.

Uso:
    python criar_medico.py "Dra. Ana Souza" ana@clinica.com SENHA --crm 12345-RS
"""
import argparse
import uuid

from sqlalchemy import select

from app.auth.seguranca import hash_senha
from app.db import Medico, SessionLocal, init_db


def main() -> None:
    p = argparse.ArgumentParser(description="Cria/atualiza um médico")
    p.add_argument("nome")
    p.add_argument("email")
    p.add_argument("senha")
    p.add_argument("--crm", default=None)
    args = p.parse_args()

    init_db()
    db = SessionLocal()
    try:
        email = args.email.lower()
        medico = db.scalar(select(Medico).where(Medico.email == email))
        if medico:
            medico.senha_hash = hash_senha(args.senha)
            medico.nome = args.nome
            medico.crm = args.crm
            medico.ativo = True
            acao = "atualizado"
        else:
            medico = Medico(
                id=str(uuid.uuid4()),
                nome=args.nome,
                email=email,
                crm=args.crm,
                senha_hash=hash_senha(args.senha),
            )
            db.add(medico)
            acao = "criado"
        db.commit()
        print(f"Médico {acao}: {medico.nome} <{email}> (CRM {medico.crm or '—'})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
