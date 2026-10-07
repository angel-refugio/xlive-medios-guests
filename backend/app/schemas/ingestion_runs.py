"""Esquemas de las corridas de ingesta (botón "Ingesta" de la app)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RunStatus = Literal["running", "completed", "failed"]
RunTrigger = Literal["manual", "scheduled"]


class IngestionRunCreate(BaseModel):
    # 30 = app.services.pipeline.DEFAULT_BATCH_SIZE (no se importa para no invertir la capa:
    # los services dependen de schemas, no al revés). El botón de la app puede pedir un lote
    # más chico (5) para una demostración rápida.
    batch_size: int = Field(default=30, ge=1, le=200)


class IngestionRunErrorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    youtube_video_id: str
    error_message: str
    created_at: datetime


class IngestionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    finished_at: datetime | None
    status: RunStatus
    trigger: RunTrigger
    requested_batch_size: int | None
    processed_count: int
    success_count: int
    error_count: int
    errors: list[IngestionRunErrorOut]
