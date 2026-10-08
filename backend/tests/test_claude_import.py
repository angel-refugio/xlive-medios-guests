"""Pruebas del importador a staging de lo que extrae Claude (Claude Code o API), sin red."""
import json
import os
import time

import pytest
from sqlalchemy import select

from app.models.catalogs import ContactType, Program
from app.models.ingestion import StagingContactCandidate, StagingGuestCandidate, StagingVideoSuggestion
from app.models.video import Video
from app.schemas.claude_extraction import BatchExtraction, VideoExtraction
from app.services import claude_import as ci
from app.services.claude_import import ClaudeImportError

TITLE = "Rock and Rull: Ana Pérez"
DESCRIPTION = "Invitada Ana Pérez. Contacto: https://instagram.com/ana_perez"


def _video(session, youtube_id="v1", title=TITLE, description=DESCRIPTION):
    video = Video(youtube_video_id=youtube_id, title=title, description=description, source="youtube")
    session.add(video)
    session.flush()
    return video


def _extraction(video_id="v1", **overrides):
    data = {
        "video_id": video_id, "program": "Rock and Rull",
        "guests": [{"name": "Ana Pérez", "confidence": 0.9, "evidence": "Invitada Ana Pérez"}],
        "hosts": [{"name": "Raúl"}], "doubtful": [{"name": "Rul", "reason": "apodo"}],
        "contacts": [{
            "type": "instagram", "value": "https://instagram.com/ana_perez", "relationship": "propio",
            "guest": "Ana Pérez", "evidence": "Contacto: https://instagram.com/ana_perez",
        }],
        "unassigned_contacts": [{"type": "email", "value": "contacto@mail.com", "doubtful": True,
                                 "doubtful_reason": "varios invitados posibles"}],
    }
    data.update(overrides)
    return VideoExtraction.model_validate(data)


def _import(session, video, extraction, version="v5", extractor="claude_code"):
    return ci.import_video(session, video, extraction, extractor=extractor, instructions_version=version)


def _rows(session, model):
    return list(session.scalars(select(model).order_by(model.id)))


# --- invitados y origen -----------------------------------------------------------------

def test_guarda_el_invitado_como_candidato_con_origen_evidencia_y_confianza_ajustada(session):
    video = _video(session)
    result = _import(session, video, _extraction())
    guest = _rows(session, StagingGuestCandidate)[0]
    assert result.guests == 1
    assert (guest.extracted_name, guest.status, guest.extraction_method) == ("Ana Pérez", "pending", "llm")
    assert (guest.extractor, guest.instructions_version) == ("claude_code", "v5")
    assert guest.evidence == "Invitada Ana Pérez" and guest.found_in_title and guest.found_in_description
    assert guest.raw_confidence == 0.9 and guest.raw_confidence < guest.adjusted_confidence <= 1.0


def test_extractor_desconocido_da_error_con_modulo(session):
    with pytest.raises(ClaudeImportError, match=r"claude_import\.import_video.*gemini"):
        _import(session, _video(session), _extraction(), extractor="gemini")


@pytest.mark.parametrize("extractor", ["claude_code", "claude_api"])
def test_los_dos_modos_guardan_su_origen(session, extractor):
    video = _video(session)
    _import(session, video, _extraction(), extractor=extractor)
    assert {r.extractor for r in _rows(session, StagingGuestCandidate)} == {extractor}
    assert {r.extractor for r in _rows(session, StagingContactCandidate)} == {extractor}
    assert _rows(session, StagingVideoSuggestion)[0].extractor == extractor


# --- contactos --------------------------------------------------------------------------

def test_contacto_asignado_se_vincula_al_candidato_de_invitado_con_relacion_y_evidencia(session):
    session.add(ContactType(name="Instagram"))
    video = _video(session)
    result = _import(session, video, _extraction())
    contacts = _rows(session, StagingContactCandidate)
    guest = _rows(session, StagingGuestCandidate)[0]
    assigned = next(c for c in contacts if c.type_hint == "instagram")
    assert assigned.guest_candidate_id == guest.id and assigned.guest_name == "Ana Pérez"
    assert assigned.relationship_name == "propio" and assigned.evidence.startswith("Contacto:")
    assert assigned.normalized_value == "instagram.com/ana_perez" and not assigned.doubtful
    assert (result.contacts, result.unassigned_contacts) == (2, 1)


