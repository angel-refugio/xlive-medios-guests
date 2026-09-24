"""Importa todos los modelos para que queden registrados en Base.metadata."""
from app.models.catalogs import Borough, ContactType, GuestCategory, Program, VideoType
from app.models.contact import Contact
from app.models.guest import Guest, guest_category_links
from app.models.participation import Participation
from app.models.user import User
from app.models.video import Video

__all__ = [
    "User",
    "Borough",
    "Contact",
    "ContactType",
    "Guest",
    "GuestCategory",
    "Participation",
    "Program",
    "Video",
    "VideoType",
    "guest_category_links",
]
