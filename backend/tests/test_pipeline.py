"""Pruebas del orquestador (Fase 3, paso 6). Sin red ni Ollama reales."""
import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from app.models.ingestion import IngestionRun, IngestionRunError, StagingContactCandidate, StagingGuestCandidate
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

CLASSIFIER_MARK = "Nombres candidatos"  # aparece solo en el prompt del clasificador (etapa 2)
SIMPLE_MARK = "INVITADOS al programa"  # aparece solo en el prompt simple de la segunda opinión


def _verdicts_json(*pairs: tuple[str, str]) -> str:
    return json.dumps({"verdicts": [{"name": n, "role": r} for n, r in pairs]})


def _llm_guest(name: str, **overrides) -> dict:
    return dict({
        "name": name, "found_in_title": True, "found_in_description": False,
        "is_possible_group": False, "category_match": None, "category_is_new_suggestion": False,
        "raw_confidence": 0.5, "evidence": "algo",
    }, **overrides)


def test_process_video_crea_candidatos_de_reglas_y_contactos(session):
    video = _video(title="Programa Nuevo: Ana Lopez", description="FACEBOOK: /XLiveMedios")
    session.add(video)
    session.commit()

    llm_response = _analysis_json(
        guests=[_llm_guest("Ana Lopez", category_match="Música", is_possible_group=True)],
        contacts=[{"type_hint": "sponsor", "value": "Marca X", "raw_confidence": 0.2}],
    )
    client, calls = _ollama_client(llm_response, {CLASSIFIER_MARK: _verdicts_json()})
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    guest = session.scalars(select(StagingGuestCandidate)).one()
    assert guest.extracted_name == "Ana Lopez"
    assert guest.extraction_method == "regex"          # sale de las reglas, el LLM solo filtra
    assert guest.raw_confidence == pytest.approx(0.35)  # el valor que ya existía para "after_colon"
    assert guest.found_in_title and not guest.found_in_description
    assert guest.category_match == "Música" and guest.is_possible_group  # copiados del análisis
    assert len(calls) == 2  # análisis + clasificador (había un candidato dudoso)

    contact_candidates = session.scalars(select(StagingContactCandidate)).all()
    assert {c.type_hint for c in contact_candidates} == {"facebook", "sponsor"}
    by_type = {c.type_hint: c for c in contact_candidates}
    assert by_type["facebook"].extraction_method == "regex"
    assert by_type["sponsor"].extraction_method == "llm"


def test_process_video_ignora_invitados_del_llm_y_no_toma_al_conductor_como_invitado(session):
    video = _video(title="Revista Penthouse con Karimm Kury", description="")
    session.add(video)
    session.commit()

    client, calls = _ollama_client(_analysis_json(guests=[_llm_guest("Otro Invitado")]))
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    assert session.scalars(select(StagingGuestCandidate)).all() == []
    # Análisis + segunda opinión (las reglas no hallaron invitados); sin dudosos no hay clasificador.
    assert len(calls) == 2
    assert SIMPLE_MARK in calls[1]["prompt"]


def test_process_video_el_llm_descarta_lo_que_no_es_persona(session):
    video = _video(title="Programa Nuevo: Novedades", description="")
    session.add(video)
    session.commit()

    client, calls = _ollama_client(
        _analysis_json(), {CLASSIFIER_MARK: _verdicts_json(("Novedades", "topic"))},
    )
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    assert session.scalars(select(StagingGuestCandidate)).all() == []
    assert video.last_ingested_at is not None


def test_process_video_si_el_clasificador_falla_conserva_los_candidatos(session):
    video = _video(title="Programa Nuevo: Ana Lopez", description="")
    session.add(video)
    session.commit()

    client, _ = _ollama_client(_analysis_json(), {CLASSIFIER_MARK: "esto no es json"})
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    assert [c.extracted_name for c in session.scalars(select(StagingGuestCandidate))] == ["Ana Lopez"]
    assert video.last_ingested_at is not None