def test_contacto_sin_asignar_dudoso_conserva_el_motivo_de_claude_y_suma_tipo_no_registrado(session):
    session.add(ContactType(name="Instagram"))      # "email" sin equivalente en el catálogo
    result = _import(session, _video(session), _extraction())
    pending = next(c for c in _rows(session, StagingContactCandidate) if c.type_hint == "email")
    assert pending.guest_candidate_id is None and pending.doubtful
    assert pending.doubtful_reason == "varios invitados posibles; tipo no registrado"
    assert result.doubtful_contacts == 1


def test_tipo_registrado_por_sinonimo_no_es_dudoso(session):
    session.add_all([ContactType(name="Instagram"), ContactType(name="Correo")])
    contact = {"type": "email", "value": "a@mail.com", "guest": "Ana Pérez"}
    _import(session, _video(session), _extraction(contacts=[contact], unassigned_contacts=[]))
    assert not _rows(session, StagingContactCandidate)[0].doubtful


def test_handle_nunca_coincide_con_el_catalogo_y_queda_dudoso(session):
    session.add(ContactType(name="Instagram"))
    contact = {"type": "handle", "value": "@ana_perez", "guest": "Ana Pérez"}
    _import(session, _video(session), _extraction(contacts=[contact], unassigned_contacts=[]))
    row = _rows(session, StagingContactCandidate)[0]
    assert row.doubtful and row.doubtful_reason == "tipo no registrado"


def test_invitado_del_contacto_sin_candidato_queda_dudoso(session):
    session.add(ContactType(name="Instagram"))
    contact = {"type": "instagram", "value": "https://instagram.com/otra", "guest": "Beto Sánchez"}
    _import(session, _video(session), _extraction(contacts=[contact], unassigned_contacts=[]))
    row = _rows(session, StagingContactCandidate)[0]
    assert row.guest_candidate_id is None and row.guest_name == "Beto Sánchez"
    assert row.doubtful and row.doubtful_reason == "invitado sin candidato"


def test_posible_invitado_no_detectado_se_conserva(session):
    contact = {"type": "instagram", "value": "https://instagram.com/otra", "possible_guest": "Beto"}
    _import(session, _video(session), _extraction(contacts=[], unassigned_contacts=[contact]))
    assert _rows(session, StagingContactCandidate)[0].possible_guest_name == "Beto"


def test_contacto_repetido_en_el_mismo_video_se_importa_una_vez(session):
    contact = {"type": "instagram", "value": "https://www.Instagram.com/ana_perez/"}
    extraction = _extraction(contacts=[contact, contact], unassigned_contacts=[])
    _import(session, _video(session), extraction)
    assert len(_rows(session, StagingContactCandidate)) == 1


@pytest.mark.parametrize("version,method", [("v5", "regex"), ("v3", "llm")])
def test_metodo_del_contacto_segun_quien_lo_encontro(session, version, method):
    _import(session, _video(session), _extraction(), version=version)
    assert {c.extraction_method for c in _rows(session, StagingContactCandidate)} == {method}


# --- programa, conductores y dudosos ----------------------------------------------------

def test_programa_del_catalogo_se_asigna_aunque_cambie_la_ortografia(session):
    session.add(Program(name="Rock and Rull"))
    _import(session, _video(session), _extraction(program="rock AND rull"))
    suggestion = _rows(session, StagingVideoSuggestion)[0]
    assert suggestion.program_name == "Rock and Rull" and suggestion.new_program_name is None
    assert suggestion.host_names == ["Raúl"] and suggestion.doubtful_names[0]["name"] == "Rul"


def test_programa_fuera_del_catalogo_queda_como_propuesto_y_nunca_se_asigna(session):
    _import(session, _video(session), _extraction(program="Programa Nuevo"))
    suggestion = _rows(session, StagingVideoSuggestion)[0]
    assert suggestion.program_name is None and suggestion.new_program_name == "Programa Nuevo"


