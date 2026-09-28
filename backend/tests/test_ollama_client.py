"""Pruebas del cliente de Ollama (Fase 3, paso 5), con respuestas simuladas. Sin red real."""
import json

import httpx
import pytest

from app.services import ollama_client
from app.services.ollama_client import OllamaError

VALID_ANALYSIS = {
    "no_guests_opinion": False,
    "guests": [
        {
            "name": "Karimm Kury",
            "found_in_title": True,
            "found_in_description": True,
            "is_possible_group": False,
            "category_match": None,
            "category_is_new_suggestion": False,
            "raw_confidence": 0.8,
            "evidence": "con Karimm Kury",
        }
    ],
    "contacts": [],
    "video_type_match": None,
    "event_borough_match": None,
    "host_match": None,
    "program_match": None,
}


def _fake_transport(responses: list[str | Exception]):
    """Devuelve las respuestas en orden (una por llamada); guarda las peticiones recibidas."""
    calls: list[httpx.Request] = []
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        item = responses[min(state["i"], len(responses) - 1)]
        state["i"] += 1
        if isinstance(item, Exception):
            raise item
        return httpx.Response(200, json={"response": item})

    return httpx.MockTransport(handler), calls


def _client(responses):
    transport, calls = _fake_transport(responses)
    return httpx.Client(transport=transport), calls


# --- analyze_video: camino feliz y reintentos -----------------------------------

def test_analyze_video_exitoso_primer_intento():
    client, calls = _client([json.dumps(VALID_ANALYSIS)])
    with client:
        result = ollama_client.analyze_video(client, "http://x", "qwen2.5:3b", "T", "D")
    assert result.guests[0].name == "Karimm Kury"
    assert len(calls) == 1


def test_analyze_video_json_invalido_reintenta_y_luego_ok():
    client, calls = _client(["esto no es json", json.dumps(VALID_ANALYSIS)])
    with client:
        result = ollama_client.analyze_video(client, "http://x", "qwen2.5:3b", "T", "D")
    assert result.guests[0].name == "Karimm Kury"
    assert len(calls) == 2


def test_analyze_video_no_cumple_contrato_reintenta():
    invalido = dict(VALID_ANALYSIS, guests=[dict(VALID_ANALYSIS["guests"][0], raw_confidence=5.0)])
    client, calls = _client([json.dumps(invalido), json.dumps(VALID_ANALYSIS)])
    with client:
        result = ollama_client.analyze_video(client, "http://x", "qwen2.5:3b", "T", "D")
    assert result.guests[0].name == "Karimm Kury"
    assert len(calls) == 2


def test_analyze_video_agota_intentos_y_falla_claro():
    client, calls = _client(["no json"] * 3)
    with client:
        with pytest.raises(OllamaError, match="analyze_video") as exc:
            ollama_client.analyze_video(client, "http://x", "qwen2.5:3b", "T", "D", max_attempts=3)
    assert "Sin salida válida tras 3" in str(exc.value)
    assert len(calls) == 3


def test_analyze_video_error_de_red_reintenta_y_falla_claro():
    client, calls = _client([httpx.ConnectError("boom")] * 2)
    with client:
        with pytest.raises(OllamaError):
            ollama_client.analyze_video(client, "http://x", "qwen2.5:3b", "T", "D", max_attempts=2)
    assert len(calls) == 2


# --- _call_ollama: errores puntuales ----------------------------------------------

def test_call_ollama_http_error_no_200():
    transport = httpx.MockTransport(lambda r: httpx.Response(500, json={"error": "boom"}))
    with httpx.Client(transport=transport) as c:
        with pytest.raises(OllamaError, match="HTTP 500"):
            ollama_client._call_ollama(c, "http://x", "qwen2.5:3b", "prompt")


def test_call_ollama_respuesta_sin_campo_response():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"otra_cosa": 1}))
    with httpx.Client(transport=transport) as c:
        with pytest.raises(OllamaError, match="_call_ollama"):
            ollama_client._call_ollama(c, "http://x", "qwen2.5:3b", "prompt")


# --- payload y prompt --------------------------------------------------------------

def test_analyze_video_envia_modelo_prompt_y_esquema():
    client, calls = _client([json.dumps(VALID_ANALYSIS)])
    with client:
        ollama_client.analyze_video(
            client, "http://x", "qwen2.5:3b", "Mi título", "Mi descripción",
            existing_hosts=["Dante"],
        )
    payload = json.loads(calls[0].content)
    assert payload["model"] == "qwen2.5:3b"
    assert payload["stream"] is False
    assert "Mi título" in payload["prompt"]
    assert "Mi descripción" in payload["prompt"]
    assert "Dante" in payload["prompt"]
    assert payload["format"]["title"] == "VideoAnalysis"  # esquema JSON del contrato


def test_build_prompt_marca_catalogo_vacio():
    prompt = ollama_client._build_prompt(
        "T", None,
        existing_categories=[], existing_video_types=[], existing_boroughs=[],
        existing_hosts=[], existing_programs=[],
    )
    assert "(ninguno todavía)" in prompt
    assert "(sin descripción)" in prompt
