"""Lógica del vínculo programa ↔ conductores (N↔N)."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalogs import Host, Program, program_host_links

logger = logging.getLogger(__name__)


class ProgramNotFoundError(LookupError):
    pass


class InvalidHostError(ValueError):
    """Un conductor indicado no existe o está desactivado."""


def list_links(db: Session) -> list[dict]:
    """Todos los vínculos (program_id, host_id), ordenados para que el resultado sea estable."""
    rows = db.execute(
        select(program_host_links.c.program_id, program_host_links.c.host_id).order_by(
            program_host_links.c.program_id, program_host_links.c.host_id
        )
    )
    return [{"program_id": program_id, "host_id": host_id} for program_id, host_id in rows]


def set_hosts(db: Session, program_id: int, host_ids: list[int]) -> list[dict]:
    """Reemplaza los conductores de un programa. Devuelve los vínculos del programa.

    Un conductor desactivado solo se acepta si el programa ya lo tenía (para poder
    guardar sin quitarlo a la fuerza).
    """
    program = db.get(Program, program_id)
    if program is None:
        msg = f"No existe el programa {program_id}"
        logger.warning("[app.services.program_hosts.set_hosts] %s", msg)
        raise ProgramNotFoundError(msg)

    already = {host.id for host in program.hosts}
    hosts: dict[int, Host] = {}
    for host_id in host_ids:
        host = db.get(Host, host_id)
        if host is None or (not host.is_active and host_id not in already):
            msg = f"El conductor {host_id} no existe o está desactivado"
            logger.warning("[app.services.program_hosts.set_hosts] %s", msg)
            raise InvalidHostError(msg)
        hosts[host.id] = host

    program.hosts = list(hosts.values())
    db.commit()
    return [{"program_id": program_id, "host_id": host_id} for host_id in sorted(hosts)]