def test_sin_programa_conductores_ni_dudosos_no_se_crea_sugerencia(session):
    extraction = _extraction(program=None, hosts=[], doubtful=[])
    assert _import(session, _video(session), extraction).suggestion is False
    assert not _rows(session, StagingVideoSuggestion)


# --- idempotencia y lo ya revisado ------------------------------------------------------

def test_reimportar_reemplaza_los_pendientes_sin_duplicar(session):
    video = _video(session)
    _import(session, video, _extraction())
    again = _import(session, video, _extraction())
    assert again.replaced_pending == 4          # 1 invitado + 2 contactos + 1 sugerencia
    assert (len(_rows(session, StagingGuestCandidate)), len(_rows(session, StagingContactCandidate)),
            len(_rows(session, StagingVideoSuggestion))) == (1, 2, 1)


def test_un_contacto_rechazado_no_se_vuelve_a_proponer(session):
    video = _video(session)
    _import(session, video, _extraction())
    rejected = next(c for c in _rows(session, StagingContactCandidate) if c.type_hint == "email")
    rejected.status = "rejected"
    session.flush()
    again = _import(session, video, _extraction())
    rows = _rows(session, StagingContactCandidate)
    assert again.skipped_reviewed == 1 and len(rows) == 2
    assert [c.status for c in rows if c.type_hint == "email"] == ["rejected"]


def test_un_invitado_ya_revisado_no_se_duplica(session):
    video = _video(session)
    _import(session, video, _extraction())
    _rows(session, StagingGuestCandidate)[0].status = "accepted"
    session.flush()
    again = _import(session, video, _extraction())
    assert again.guests == 0 and again.skipped_reviewed >= 1
    assert [g.status for g in _rows(session, StagingGuestCandidate)] == ["accepted"]


def test_una_sugerencia_ya_revisada_se_conserva(session):
    video = _video(session)
    _import(session, video, _extraction())
    _rows(session, StagingVideoSuggestion)[0].status = "accepted"
    session.flush()
    again = _import(session, video, _extraction(program="Otro"))
    assert again.suggestion is False
    assert _rows(session, StagingVideoSuggestion)[0].program_name is None  # sigue siendo la revisada


# --- estado del video -------------------------------------------------------------------

def test_sin_invitados_marca_el_video_si_estaba_pendiente(session):
    video = _video(session)
    _import(session, video, _extraction(guests=[], no_guests=True, contacts=[], unassigned_contacts=[]))
    assert video.guest_status == "no_guests" and video.last_ingested_at is not None


def test_sin_invitados_no_pisa_un_estado_ya_revisado(session):
    video = _video(session)
    video.guest_status = "has_guests"
    _import(session, video, _extraction(guests=[], no_guests=True))
    assert video.guest_status == "has_guests"


# --- lote -------------------------------------------------------------------------------

def _batch(*videos):
    return BatchExtraction(instructions_version="v5", videos=list(videos))


def test_import_batch_reporta_los_videos_que_no_estan_en_la_bd(session):
    _video(session, "v1")
    summary = ci.import_batch(session, _batch(_extraction("v1"), _extraction("v2")), extractor="claude_code")
    assert (summary.videos, summary.missing_videos) == (1, ["v2"])


def test_import_batch_crea_los_videos_faltantes_con_los_metadatos(session):
    metadata = {"v9": {"id": "v9", "title": "Nuevo: Ana", "description": "d", "published_at": "2025-01-02T00:00:00Z",
                       "duration": "PT10M"}}
    summary = ci.import_batch(session, _batch(_extraction("v9")), extractor="claude_api",
                              video_metadata=metadata, create_missing=True)
    video = session.scalar(select(Video).where(Video.youtube_video_id == "v9"))
    assert summary.created_videos == 1 and video.source == "youtube" and video.duration_seconds == 600