def test_process_video_usa_los_conductores_de_la_serie_guardados_en_la_bd(session):
    # Tres videos de la serie ya sincronizados repiten #ConductorFijo: es conductor, no invitado.
    previos = [
        _video(f"prev{i}", title=f"Serie Z: Invitado {i}", description="#ConductorFijo")
        for i in range(3)
    ]
    nuevo = _video("nuevo", title="Serie Z: Conductor Fijo", description="")
    session.add_all([*previos, nuevo])
    session.commit()

    client, calls = _ollama_client(_analysis_json())
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", nuevo)

    assert session.scalars(select(StagingGuestCandidate)).all() == []
    assert len(calls) == 2  # análisis + segunda opinión
    assert not any(CLASSIFIER_MARK in c["prompt"] for c in calls)  # ningún dudoso: sin clasificador


def test_process_video_usa_el_catalogo_de_programas(session):
    from app.models.catalogs import Program

    session.add(Program(name="Rock and Rul"))
    video = _video(title="ROCK AND RUL: LOS OVNIS", description="#LOSOVNIS")
    session.add(video)
    session.commit()

    client, _ = _ollama_client(_analysis_json(), {CLASSIFIER_MARK: _verdicts_json(("LOS OVNIS", "topic"))})
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    # El LLM dijo "topic", pero el nombre también está en la descripción: el invitado se conserva.
    assert [c.extracted_name for c in session.scalars(select(StagingGuestCandidate))] == ["LOS OVNIS"]


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


def test_process_video_marca_duplicado_con_emoji_de_mas_en_el_titulo(session):
    # Caso real (primera corrida contra el canal): el mismo video subido dos veces, la única
    # diferencia es un emoji al final del título; misma descripción, segundos de diferencia.
    original = _video("orig", title="Con las Estrellas Arween Tarot", description="Misma bio",
                       published_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc))
    nuevo = _video("nuevo", title="Con las Estrellas Arween Tarot 📱", description="Misma bio",
                    published_at=datetime(2024, 1, 1, 12, 0, 8, tzinfo=timezone.utc))
    session.add_all([original, nuevo])
    session.commit()

    client, _ = _ollama_client(_analysis_json())
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", nuevo)

    assert nuevo.possible_duplicate_of_video_id == original.id


def test_normalize_for_duplicate_check_quita_emoji():
    assert (
        pipeline._normalize_for_duplicate_check("Con las Estrellas Arween Tarot 📱")
        == pipeline._normalize_for_duplicate_check("Con las Estrellas Arween Tarot")
    )


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
    assert len(calls) == 2  # análisis + segunda opinión, los dos de v2
    assert all("Título v2" in c["prompt"] for c in calls)


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


# --- trigger_manual_run (botón "Ingesta") -------------------------------------------

def test_trigger_manual_run_falta_youtube_api_key(session, monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
    with pytest.raises(RuntimeError, match="YOUTUBE_API_KEY"):
        pipeline.trigger_manual_run(session)


def test_trigger_manual_run_falta_ollama_model(session, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "clave")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="OLLAMA_MODEL"):
        pipeline.trigger_manual_run(session)


def test_trigger_manual_run_llama_a_run_batch_con_los_parametros_correctos(session, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "clave")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
    captured = {}

    def fake_run_batch(db, yt_client, api_key, ollama_client, base_url, model, handle, batch_size, trigger):
        captured.update(
            db=db, yt_client=yt_client, api_key=api_key, ollama_client=ollama_client,
            base_url=base_url, model=model, handle=handle, batch_size=batch_size, trigger=trigger,
        )
        return IngestionRun(status="completed")

    monkeypatch.setattr(pipeline, "run_batch", fake_run_batch)
    result = pipeline.trigger_manual_run(session, batch_size=5)

    assert captured["handle"] == pipeline.CHANNEL_HANDLE
    assert captured["batch_size"] == 5
    assert captured["trigger"] == "manual"
    assert captured["api_key"] == "clave"
    assert captured["model"] == "qwen2.5:3b"
    assert isinstance(captured["yt_client"], httpx.Client)
    assert isinstance(captured["ollama_client"], httpx.Client)
    assert result.status == "completed"


