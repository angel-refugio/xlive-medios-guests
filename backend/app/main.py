"""Punto de entrada de la API. Ejecutar: uvicorn app.main:app --reload"""
import logging

from fastapi import FastAPI

from app.api import health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

app = FastAPI(title="X Live Medios API")
app.include_router(health.router)
