"""Pruebas del sync de videos de YouTube a la BD (Fase 3, paso 3). Sin red real."""
from datetime import datetime

import httpx
import pytest
from sqlalchemy import select

from app.models.guest import Guest
from app.models.participation import Participation
from app.models.video import Video
from app.services import ingestion


def _count_videos(session) -> int:
    return len(session.scalars(select(Video)).all())

RAW_VIDEO = {
    "id": "abc123",
    "title": "Título",
    "description": "Descripción",
    "published_at": "2024-01-01T00:00:00Z",
    "duration": "PT10M",
    "tags": ["x"],
    "channel_id": "UCabc",
    "channel_title": "X Live Medios",
    "thumbnail_url": "http://x/high.jpg",
}


def fake_youtube(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/videos"):
        ids = request.url.params["id"].split(",")
        return httpx.Response(200, json={"items": [
            {
                "id": i,
                "snippet": {
                    "title": f"Título {i}", "description": f"Desc {i}",
                    "publishedAt": "2024-01-01T00:00:00Z",
                    "channelId": "UCabc", "channelTitle": "X Live Medios",
                },
                "contentDetails": {"duration": "PT5M"},
            }
            for i in ids
        ]})
    return httpx.Response(404, json={"error": {"message": "ruta desconocida"}})


@pytest.fixture
def client():
    with httpx.Client(transport=httpx.MockTransport(fake_youtube)) as c:
        yield c


# --- upsert_video -------------------------------------------------------------

def test_upsert_video_crea_nuevo(session):
    result = ingestion.upsert_video(session, RAW_VIDEO)
    session.commit()
    assert result.created is True
    assert result.replaced_manual is False
    assert result.video.source == "youtube"
    assert result.video.youtube_video_id == "abc123"
    assert result.video.duration_seconds == 600
    assert result.video.channel_title == "X Live Medios"
    # SQLite (motor de pruebas) no conserva tzinfo en DateTime(timezone=True) y regresa un
    # datetime naive; PostgreSQL (producción) sí la preserva. Se compara sin tzinfo para que
    # la prueba valga en ambos casos.
    assert result.video.published_at.replace(tzinfo=None) == datetime(2024, 1, 1)


def test_upsert_video_fecha_invalida_da_error_claro(session):
    with pytest.raises(ValueError, match="_parse_timestamp"):
        ingestion.upsert_video(session, dict(RAW_VIDEO, published_at="no es fecha"))


def test_upsert_video_actualiza_video_youtube_existente(session):
    ingestion.upsert_video(session, RAW_VIDEO)
    session.commit()

    updated = dict(RAW_VIDEO, title="Título nuevo")
    result = ingestion.upsert_video(session, updated)
    session.commit()

    assert result.created is False
    assert result.replaced_manual is False
    assert result.video.title == "Título nuevo"
    assert _count_videos(session) == 1  # no duplica


def test_upsert_video_reemplaza_manual_y_conserva_relaciones(session):
    manual = Video(youtube_video_id="abc123", title="Cargado a mano", source="manual")
    guest = Guest(full_name="Invitado")
    session.add_all([manual, guest])
    session.commit()
    session.add(Participation(guest_id=guest.id, video_id=manual.id))
    session.commit()

    result = ingestion.upsert_video(session, RAW_VIDEO)
    session.commit()

    assert result.created is False
    assert result.replaced_manual is True
    assert result.video.id == manual.id  # mismo registro, no uno nuevo
    assert result.video.source == "youtube"
    assert result.video.title == "Título"
    # La participación capturada a mano sigue intacta.
    assert len(guest.participations) == 1


# --- sync_videos / sync_channel -------------------------------------------------

def test_sync_videos_guarda_y_comitea(session, client):
    results = ingestion.sync_videos(session, client, "k", ["v1", "v2"])
    assert len(results) == 2
    assert {r.video.youtube_video_id for r in results} == {"v1", "v2"}
    assert _count_videos(session) == 2  # persistido, no solo en memoria


def test_sync_videos_no_duplica_al_reprocesar(session, client):
    ingestion.sync_videos(session, client, "k", ["v1"])
    ingestion.sync_videos(session, client, "k", ["v1"])
    assert _count_videos(session) == 1
