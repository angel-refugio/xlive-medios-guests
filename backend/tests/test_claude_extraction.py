"""Pruebas del extractor con Claude: lotes, prompt, lectura de la salida y tokens (sin red)."""
import json

import pytest
from pydantic import ValidationError

from app.schemas.claude_extraction import BatchExtraction, ContactCandidate, VideoExtraction
from app.services import claude_extraction as ce
from app.services.claude_extraction import ClaudeExtractionError, Usage


def _videos() -> dict[str, dict]:
    return {
        "a1": {"title": "Serie A: Uno", "description": "d1", "published_at": "2024-02-01T00:00:00Z"},
        "a2": {"title": "Serie A: Dos", "description": None, "published_at": "2024-01-01T00:00:00Z"},
        "b1": {"title": "Serie B: Tres", "description": "d3", "published_at": "2024-03-01T00:00:00Z"},
        "s1": {"title": "Titulo suelto", "description": "d4", "published_at": "2024-04-01T00:00:00Z"},
    }


def _output(ids: list[str], **extra) -> str:
    return json.dumps({
        "instructions_version": "v1",
        "videos": [{"video_id": i, **extra} for i in ids],
    })


# --- instrucciones ----------------------------------------------------------------------

def test_load_instructions_trae_la_version_y_las_reglas_de_contactos():
    text = ce.load_instructions()
    assert ce.INSTRUCTIONS_VERSION in text and "unassigned_contacts" in text
    assert "varios invitados posibles" in text and "tipo no registrado" in text


def test_load_instructions_v4_ignora_enlaces_del_canal_sin_perder_los_patrocinadores():
    v3, v4 = ce.load_instructions(version="v3"), ce.load_instructions(version="v4")
    assert "herramientas, promociones" not in v3 and "herramientas, promociones" in v4
    assert "Un patrocinador del invitado sí es un" in v4          # el patrocinador del invitado sigue siendo contacto
    assert "Viaje a Marte" not in v4 and '"instructions_version": "v4"' in v4 and "versión v4" in v4


def test_load_instructions_v3_no_contradice_la_regla_de_los_dos_puntos():
    v2, v3 = ce.load_instructions(version="v2"), ce.load_instructions(version="v3")
    assert "Viaje a Marte" in v2 and "Viaje a Marte" not in v3     # el ejemplo que contradecía la regla
    assert "aunque parezca una banda o un tema" in v3
    assert "known_hosts" in v3 and '"instructions_version": "v3"' in v3 and "versión v3" in v3


def test_load_instructions_v1_y_v2_existen_y_v2_trae_los_catalogos():
    v1, v2 = ce.load_instructions(version="v1"), ce.load_instructions(version="v2")
    assert "known_programs" not in v1 and "known_programs" in v2 and "known_hosts" in v2
    assert '"instructions_version": "v2"' in v2 and "versión v2" in v2


def test_load_instructions_version_desconocida_da_error():
    with pytest.raises(ClaudeExtractionError, match=r"load_instructions.*v9"):
        ce.load_instructions(version="v9")


def test_load_instructions_archivo_inexistente_da_error_con_modulo(tmp_path):
    with pytest.raises(ClaudeExtractionError, match=r"claude_extraction\.load_instructions"):
        ce.load_instructions(tmp_path / "no_existe.md")


# --- lotes ------------------------------------------------------------------------------

def test_build_batches_agrupa_por_serie_y_deja_sueltos_aparte():
    batches = ce.build_batches(_videos(), max_size=15)
    assert batches[0] == ["a2", "a1"]          # misma serie, ordenados por fecha
    assert sorted(batches[1]) == ["b1", "s1"]  # series de un solo video y sin serie, juntos


def test_build_batches_respeta_el_tamano_maximo():
    batches = ce.build_batches(_videos(), max_size=1)
    assert all(len(b) == 1 for b in batches)
    assert sorted(i for b in batches for i in b) == ["a1", "a2", "b1", "s1"]


