"""Punto de entrada de la API. Ejecutar: uvicorn app.main:app --reload"""
import logging

from fastapi import FastAPI

from app.api import auth, contacts, guests, health, participations, videos
from app.api.catalogs import CATALOG_ROUTERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

app = FastAPI(title="X Live Medios API")
app.include_router(health.router)
app.include_router(auth.router)
for catalog_router in CATALOG_ROUTERS:
    app.include_router(catalog_router)
app.include_router(guests.router)
app.include_router(contacts.router)
app.include_router(videos.router)
app.include_router(participations.guest_router)
app.include_router(participations.video_router)
