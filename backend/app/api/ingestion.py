"""Endpoint del botón "Ingesta": dispara una corrida manual del orquestador (protegido)."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.schemas.ingestion_runs import IngestionRunCreate, IngestionRunOut
from app.services import pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingestion", tags=["ingestion"], dependencies=[Depends(require_admin)])


@router.post("/runs", response_model=IngestionRunOut, status_code=201)
def create_run(data: IngestionRunCreate, db: Session = Depends(get_db)):
    """Corre de forma síncrona (puede tardar varios minutos con un LLM local en CPU)."""
    try:
        return pipeline.trigger_manual_run(db, data.batch_size)
    except RuntimeError as exc:
        # Falta YOUTUBE_API_KEY u OLLAMA_MODEL: no se llegó a crear ningún IngestionRun.
        logger.error("[app.api.ingestion.create_run] %s", exc)
        raise HTTPException(status_code=422, detail=str(exc))