def test_build_batches_tamano_invalido_da_error():
    with pytest.raises(ClaudeExtractionError, match=r"build_batches"):
        ce.build_batches(_videos(), max_size=0)


# --- prompt -----------------------------------------------------------------------------

def test_build_user_prompt_incluye_videos_tipos_y_cuentas_propias():
    prompt = ce.build_user_prompt(_videos(), ["a1", "a2"], ["instagram"], ["@xlivemedios"])
    payload = json.loads(prompt[prompt.index("{"):])
    assert [v["video_id"] for v in payload["videos"]] == ["a1", "a2"]
    assert payload["videos"][1]["description"] == ""   # None se envía como texto vacío
    assert payload["contact_types"] == ["instagram"] and payload["own_accounts"] == ["@xlivemedios"]


def test_build_user_prompt_incluye_el_catalogo_validado():
    prompt = ce.build_user_prompt(_videos(), ["a1"], known_programs=["Serie A"], known_hosts=["Luis Pérez"])
    payload = json.loads(prompt[prompt.index("{"):])
    assert payload["known_programs"] == ["Serie A"] and payload["known_hosts"] == ["Luis Pérez"]


def test_build_user_prompt_incluye_los_candidatos_de_contacto_por_video():
    candidates = {"a1": [{"id": "c1", "type": "email", "value": "a@b.com", "evidence": "a@b.com"}]}
    prompt = ce.build_user_prompt(_videos(), ["a1", "a2"], contact_candidates=candidates)
    videos = json.loads(prompt[prompt.index("{"):])["videos"]
    assert videos[0]["contact_candidates"][0]["id"] == "c1" and videos[1]["contact_candidates"] == []
    assert "contact_candidates" not in ce.build_user_prompt(_videos(), ["a1"])


def test_load_instructions_v5_los_contactos_vienen_de_la_regex():
    v5 = ce.load_instructions(version="v5")
    assert "contact_candidates" in v5 and "contact_links" in v5 and "no agregues contactos nuevos" in v5
    assert '"instructions_version": "v5"' in v5 and "versión v5" in v5 and "Viaje a Marte" not in v5


def test_build_user_prompt_lote_vacio_da_error():
    with pytest.raises(ClaudeExtractionError, match=r"build_user_prompt"):
        ce.build_user_prompt(_videos(), [])


# --- salida -----------------------------------------------------------------------------

def test_extract_json_text_quita_bloques_de_codigo_y_texto_alrededor():
    assert json.loads(ce.extract_json_text('Aquí va:\n```json\n{"a": 1}\n```\nlisto')) == {"a": 1}


def test_extract_json_text_sin_json_da_error():
    with pytest.raises(ClaudeExtractionError, match=r"extract_json_text"):
        ce.extract_json_text("no hay nada")


def test_parse_batch_output_valida_y_devuelve_los_videos():
    batch = ce.parse_batch_output(_output(["a1", "a2"], program="Serie A"), ["a1", "a2"])
    assert [v.video_id for v in batch.videos] == ["a1", "a2"] and batch.videos[0].program == "Serie A"


def test_parse_batch_output_falta_un_video_da_error_que_lo_nombra():
    with pytest.raises(ClaudeExtractionError, match=r"parse_batch_output.*a2"):
        ce.parse_batch_output(_output(["a1"]), ["a1", "a2"])


def test_parse_batch_output_video_inesperado_da_error():
    with pytest.raises(ClaudeExtractionError, match="zzz"):
        ce.parse_batch_output(_output(["a1", "zzz"]), ["a1"])


def test_parse_batch_output_fuera_del_esquema_da_error():
    bad = json.dumps({"instructions_version": "v1", "videos": [{"video_id": "a1", "guests": [{"name": ""}]}]})
    with pytest.raises(ClaudeExtractionError, match=r"parse_batch_output"):
        ce.parse_batch_output(bad, ["a1"])


