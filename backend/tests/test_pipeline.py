"""Pruebas del orquestador (Fase 3, paso 6). Sin red ni Ollama reales."""
import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from app.models.ingestion import IngestionRunError, StagingContactCandidate, StagingGuestCandidate
from app.models.video import Video
from app.services import pipeline

MINIMAL_ANALYSIS = {
    "no_guests_opinion": False, "guests": [], "contacts": [],
    "video_type_match": None, "event_borough_match": None,
    "host_match": None, "program_match": None,
}


def _analysis_json(**overrides) -> str:
    return json.dumps(dict(MINIMAL_ANALYSIS, **overrides))


def _ollama_client(default_response: str, by_title: dict[str, str | Exception] | None = None):
    """Cliente de Ollama simulado; `by_title` permite una respuesta distinta por video."""
    by_title = by_title or {}
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        prompt = payload["prompt"]
        for substring, resp in by_title.items():
            if substring in prompt:
                if isinstance(resp, Exception):
                    raise resp
                return httpx.Response(200, json={"response": resp})
        return httpx.Response(200, json={"response": default_response})

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def _video(yt_id="abc123", **kw):
    kw.setdefault("title", "Título")
    kw.setdefault("published_at", datetime(2024, 1, 1, tzinfo=timezone.utc))
    return Video(youtube_video_id=yt_id, source="youtube", **kw)


# --- process_video ----------------------------------------------------------------

def test_process_video_crea_candidatos_de_regex_y_llm(session):
    video = _video(title="con Karimm Kury", description="FACEBOOK: /XLiveMedios")
    session.add(video)
    session.commit()

    llm_response = _analysis_json(guests=[{
        "name": "Otro Invitado", "found_in_title": False, "found_in_description": True,
        "is_possible_group": False, "category_match": None, "category_is_new_suggestion": False,
        "raw_confidence": 0.5, "evidence": "algo",
    }], contacts=[{"type_hint": "sponsor", "value": "Marca X", "raw_confidence": 0.2}])
    client, calls = _ollama_client(llm_response)
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    guest_candidates = session.scalars(select(StagingGuestCandidate)).all()
    assert {c.extracted_name for c in guest_candidates} == {"Karimm Kury", "Otro Invitado"}
    by_name = {c.extracted_name: c for c in guest_candidates}
    assert by_name["Karimm Kury"].extraction_method == "regex"
    assert by_name["Otro Invitado"].extraction_method == "llm"

    contact_candidates = session.scalars(select(StagingContactCandidate)).all()
    assert {c.type_hint for c in contact_candidates} == {"facebook", "sponsor"}
    by_type = {c.type_hint: c for c in contact_candidates}
    assert by_type["facebook"].extraction_method == "regex"
    assert by_type["sponsor"].extraction_method == "llm"


def test_process_video_omite_si_ya_procesado(session):
    video = _video(last_ingested_at=datetime.now(timezone.utc))
    session.add(video)
    session.commit()

    client, calls = _ollama_client(_analysis_json())
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    assert calls == []  # ni siquiera llamó al LLM
    assert session.scalars(select(StagingGuestCandidate)).all() == []


def test_process_video_marca_sin_invitados(session):
    video = _video(title="Resumen semanal", description="")
    session.add(video)
    session.commit()

    client, _ = _ollama_client(_analysis_json())
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    assert video.guest_status == "no_guests"


def test_process_video_no_marca_sin_invitados_si_hay_nombre(session):
    video = _video(title="con Karimm Kury", description="")
    session.add(video)
    session.commit()

    client, _ = _ollama_client(_analysis_json())
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    assert video.guest_status == "pending"


def test_process_video_marca_last_ingested_at(session):
    video = _video()
    session.add(video)
    session.commit()

    client, _ = _ollama_client(_analysis_json())
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    assert video.last_ingested_at is not None