def test_import_batch_sin_create_missing_no_crea_videos(session):
    metadata = {"v9": {"id": "v9", "title": "Nuevo"}}
    summary = ci.import_batch(session, _batch(_extraction("v9")), extractor="claude_code", video_metadata=metadata)
    assert summary.missing_videos == ["v9"] and session.scalar(select(Video.id)) is None


def test_import_batch_un_video_con_error_no_detiene_el_lote(session, monkeypatch):
    _video(session, "v1")
    _video(session, "v2", title="Otro: Beto")
    session.commit()
    original = ci.import_video

    def flaky(db, video, extraction, **kwargs):
        if video.youtube_video_id == "v1":
            raise RuntimeError("falla simulada")
        return original(db, video, extraction, **kwargs)

    monkeypatch.setattr(ci, "import_video", flaky)
    summary = ci.import_batch(session, _batch(_extraction("v1"), _extraction("v2")), extractor="claude_code")
    assert summary.videos == 1 and summary.errors == [("v1", "falla simulada")]
    assert {g.video_id for g in _rows(session, StagingGuestCandidate)} == {
        session.scalar(select(Video.id).where(Video.youtube_video_id == "v2"))}


def test_import_batch_simulacion_no_guarda_nada(session):
    _video(session, "v1")
    session.commit()
    summary = ci.import_batch(session, _batch(_extraction("v1")), extractor="claude_code", commit=False)
    assert summary.guests == 1
    assert not _rows(session, StagingGuestCandidate) and not _rows(session, StagingContactCandidate)


def test_import_batch_usa_la_version_del_lote_si_no_se_indica(session):
    _video(session, "v1")
    ci.import_batch(session, _batch(_extraction("v1")), extractor="claude_code")
    assert _rows(session, StagingGuestCandidate)[0].instructions_version == "v5"


def test_los_valores_de_los_contactos_no_se_escriben_en_los_logs(session, caplog):
    video = _video(session)
    with caplog.at_level("DEBUG"):
        _import(session, video, _extraction())
        ci.import_batch(session, _batch(_extraction("v1")), extractor="claude_code", commit=False)
    assert "ana_perez" not in caplog.text and "contacto@mail.com" not in caplog.text


# --- lectura de la carpeta de Claude Code -----------------------------------------------

def _write_batch(folder, name, videos, version="v5", mtime=None):
    path = folder / name
    path.write_text(json.dumps({
        "instructions_version": version, "result": {"instructions_version": version, "videos": videos},
    }), encoding="utf-8")
    if mtime:
        os.utime(path, (mtime, mtime))


def test_load_claude_code_results_junta_los_lotes_y_gana_el_mas_reciente(tmp_path):
    now = time.time()
    _write_batch(tmp_path, "batch_0001_a.json", [{"video_id": "v1", "program": "Viejo"}], mtime=now - 100)
    _write_batch(tmp_path, "batch_0002_b.json",
                 [{"video_id": "v1", "program": "Nuevo"}, {"video_id": "v2"}], mtime=now)
    batch = ci.load_claude_code_results(tmp_path)
    assert batch.instructions_version == "v5"
    assert {v.video_id: v.program for v in batch.videos} == {"v1": "Nuevo", "v2": None}


def test_load_claude_code_results_carpeta_vacia_da_error(tmp_path):
    with pytest.raises(ClaudeImportError, match=r"load_claude_code_results"):
        ci.load_claude_code_results(tmp_path)


def test_load_claude_code_results_lote_roto_da_error_con_su_nombre(tmp_path):
    (tmp_path / "batch_0001_a.json").write_text("{", encoding="utf-8")
    with pytest.raises(ClaudeImportError, match="batch_0001_a.json"):
        ci.load_claude_code_results(tmp_path)


def test_load_claude_code_results_no_mezcla_versiones(tmp_path):
    _write_batch(tmp_path, "batch_0001_a.json", [{"video_id": "v1"}], version="v3")
    _write_batch(tmp_path, "batch_0002_b.json", [{"video_id": "v2"}], version="v5")
    with pytest.raises(ClaudeImportError, match="mezcla versiones"):
        ci.load_claude_code_results(tmp_path)