def test_trigger_manual_run_usa_el_lote_por_defecto_si_no_se_indica(session, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "clave")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
    captured = {}

    def fake_run_batch(db, yt, api_key, ollama, base_url, model, handle, batch_size, trigger):
        captured["batch_size"] = batch_size
        return IngestionRun(status="completed")

    monkeypatch.setattr(pipeline, "run_batch", fake_run_batch)
    pipeline.trigger_manual_run(session)
    assert captured["batch_size"] == pipeline.DEFAULT_BATCH_SIZE


def test_run_batch_calcula_los_perfiles_una_sola_vez_por_lote(session, monkeypatch):
    llamadas = []
    original = pipeline._build_series

    def contando(db):
        llamadas.append(1)
        return original(db)

    monkeypatch.setattr(pipeline, "_build_series", contando)
    yt = _youtube_client(["v1", "v2"])
    ollama, _ = _ollama_client(_analysis_json())
    with yt, ollama:
        run = pipeline.run_batch(session, yt, "k", ollama, "http://x", "qwen2.5:3b", "xlivemedios", batch_size=5)

    assert run.processed_count == 2
    assert len(llamadas) == 1


# --- sugerencia de programa y conductores ---------------------------------------------

def _suggestions(session):
    from app.models.ingestion import StagingVideoSuggestion
    return session.scalars(select(StagingVideoSuggestion)).all()


def test_process_video_guarda_el_programa_del_catalogo_y_los_conductores_como_sugerencia(session):
    from app.models.catalogs import Program

    session.add(Program(name="Revista Penthouse Television"))
    video = _video(title="Revista Penthouse Television con Karimm Kury", description="")
    session.add(video)
    session.commit()

    client, _ = _ollama_client(_analysis_json())
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    (suggestion,) = _suggestions(session)
    assert suggestion.video_id == video.id
    assert suggestion.program_name == "Revista Penthouse Television"
    assert suggestion.host_names == ["Karimm Kury"]
    assert suggestion.status == "pending"


def test_process_video_no_crea_sugerencia_si_no_hay_programa_ni_conductores(session):
    video = _video(title="Título", description="")
    session.add(video)
    session.commit()

    client, _ = _ollama_client(_analysis_json())
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    assert _suggestions(session) == []


def test_process_video_nunca_inventa_un_programa_fuera_del_catalogo(session):
    video = _video(title="Programa Nuevo: Ana Lopez", description="")
    session.add(video)
    session.commit()

    client, _ = _ollama_client(_analysis_json(), {CLASSIFIER_MARK: _verdicts_json()})
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    assert _suggestions(session) == []  # sin catálogo no hay programa que sugerir


def test_save_video_suggestion_es_idempotente(session):
    from app.services import series_profile

    video = _video()
    session.add(video)
    session.commit()
    hints = series_profile.VideoHints(program="", hosts=[series_profile.NameHint("Dante", "host", "title_con")])
    assert pipeline._save_video_suggestion(session, video, None, hints) is True
    session.commit()
    assert pipeline._save_video_suggestion(session, video, None, hints) is False
    assert len(_suggestions(session)) == 1


def test_backfill_crea_sugerencias_solo_para_videos_ya_ingeridos_y_es_idempotente(session):
    from app.models.catalogs import Program

    session.add(Program(name="Revista Penthouse Television"))
    ingerido = _video("ing", title="Revista Penthouse Television con Karimm Kury",
                      last_ingested_at=datetime.now(timezone.utc))
    pendiente = _video("pen", title="Revista Penthouse Television con Karimm Kury")
    sin_nada = _video("nada", title="Título", last_ingested_at=datetime.now(timezone.utc))
    session.add_all([ingerido, pendiente, sin_nada])
    session.commit()

    assert pipeline.backfill_video_suggestions(session) == 1
    (suggestion,) = _suggestions(session)
    assert suggestion.video_id == ingerido.id and suggestion.host_names == ["Karimm Kury"]
    assert pipeline.backfill_video_suggestions(session) == 0


