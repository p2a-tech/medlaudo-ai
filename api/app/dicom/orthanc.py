"""
Cliente REST do Orthanc + ingestão automática de exames novos.

Em vez de o técnico subir o DICOM na web, o equipamento envia ao Orthanc
(C-STORE) e este poller observa a API de mudanças do Orthanc (`/changes`),
puxa cada instância nova e a injeta no mesmo pipeline de ingestão.

A API `/changes` do Orthanc é incremental: cada evento tem um `Seq`. Guardamos
o último `Seq` processado (tabela `EstadoOrthanc`) para retomar de onde paramos
após um restart, sem reprocessar.
"""

from __future__ import annotations

import os

import httpx


class OrthancClient:
    def __init__(
        self,
        base_url: str | None = None,
        usuario: str | None = None,
        senha: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("ORTHANC_URL", "http://orthanc:8042")).rstrip("/")
        usuario = usuario or os.getenv("ORTHANC_USER")
        senha = senha or os.getenv("ORTHANC_PASS")
        self.auth = (usuario, senha) if usuario else None

    async def get_changes(self, desde: int, limite: int = 50) -> dict:
        """Lista mudanças a partir de `desde`. Retorna {Changes, Done, Last}."""
        async with httpx.AsyncClient(timeout=15, auth=self.auth) as cli:
            resp = await cli.get(
                f"{self.base_url}/changes",
                params={"since": desde, "limit": limite},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_instance_file(self, instance_id: str) -> bytes:
        """Baixa o arquivo DICOM bruto de uma instância."""
        async with httpx.AsyncClient(timeout=60, auth=self.auth) as cli:
            resp = await cli.get(f"{self.base_url}/instances/{instance_id}/file")
            resp.raise_for_status()
            return resp.content


def poll_ligado() -> bool:
    return os.getenv("ORTHANC_POLL", "0") in ("1", "true", "True")
