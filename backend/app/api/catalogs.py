"""Endpoints de los 5 catálogos, generados con una sola fábrica de routers."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.catalogs import Borough, ContactType, GuestCategory, Program, VideoType
from app.schemas.catalogs import CatalogCreate, CatalogOut, CatalogUpdate
from app.services import catalogs as service


def make_catalog_router(prefix: str, model, tag: str) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag], dependencies=[Depends(require_admin)])

    @router.get("", response_model=list[CatalogOut])
    def list_items(include_inactive: bool = False, db: Session = Depends(get_db)):
        return service.list_items(db, model, include_inactive)

    @router.post("", response_model=CatalogOut, status_code=201)
    def create_item(data: CatalogCreate, db: Session = Depends(get_db)):
        try:
            return service.create_item(db, model, data)
        except service.CatalogDuplicateError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @router.patch("/{item_id}", response_model=CatalogOut)
    def update_item(item_id: int, data: CatalogUpdate, db: Session = Depends(get_db)):
        try:
            return service.update_item(db, model, item_id, data)
        except service.CatalogNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except service.CatalogDuplicateError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    return router


CATALOG_ROUTERS = [
    make_catalog_router("/guest-categories", GuestCategory, "guest-categories"),
    make_catalog_router("/boroughs", Borough, "boroughs"),
    make_catalog_router("/video-types", VideoType, "video-types"),
    make_catalog_router("/contact-types", ContactType, "contact-types"),
    make_catalog_router("/programs", Program, "programs"),
]