# --- dudosos, conductores habituales y reprocesamiento ---------------------------------

def _serie_z_con_conductor_fijo(session, n=3):
    """n videos ya sincronizados de "Serie Z" que repiten #ConductorFijo (es su conductor)."""
    session.add_all([
        _video(f"prev{i}", title=f"Serie Z: Invitado {i}", description="#ConductorFijo")
        for i in range(n)
    ])


def test_process_video_guarda_dudosos_con_la_pista_del_llm_y_los_conductores_habituales(session):
    _serie_z_con_conductor_fijo(session)
    nuevo = _video("nuevo", title="Serie Z: Ana Lopez", description="#Frankgogo\n#cuidados")
    session.add(nuevo)
    session.commit()

    client, _ = _ollama_client(_analysis_json(), {CLASSIFIER_MARK: _verdicts_json(
        ("Ana Lopez", "guest"), ("Frankgogo", "guest"), ("cuidados", "topic"),
    )})
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", nuevo)

    suggestion = next(s for s in _suggestions(session) if s.video_id == nuevo.id)
    assert suggestion.doubtful_names == [{"name": "Frankgogo", "guess": "guest"}]  # "cuidados" es ruido
    assert suggestion.usual_host_names == ["Conductor Fijo"]  # el texto no lo menciona: se ofrece
    assert suggestion.host_names == []
    # El dudoso NO se vuelve invitado solo: queda para que lo decida el humano.
    guests = session.scalars(select(StagingGuestCandidate).where(StagingGuestCandidate.video_id == nuevo.id)).all()
    assert [g.extracted_name for g in guests] == ["Ana Lopez"]


def test_los_conductores_habituales_no_repiten_a_los_que_el_texto_ya_menciona(session):
    _serie_z_con_conductor_fijo(session)
    nuevo = _video("nuevo", title="Serie Z: Ana Lopez conduce Conductor Fijo", description="")
    session.add(nuevo)
    session.commit()

    client, _ = _ollama_client(_analysis_json(), {CLASSIFIER_MARK: _verdicts_json()})
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", nuevo)

    suggestion = next(s for s in _suggestions(session) if s.video_id == nuevo.id)
    assert suggestion.host_names == ["Conductor Fijo"]
    assert suggestion.usual_host_names == []


def test_backfill_completa_las_sugerencias_pendientes_sin_dudosos_ni_habituales(session):
    from app.models.ingestion import StagingVideoSuggestion

    _serie_z_con_conductor_fijo(session)
    ingerido = _video("ing", title="Serie Z: Ana Lopez", description="#Frankgogo",
                      last_ingested_at=datetime.now(timezone.utc))
    session.add(ingerido)
    session.commit()
    session.add(StagingVideoSuggestion(video_id=ingerido.id, host_names=[]))
    session.commit()

    assert pipeline.backfill_video_suggestions(session) == 1
    suggestion = session.scalars(select(StagingVideoSuggestion)).one()
    assert suggestion.doubtful_names == [{"name": "Frankgogo", "guess": "unknown"}]
    assert suggestion.usual_host_names == ["Conductor Fijo"]
    assert pipeline.backfill_video_suggestions(session) == 0  # idempotente


def test_backfill_no_toca_las_sugerencias_ya_revisadas(session):
    from app.models.ingestion import StagingVideoSuggestion

    _serie_z_con_conductor_fijo(session)
    ingerido = _video("ing", title="Serie Z: Ana Lopez", description="#Frankgogo",
                      last_ingested_at=datetime.now(timezone.utc))
    session.add(ingerido)
    session.commit()
    session.add(StagingVideoSuggestion(video_id=ingerido.id, host_names=[], status="accepted"))
    session.commit()

    assert pipeline.backfill_video_suggestions(session) == 0
    assert session.scalars(select(StagingVideoSuggestion)).one().doubtful_names == []