def test_esquema_contacto_con_relacion_invalida_falla():
    with pytest.raises(ValidationError):
        ContactCandidate(type="instagram", value="@x", relationship="amigo")


def test_esquema_contactos_dudosos_y_sin_asignar():
    video = VideoExtraction.model_validate({
        "video_id": "a1",
        "guests": [{"name": " Ana   Pérez ", "confidence": 0.9}],
        "contacts": [{"type": "instagram", "value": "@ana", "guest": "Ana Pérez", "relationship": "propio"}],
        "unassigned_contacts": [{
            "type": "celular", "value": "55 1234 5678", "doubtful": True,
            "doubtful_reason": "varios invitados posibles",
        }],
    })
    assert video.guests[0].name == "Ana Pérez"
    assert ce.count_contacts(video) == (1, 1)
    assert video.unassigned_contacts[0].guest is None


def test_to_eval_entry_da_nombres_y_programa_vacio_si_no_hay():
    video = VideoExtraction.model_validate({
        "video_id": "a1", "guests": [{"name": "Ana"}], "hosts": [{"name": "Luis"}],
    })
    assert ce.to_eval_entry(video) == {"guests": ["Ana"], "hosts": ["Luis"], "program": ""}


# --- tokens y costo ---------------------------------------------------------------------

def _envelope(**overrides) -> str:
    base = {
        "result": "{}", "is_error": False, "total_cost_usd": 0.5,
        "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 10}},
        "usage": {
            "input_tokens": 10, "output_tokens": 20,
            "cache_creation_input_tokens": 30, "cache_read_input_tokens": 40,
        },
    }
    return json.dumps({**base, **overrides})


def test_parse_cli_envelope_lee_texto_y_tokens():
    text, usage = ce.parse_cli_envelope(_envelope())
    assert text == "{}"
    assert (usage.input_tokens, usage.output_tokens, usage.total_input_tokens, usage.calls) == (10, 20, 80, 1)
    assert usage.reported_cost_usd == 0.5
    assert usage.models == ["claude-sonnet-5-5"]


def test_parse_cli_envelope_sin_usage_cuenta_cero():
    _, usage = ce.parse_cli_envelope(json.dumps({"result": "x"}))
    assert usage.total_input_tokens == 0 and usage.output_tokens == 0 and usage.models == []


def test_parse_cli_envelope_error_de_claude():
    with pytest.raises(ClaudeExtractionError, match=r"parse_cli_envelope.*límite"):
        ce.parse_cli_envelope(_envelope(is_error=True, result="límite alcanzado"))


@pytest.mark.parametrize("stdout", ["no es json", "[1, 2]", json.dumps({"result": 5})])
def test_parse_cli_envelope_salida_invalida(stdout):
    with pytest.raises(ClaudeExtractionError, match=r"parse_cli_envelope"):
        ce.parse_cli_envelope(stdout)


def test_usage_suma_y_estima_costo_con_todos_los_tokens_de_entrada():
    total = Usage()
    total.add(Usage(input_tokens=400_000, cache_read_tokens=600_000, output_tokens=1_000_000, calls=1))
    total.add(Usage(output_tokens=0, calls=1))
    assert total.calls == 2 and total.total_input_tokens == 1_000_000
    # 1 M de entrada a 3 USD + 1 M de salida a 15 USD
    assert total.estimated_api_cost_usd(3, 15) == pytest.approx(18.0)


def test_usage_add_junta_los_modelos_sin_repetir():
    total = Usage(models=["claude-sonnet-5-5"])
    total.add(Usage(models=["claude-haiku-4-5", "claude-sonnet-5-5"]))
    assert total.models == ["claude-haiku-4-5", "claude-sonnet-5-5"]


def test_batch_extraction_requiere_version_y_videos():
    with pytest.raises(ValidationError):
        BatchExtraction.model_validate({"videos": []})
