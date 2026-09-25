"""Esquemas del vínculo programa ↔ conductores."""
from pydantic import BaseModel


class ProgramHostLink(BaseModel):
    program_id: int
    host_id: int


class ProgramHostsUpdate(BaseModel):
    """Conjunto completo de conductores del programa (reemplaza al anterior)."""

    host_ids: list[int]