def _stale_candidate(video_id, status="pending"):
    return StagingGuestCandidate(
        video_id=video_id, extracted_name="Viejo", found_in_title=True, found_in_description=False,
        raw_confidence=0.3, adjusted_confidence=0.3, evidence="Viejo", extraction_method="regex",
        status=status,
    )


def test_reprocess_en_simulacion_solo_lista_los_videos_sin_revisar(session):
    video = _video(title="Programa Nuevo: Ana Lopez", last_ingested_at=datetime.now(timezone.utc))
    session.add(video)
    session.commit()
    session.add(_stale_candidate(video.id))
    session.commit()

    client, calls = _ollama_client(_analysis_json())
    with client:
        result = pipeline.reprocess_unreviewed_videos(session, client, "http://x", "m", dry_run=True)

    assert result == {"videos": [video.youtube_video_id], "reprocessed": 0, "errors": []}
    assert calls == []
    assert [c.extracted_name for c in session.scalars(select(StagingGuestCandidate))] == ["Viejo"]


def test_reprocess_rehace_los_candidatos_pendientes_con_el_extractor_actual(session):
    video = _video(title="Programa Nuevo: Ana Lopez", last_ingested_at=datetime.now(timezone.utc))
    session.add(video)
    session.commit()
    session.add(_stale_candidate(video.id))
    session.commit()

    client, _ = _ollama_client(_analysis_json(), {CLASSIFIER_MARK: _verdicts_json()})
    with client:
        result = pipeline.reprocess_unreviewed_videos(session, client, "http://x", "m", dry_run=False)

    assert result["reprocessed"] == 1 and result["errors"] == []
    assert [c.extracted_name for c in session.scalars(select(StagingGuestCandidate))] == ["Ana Lopez"]
    assert video.last_ingested_at is not None


def test_reprocess_no_toca_lo_que_una_persona_ya_reviso(session):
    from app.models.catalogs import Program

    program = Program(name="Programa Nuevo")
    session.add(program)
    aceptado = _video("a", title="Programa Nuevo: Ana", last_ingested_at=datetime.now(timezone.utc))
    rechazado = _video("r", title="Programa Nuevo: Luis", last_ingested_at=datetime.now(timezone.utc))
    sin_invitados = _video("s", title="Programa Nuevo: Sin", last_ingested_at=datetime.now(timezone.utc),
                           guest_status="no_guests")
    con_programa = _video("p", title="Programa Nuevo: Pro", last_ingested_at=datetime.now(timezone.utc))
    session.add_all([aceptado, rechazado, sin_invitados, con_programa])
    session.commit()
    con_programa.program_id = program.id
    session.add_all([
        _stale_candidate(aceptado.id, "accepted"), _stale_candidate(rechazado.id, "rejected"),
        _stale_candidate(sin_invitados.id), _stale_candidate(con_programa.id),
    ])
    session.commit()

    client, calls = _ollama_client(_analysis_json())
    with client:
        result = pipeline.reprocess_unreviewed_videos(session, client, "http://x", "m", dry_run=False)

    assert result == {"videos": [], "reprocessed": 0, "errors": []}
    assert calls == []
    assert len(session.scalars(select(StagingGuestCandidate)).all()) == 4


def test_reprocess_un_error_no_detiene_a_los_demas(session):
    malo = _video("malo", title="VideoConError: x", last_ingested_at=datetime.now(timezone.utc))
    bueno = _video("bueno", title="Programa Nuevo: Ana Lopez", last_ingested_at=datetime.now(timezone.utc))
    session.add_all([malo, bueno])
    session.commit()

    client, _ = _ollama_client(_analysis_json(), {"VideoConError": "esto no es json", CLASSIFIER_MARK: _verdicts_json()})
    with client:
        result = pipeline.reprocess_unreviewed_videos(session, client, "http://x", "m", dry_run=False)

    assert result["reprocessed"] == 1
    assert [e["video"] for e in result["errors"]] == ["malo"]


