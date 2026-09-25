"""Pruebas del cliente de YouTube y del script de muestreo, con respuestas simuladas."""
import json

import httpx
import pytest

from app.services import youtube_client
from app.services.youtube_client import YouTubeError
from scripts import sample_videos

ALL_IDS = [f"vid{i:03d}" for i in range(75)]


def fake_youtube(request: httpx.Request) -> httpx.Response:
    """Simula channels, playlistItems (2 páginas: 50 + 25) y videos."""
    path = request.url.path
    params = request.url.params
    if path.endswith("/channels"):
        assert params["forHandle"] == "xlivemedios"
        return httpx.Response(200, json={"items": [
            {"contentDetails": {"relatedPlaylists": {"uploads": "UUabc"}}}
        ]})
    if path.endswith("/playlistItems"):
        second = params.get("pageToken") == "p2"
        ids = ALL_IDS[50:] if second else ALL_IDS[:50]
        body = {"items": [{"contentDetails": {"videoId": i}} for i in ids]}
        if not second:
            body["nextPageToken"] = "p2"
        return httpx.Response(200, json=body)
    if path.endswith("/videos"):
        return httpx.Response(200, json={"items": [
            {
                "id": i,
                "snippet": {"title": f"Título {i}", "description": f"Desc {i}",
                            "publishedAt": "2024-01-01T00:00:00Z", "tags": ["x"]},
                "contentDetails": {"duration": "PT10M"},
            }
            for i in params["id"].split(",")
        ]})
    return httpx.Response(404, json={"error": {"message": "ruta desconocida"}})


@pytest.fixture
def client():
    with httpx.Client(transport=httpx.MockTransport(fake_youtube)) as c:
        yield c


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "clave-de-prueba")


def test_list_video_ids_pagina(client):
    assert youtube_client.list_video_ids(client, "k", "UUabc") == ALL_IDS


def test_get_uploads_playlist_id(client):
    assert youtube_client.get_uploads_playlist_id(client, "k", "@xlivemedios") == "UUabc"


def test_canal_inexistente_da_error_claro():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"items": []}))
    with httpx.Client(transport=transport) as c:
        with pytest.raises(YouTubeError, match="get_uploads_playlist_id"):
            youtube_client.get_uploads_playlist_id(c, "k", "noexiste")


def test_http_error_no_filtra_la_clave():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(403, json={"error": {"message": "cuota agotada"}})
    )
    with httpx.Client(transport=transport) as c:
        with pytest.raises(YouTubeError) as exc:
            youtube_client.get_video_details(c, "clave-secreta", ["a"])
    assert "403" in str(exc.value) and "cuota agotada" in str(exc.value)
    assert "clave-secreta" not in str(exc.value)


def test_get_video_details_parte_en_lotes(client):
    videos = youtube_client.get_video_details(client, "k", ALL_IDS)
    assert [v["id"] for v in videos] == ALL_IDS
    assert videos[0]["title"] == "Título vid000"


def test_pick_ids_reproducible_y_sin_excluidos():
    excluded = set(ALL_IDS[:10])
    a = sample_videos.pick_ids(ALL_IDS, excluded, 30, seed=1)
    assert a == sample_videos.pick_ids(ALL_IDS, excluded, 30, seed=1)
    assert len(a) == 30 and not set(a) & excluded


def test_run_tres_corridas_no_repiten_videos(client, tmp_path):
    seen: set[str] = set()
    for seed in (1, 2, 3):
        path = sample_videos.run("xlivemedios", 25, seed, tmp_path, client)
        ids = {v["id"] for v in json.loads(path.read_text(encoding="utf-8"))["videos"]}
        assert len(ids) == 25 and not ids & seen
        seen |= ids
    assert len(seen) == 75


def test_run_sin_videos_restantes_falla(client, tmp_path):
    sample_videos.run("xlivemedios", 75, 1, tmp_path, client)
    with pytest.raises(RuntimeError, match="No quedan videos"):
        sample_videos.run("xlivemedios", 30, 2, tmp_path, client)


def test_run_sin_api_key_falla(client, tmp_path, monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY")
    with pytest.raises(RuntimeError, match="YOUTUBE_API_KEY"):
        sample_videos.run("xlivemedios", 5, 1, tmp_path, client)


def test_json_ilegible_detiene_la_corrida(client, tmp_path):
    (tmp_path / "sample_roto.json").write_text("{no es json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="sample_roto.json"):
        sample_videos.run("xlivemedios", 5, 1, tmp_path, client)
