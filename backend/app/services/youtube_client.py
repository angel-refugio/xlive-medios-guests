"""Cliente mínimo de YouTube Data API v3: solo lectura de metadatos de videos.

Cuota: channels.list, playlistItems.list y videos.list cuestan 1 unidad por llamada
(search.list cuesta 100, por eso no se usa).
"""
import logging

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/youtube/v3"
TIMEOUT_SECONDS = 20.0
PAGE_SIZE = 50  # máximo permitido por la API


class YouTubeError(RuntimeError):
    """Fallo al consultar YouTube; el mensaje indica módulo, función y causa."""


def _get(client: httpx.Client, api_key: str, path: str, params: dict, where: str) -> dict:
    """GET a la API. `where` es el nombre de la función llamadora, para los mensajes.

    Nunca se incluye la URL ni la clave en los mensajes de error.
    """
    try:
        response = client.get(
            f"{API_BASE}/{path}", params={**params, "key": api_key}, timeout=TIMEOUT_SECONDS
        )
    except httpx.HTTPError as exc:
        msg = f"[app.services.youtube_client.{where}] Error de red: {type(exc).__name__}"
        logger.error(msg)
        raise YouTubeError(msg) from exc

    if response.status_code != 200:
        try:
            detail = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            detail = "sin detalle"
        msg = f"[app.services.youtube_client.{where}] HTTP {response.status_code}: {detail}"
        logger.error(msg)
        raise YouTubeError(msg)
    return response.json()


def get_uploads_playlist_id(client: httpx.Client, api_key: str, handle: str) -> str:
    """ID de la playlist de subidas del canal identificado por su @handle."""
    data = _get(
        client, api_key, "channels",
        {"part": "contentDetails", "forHandle": handle.lstrip("@")},
        "get_uploads_playlist_id",
    )
    items = data.get("items") or []
    if not items:
        msg = f"[app.services.youtube_client.get_uploads_playlist_id] No se encontró el canal @{handle.lstrip('@')}"
        logger.error(msg)
        raise YouTubeError(msg)
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def list_video_ids(client: httpx.Client, api_key: str, playlist_id: str) -> list[str]:
    """Todos los IDs de video de una playlist (paginando de 50 en 50)."""
    ids: list[str] = []
    page_token = None
    while True:
        params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token
        data = _get(client, api_key, "playlistItems", params, "list_video_ids")
        ids.extend(item["contentDetails"]["videoId"] for item in data.get("items", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            return ids


def get_video_details(client: httpx.Client, api_key: str, video_ids: list[str]) -> list[dict]:
    """Metadatos de los videos pedidos. Los privados o borrados simplemente no vienen."""
    videos: list[dict] = []
    for start in range(0, len(video_ids), PAGE_SIZE):
        chunk = video_ids[start:start + PAGE_SIZE]
        data = _get(
            client, api_key, "videos",
            {"part": "snippet,contentDetails", "id": ",".join(chunk)},
            "get_video_details",
        )
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            videos.append({
                "id": item["id"],
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": snippet.get("publishedAt"),
                "duration": item.get("contentDetails", {}).get("duration"),
                "tags": snippet.get("tags", []),
            })
    return videos
