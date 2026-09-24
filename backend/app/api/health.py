"""Endpoint de salud: confirma que la API responde y que la BD es alcanzable."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("[app.api.health.health] No se pudo consultar la base de datos")
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    return {"status": "ok", "database": "ok"}