def test_process_video_marca_posible_duplicado_dentro_de_la_ventana(session):
    original = _video("orig", title="Mismo Titulo", description="Misma descripcion",
                       published_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    nuevo = _video("nuevo", title="MISMO TITULO", description="misma descripcion",
                    published_at=datetime(2024, 1, 5, tzinfo=timezone.utc))
    session.add_all([original, nuevo])
    session.commit()

    client, _ = _ollama_client(_analysis_json())
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", nuevo)

    assert nuevo.possible_duplicate_of_video_id == original.id


def test_process_video_no_marca_duplicado_fuera_de_la_ventana(session):
    original = _video("orig", title="Mismo Titulo", description="Misma descripcion",
                       published_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    nuevo = _video("nuevo", title="Mismo Titulo", description="Misma descripcion",
                    published_at=datetime(2024, 3, 1, tzinfo=timezone.utc))
    session.add_all([original, nuevo])
    session.commit()

    client, _ = _ollama_client(_analysis_json())
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", nuevo)

    assert nuevo.possible_duplicate_of_video_id is None


def test_adjust_confidence_bonos_y_penalizacion():
    assert pipeline._adjust_confidence(0.5, True, True, False) == pytest.approx(0.65)
    assert pipeline._adjust_confidence(0.5, True, False, False) == pytest.approx(0.6)
    assert pipeline._adjust_confidence(0.5, False, True, False) == pytest.approx(0.5)
    assert pipeline._adjust_confidence(0.9, True, True, True) == pytest.approx(0.85)
    assert pipeline._adjust_confidence(0.95, True, True, False) == pytest.approx(1.0)  # tope


# --- run_batch ----------------------------------------------------------------------

def _youtube_client(video_ids: list[str], video_data: dict[str, dict] | None = None):
    video_data = video_data or {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = request.url.params
        if path.endswith("/channels"):
            if not video_ids and not video_data:
                return httpx.Response(200, json={"items": []})
            return httpx.Response(200, json={"items": [
                {"contentDetails": {"relatedPlaylists": {"uploads": "UUabc"}}}
            ]})
        if path.endswith("/playlistItems"):
            return httpx.Response(200, json={
                "items": [{"contentDetails": {"videoId": i}} for i in video_ids]
            })
        if path.endswith("/videos"):
            items = []
            for vid in params["id"].split(","):
                data = video_data.get(vid, {})
                items.append({
                    "id": vid,
                    "snippet": {
                        "title": data.get("title", f"Título {vid}"),
                        "description": data.get("description", ""),
                        "publishedAt": data.get("published_at", "2024-01-01T00:00:00Z"),
                    },
                    "contentDetails": {"duration": "PT5M"},
                })
            return httpx.Response(200, json={"items": items})
        return httpx.Response(404, json={"error": {"message": "ruta desconocida"}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_run_batch_procesa_videos_y_completa_la_corrida(session):
    yt = _youtube_client(["v1", "v2"])
    ollama, _ = _ollama_client(_analysis_json())
    with yt, ollama:
        run = pipeline.run_batch(session, yt, "k", ollama, "http://x", "qwen2.5:3b", "xlivemedios", batch_size=5)

    assert run.status == "completed"
    assert run.success_count == 2
    assert run.processed_count == 2
    assert run.error_count == 0
    videos = session.scalars(select(Video)).all()
    assert {v.youtube_video_id for v in videos} == {"v1", "v2"}
    assert all(v.last_ingested_at is not None for v in videos)


def test_run_batch_respeta_batch_size(session):
    yt = _youtube_client(["v1", "v2", "v3"])
    ollama, _ = _ollama_client(_analysis_json())
    with yt, ollama:
        run = pipeline.run_batch(session, yt, "k", ollama, "http://x", "qwen2.5:3b", "xlivemedios", batch_size=2)

    assert run.processed_count == 2
    assert len(session.scalars(select(Video)).all()) == 2


def test_run_batch_omite_videos_ya_procesados(session):
    ya_procesado = _video("v1", last_ingested_at=datetime.now(timezone.utc))
    session.add(ya_procesado)
    session.commit()

    yt = _youtube_client(["v1", "v2"])
    ollama, calls = _ollama_client(_analysis_json())
    with yt, ollama:
        run = pipeline.run_batch(session, yt, "k", ollama, "http://x", "qwen2.5:3b", "xlivemedios", batch_size=5)

    assert run.processed_count == 1  # solo v2
    assert len(calls) == 1
    assert "Título v2" in calls[0]["prompt"]


def test_run_batch_registra_error_por_video_sin_detener_el_lote(session):
    yt = _youtube_client(["v1", "v2"], {
        "v1": {"title": "VideoConError"}, "v2": {"title": "VideoOk"},
    })
    ollama, _ = _ollama_client(
        _analysis_json(),
        by_title={"VideoConError": "esto no es json"},
    )
    with yt, ollama:
        run = pipeline.run_batch(session, yt, "k", ollama, "http://x", "qwen2.5:3b", "xlivemedios", batch_size=5)

    assert run.status == "completed"
    assert run.success_count == 1
    assert run.error_count == 1
    assert run.processed_count == 2

    errors = session.scalars(select(IngestionRunError)).all()
    assert len(errors) == 1
    assert errors[0].youtube_video_id == "v1"

    ok_video = session.scalars(select(Video).where(Video.youtube_video_id == "v2")).one()
    assert ok_video.last_ingested_at is not None
    failed_video = session.scalars(select(Video).where(Video.youtube_video_id == "v1")).one()
    assert failed_video.last_ingested_at is None


def test_run_batch_falla_completa_si_youtube_falla(session):
    yt = _youtube_client([])  # canal "inexistente": /channels responde sin items
    ollama, _ = _ollama_client(_analysis_json())
    with yt, ollama:
        run = pipeline.run_batch(session, yt, "k", ollama, "http://x", "qwen2.5:3b", "noexiste", batch_size=5)

    assert run.status == "failed"
    errors = session.scalars(select(IngestionRunError)).all()
    assert len(errors) == 1
    assert errors[0].youtube_video_id == "(canal)"