# --- segunda opinión del LLM (prompt simple, modo fallback) --------------------------------

def _simple_json(*names: str) -> str:
    return json.dumps({"invitados": list(names)})


def _llm_candidates(session, video):
    return session.scalars(select(StagingGuestCandidate).where(
        StagingGuestCandidate.video_id == video.id, StagingGuestCandidate.extraction_method == "llm",
    )).all()


def test_segunda_opinion_agrega_invitados_del_llm_si_las_reglas_no_encontraron_a_nadie(session):
    video = _video(title="El Mechero Del Abuelo", description="Hoy nos visita EMECE MILLA, no te lo pierdas")
    session.add(video)
    session.commit()

    client, calls = _ollama_client(
        _analysis_json(), {SIMPLE_MARK: _simple_json("Emece Milla", "Nombre Inventado")},
    )
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    (candidate,) = _llm_candidates(session, video)
    assert candidate.extracted_name == "Emece Milla"  # "Nombre Inventado" no está en el texto
    assert candidate.raw_confidence == pytest.approx(0.30)  # el valor más bajo que ya existía
    assert candidate.found_in_description and not candidate.found_in_title
    assert candidate.status == "pending"
    assert len(calls) == 2


def test_segunda_opinion_no_se_pide_si_las_reglas_ya_encontraron_invitados(session):
    video = _video(title="Programa Nuevo: Ana Lopez", description="")
    session.add(video)
    session.commit()

    client, calls = _ollama_client(
        _analysis_json(), {CLASSIFIER_MARK: _verdicts_json(), SIMPLE_MARK: _simple_json("Otra Persona")},
    )
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    assert not any(SIMPLE_MARK in c["prompt"] for c in calls)
    assert _llm_candidates(session, video) == []


def test_segunda_opinion_excluye_programas_y_conductores_del_catalogo(session):
    from app.models.catalogs import Host, Program

    session.add_all([Program(name="El Mechero del Abuelo"), Host(name="MC Luka")])
    video = _video(title="El Mechero Del Abuelo", description="El Mechero Del Abuelo con MC Luka y EMECE MILLA")
    session.add(video)
    session.commit()

    client, _ = _ollama_client(_analysis_json(), {
        SIMPLE_MARK: _simple_json("El Mechero Del Abuelo", "MC Luka", "EMECE MILLA"),
    })
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    assert [c.extracted_name for c in _llm_candidates(session, video)] == ["EMECE MILLA"]


def test_si_falla_la_segunda_opinion_el_video_se_procesa_igual(session):
    video = _video(title="El Mechero Del Abuelo", description="Hoy nos visita EMECE MILLA")
    session.add(video)
    session.commit()

    client, _ = _ollama_client(_analysis_json(), {SIMPLE_MARK: "esto no es json"})
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    assert _llm_candidates(session, video) == []
    assert video.last_ingested_at is not None


def test_lo_que_el_llm_propone_como_invitado_deja_de_ser_dudoso(session):
    from app.models.ingestion import StagingVideoSuggestion

    video = _video(title="Noches de Sensualite", description="#Lisa\n#Jordi")
    session.add(video)
    session.commit()

    client, _ = _ollama_client(_analysis_json(), {SIMPLE_MARK: _simple_json("Lisa")})
    with client:
        pipeline.process_video(session, client, "http://x", "qwen2.5:3b", video)

    assert [c.extracted_name for c in _llm_candidates(session, video)] == ["Lisa"]
    suggestion = session.scalars(select(StagingVideoSuggestion)).one()
    assert suggestion.doubtful_names == [{"name": "Jordi", "guess": "unknown"}]
