"""Endpoints del vínculo programa ↔ conductores."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.schemas.program_hosts import ProgramHostLink, ProgramHostsUpdate
from app.services import program_hosts as service

router = APIRouter(
    prefix="/program-hosts", tags=["program-hosts"], dependencies=[Depends(require_admin)]
)


@router.get("", response_model=list[ProgramHostLink])
def list_links(db: Session = Depends(get_db)):
    return service.list_links(db)


@router.put("/{program_id}", response_model=list[ProgramHostLink])
def set_hosts(program_id: int, data: ProgramHostsUpdate, db: Session = Depends(get_db)):
    try:
        return service.set_hosts(db, program_id, data.host_ids)
    except service.ProgramNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except service.InvalidHostError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
