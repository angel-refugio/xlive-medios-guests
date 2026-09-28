"""Pruebas del contrato de datos del LLM (Fase 3, paso 1). No usan Ollama real."""
import pytest
from pydantic import ValidationError

from app.schemas.ingestion import ContactCandidate, GuestCandidate, VideoAnalysis


def test_guest_candidate_minimo_valido():
    candidate = GuestCandidate(
        name="Karimm Kury",
        found_in_title=True,
        found_in_description=True,
        raw_confidence=0.8,
        evidence="con Karimm Kury",
    )
    assert candidate.name == "Karimm Kury"
    assert candidate.is_possible_group is False
    assert candidate.category_match is None


def test_guest_candidate_nombre_vacio_rechazado():
    with pytest.raises(ValidationError):
        GuestCandidate(
            name="   ",
            found_in_title=True,
            found_in_description=False,
            raw_confidence=0.5,
            evidence="algo",
        )


def test_guest_candidate_confianza_fuera_de_rango_rechazada():
    with pytest.raises(ValidationError):
        GuestCandidate(
            name="Alguien",
            found_in_title=True,
            found_in_description=False,
            raw_confidence=1.5,
            evidence="algo",
        )


def test_guest_candidate_categoria_vacia_se_normaliza_a_none():
    candidate = GuestCandidate(
        name="Alguien",
        found_in_title=True,
        found_in_description=False,
        raw_confidence=0.3,
        evidence="algo",
        category_match="   ",
    )
    assert candidate.category_match is None


def test_contact_candidate_valido():
    contact = ContactCandidate(type_hint="instagram", value="@algo", raw_confidence=0.2)
    assert contact.type_hint == "instagram"


def test_contact_candidate_valor_vacio_rechazado():
    with pytest.raises(ValidationError):
        ContactCandidate(type_hint="instagram", value="  ", raw_confidence=0.2)


def test_video_analysis_por_defecto_sin_candidatos():
    analysis = VideoAnalysis()
    assert analysis.no_guests_opinion is False
    assert analysis.guests == []
    assert analysis.contacts == []
    assert analysis.video_type_match is None


def test_video_analysis_con_candidatos_y_matches_de_catalogo():
    analysis = VideoAnalysis(
        no_guests_opinion=False,
        guests=[
            GuestCandidate(
                name="Dante",
                found_in_title=True,
                found_in_description=False,
                is_possible_group=False,
                raw_confidence=0.6,
                evidence="Dante presenta",
            )
        ],
        contacts=[ContactCandidate(type_hint="facebook", value="fb.com/algo", raw_confidence=0.2)],
        video_type_match="Entrevista",
        host_match="  Dante  ",
    )
    assert analysis.guests[0].name == "Dante"
    assert analysis.contacts[0].type_hint == "facebook"
    # Espacios de más se normalizan (comparación posterior contra catálogo vía normalize_name).
    assert analysis.host_match == "Dante"


def test_video_analysis_match_de_catalogo_vacio_es_none():
    analysis = VideoAnalysis(event_borough_match="   ")
    assert analysis.event_borough_match is None


def test_video_analysis_deserializa_json_del_llm():
    """El JSON que en teoría devolvería el LLM (paso 5) debe cargar sin cambios de forma."""
    raw = {
        "no_guests_opinion": False,
        "guests": [
            {
                "name": "NEDMAN GUERRERO",
                "found_in_title": True,
                "found_in_description": False,
                "is_possible_group": False,
                "category_match": None,
                "category_is_new_suggestion": False,
                "raw_confidence": 0.4,
                "evidence": "(NEDMAN GUERRERO)",
            }
        ],
        "contacts": [],
        "video_type_match": None,
        "event_borough_match": None,
        "host_match": None,
        "program_match": "Expandete TV",
    }
    analysis = VideoAnalysis.model_validate(raw)
    assert analysis.guests[0].name == "NEDMAN GUERRERO"
    assert analysis.program_match == "Expandete TV"
