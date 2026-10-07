"""Pruebas de la etapa 2 (el LLM clasifica candidatos), con respuestas simuladas. Sin red real."""
import json

import httpx
import pytest

from app.services import candidate_classifier as cc
from app.services import series_profile as sp
from app.services.candidate_classifier import CandidateClassification, ClassifierError

PROGRAMS = ["Rock & Riders", "Expo Moto"]


def _client(responses: list[str | Exception]):
    calls: list[dict] = []
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        item = responses[min(state["i"], len(responses) - 1)]
        state["i"] += 1
        if isinstance(item, Exception):
            raise item
        return httpx.Response(200, json={"response": item})

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def _verdicts(*pairs: tuple[str, str]) -> str:
    return json.dumps({"verdicts": [{"name": n, "role": r} for n, r in pairs]})


def _hints() -> sp.VideoHints:
    return sp.extract_hints(
        "Rock & Riders: Jessi Blues", "#Rock&riders\n#JessiBlues\n#Frankgogo\n#cuidados", PROGRAMS,
    )


# --- candidatos dudosos ------------------------------------------------------------------

def test_doubtful_candidates_are_colon_guests_and_unknown_hashtags():
    hints = _hints()
    assert [c.name for c in cc.doubtful_candidates(hints)] == ["Jessi Blues", "Frankgogo", "cuidados"]


def test_explicit_guests_are_not_doubtful():
    hints = sp.extract_hints("INZZANIA TV CON DANTE INVITADO VALK", "", ["Inzzania TV"])
    assert [g.source for g in hints.guests] == ["title_guest"]
    assert cc.doubtful_candidates(hints) == []


# --- apply_verdicts ----------------------------------------------------------------------

def test_topic_verdict_drops_a_colon_guest():
    hints = sp.extract_hints("Expo Moto: Novedades", "", PROGRAMS)
    result = cc.apply_verdicts(hints, CandidateClassification.model_validate(
        json.loads(_verdicts(("Novedades", "topic")))))
    assert result.guests == []


def test_colon_guest_without_verdict_stays():
    hints = sp.extract_hints("Expo Moto: Francisco Igartua", "", PROGRAMS)
    result = cc.apply_verdicts(hints, CandidateClassification())
    assert [g.name for g in result.guests] == ["Francisco Igartua"]


def test_host_verdict_moves_a_colon_guest_to_hosts_only_when_allowed():
    hints = sp.extract_hints("Expo Moto: DJ Rayas", "", PROGRAMS)
    verdicts = CandidateClassification.model_validate(json.loads(_verdicts(("DJ Rayas", "host"))))
    allowed = cc.apply_verdicts(hints, verdicts, allow_host_verdict=True)
    assert allowed.guests == []
    assert [(h.name, h.source) for h in allowed.hosts] == [("DJ Rayas", "llm_host")]
    # Por defecto el LLM solo descarta: medido en 150 videos, mover roles causó 13 cambios erróneos.
    default = cc.apply_verdicts(hints, verdicts)
    assert [g.name for g in default.guests] == ["DJ Rayas"]
    assert default.hosts == []


def test_unknown_hashtag_is_promoted_only_when_allowed_and_with_a_guest_or_group_verdict():
    verdicts = CandidateClassification.model_validate(json.loads(
        _verdicts(("Jessi Blues", "guest"), ("Frankgogo", "group"), ("cuidados", "topic"))))
    result = cc.apply_verdicts(_hints(), verdicts, promote_hashtags=True)
    assert [g.name for g in result.guests] == ["Jessi Blues", "Frankgogo"]
    assert result.unknown == []


def test_unknown_hashtags_are_not_promoted_by_default_they_stay_as_doubtful_with_a_guess():
    verdicts = CandidateClassification.model_validate(json.loads(
        _verdicts(("Frankgogo", "guest"), ("cuidados", "host"))))
    result = cc.apply_verdicts(_hints(), verdicts)
    assert [g.name for g in result.guests] == ["Jessi Blues"]
    assert result.hosts == []
    assert [(u.name, u.role) for u in result.unknown] == [("Frankgogo", "guest"), ("cuidados", "host")]


def test_a_group_verdict_is_a_guest_guess_and_a_topic_verdict_is_noise():
    verdicts = CandidateClassification.model_validate(json.loads(
        _verdicts(("Frankgogo", "group"), ("cuidados", "topic"))))
    result = cc.apply_verdicts(_hints(), verdicts)
    assert [(u.name, u.role) for u in result.unknown] == [("Frankgogo", "guest")]


def test_unknown_hashtag_without_verdict_stays_doubtful_with_no_guess():
    result = cc.apply_verdicts(_hints(), CandidateClassification())
    assert [g.name for g in result.guests] == ["Jessi Blues"]
    assert [(u.name, u.role) for u in result.unknown] == [("Frankgogo", "unknown"), ("cuidados", "unknown")]


def test_verdicts_match_names_ignoring_case_and_spaces_and_never_add_names():
    result = cc.apply_verdicts(_hints(), CandidateClassification.model_validate(json.loads(
        _verdicts(("frank gogo", "guest"), ("Nombre Inventado", "guest")))), promote_hashtags=True)
    assert [g.name for g in result.guests] == ["Jessi Blues", "Frankgogo"]


def test_explicit_hosts_and_program_are_kept():
    hints = sp.extract_hints("A LO MEXA: CONDUCE MC INDIGENTE", "", ["A Lo Mexa"])
    result = cc.apply_verdicts(hints, CandidateClassification())
    assert [h.name for h in result.hosts] == ["MC INDIGENTE"]
    assert result.program == "A Lo Mexa"


# --- prompt y llamada al LLM -------------------------------------------------------------

def test_build_prompt_includes_context_and_truncates_long_descriptions():
    prompt = cc.build_prompt("Título", "x" * 5000, "Rock & Riders", ["Dante"], ["Ana", "Luis"])
    assert "Rock & Riders" in prompt and "Dante" in prompt
    assert '["Ana", "Luis"]' in prompt
    assert "x" * cc.MAX_DESCRIPTION_CHARS in prompt
    assert "x" * (cc.MAX_DESCRIPTION_CHARS + 1) not in prompt


def test_build_prompt_marks_missing_context():
    prompt = cc.build_prompt("T", None, "", [], ["Ana"])
    assert "(desconocido)" in prompt and "(ninguno conocido)" in prompt and "(sin descripción)" in prompt


def test_classify_sends_its_own_schema():
    client, calls = _client([_verdicts(("Ana", "guest"))])
    with client:
        result = cc.classify(client, "http://x", "m", "T", "D", "", [], ["Ana"])
    assert result.verdicts[0].role == "guest"
    assert "verdicts" in calls[0]["format"]["properties"]
    assert calls[0]["stream"] is False


def test_classify_retries_on_invalid_json_then_succeeds():
    client, calls = _client(["no es json", _verdicts(("Ana", "topic"))])
    with client:
        result = cc.classify(client, "http://x", "m", "T", "D", "", [], ["Ana"])
    assert result.verdicts[0].role == "topic"
    assert len(calls) == 2


def test_classify_rejects_a_role_outside_the_contract():
    client, calls = _client([_verdicts(("Ana", "cantante"))])
    with client, pytest.raises(ClassifierError, match="classify"):
        cc.classify(client, "http://x", "m", "T", "D", "", [], ["Ana"], max_attempts=2)
    assert len(calls) == 2


def test_classify_raises_after_network_errors():
    client, calls = _client([httpx.ConnectError("sin red")])
    with client, pytest.raises(ClassifierError, match="Sin salida válida"):
        cc.classify(client, "http://x", "m", "T", "D", "", [], ["Ana"], max_attempts=2)
    assert len(calls) == 2


# --- refine ------------------------------------------------------------------------------

def test_refine_skips_the_llm_when_nothing_is_doubtful():
    client, calls = _client([_verdicts()])
    hints = sp.extract_hints("INZZANIA TV CON DANTE INVITADO VALK", "", ["Inzzania TV"])
    with client:
        result = cc.refine(client, "http://x", "m", "T", "D", hints, [])
    assert calls == []
    assert [g.name for g in result.guests] == ["VALK"]
    assert [h.name for h in result.hosts] == ["DANTE"]


def test_refine_calls_the_llm_once_with_the_doubtful_names():
    client, calls = _client([_verdicts(
        ("Jessi Blues", "guest"), ("Frankgogo", "group"), ("cuidados", "topic"))])
    with client:
        result = cc.refine(client, "http://x", "m", "Rock & Riders: Jessi Blues", "D", _hints(), ["Dante"])
        promoted = cc.refine(
            client, "http://x", "m", "Rock & Riders: Jessi Blues", "D", _hints(), ["Dante"],
            promote_hashtags=True,
        )
    assert len(calls) == 2
    assert '["Jessi Blues", "Frankgogo", "cuidados"]' in calls[0]["prompt"]
    assert "Dante" in calls[0]["prompt"]
    assert [g.name for g in result.guests] == ["Jessi Blues"]
    assert [(u.name, u.role) for u in result.unknown] == [("Frankgogo", "guest")]  # dudoso, no decidido
    assert [g.name for g in promoted.guests] == ["Jessi Blues", "Frankgogo"]
    assert promoted.unknown == []


def test_topic_verdict_cannot_drop_a_colon_guest_that_the_description_repeats():
    # Corrección del usuario: lo que sigue a los dos puntos es invitado aunque suene a tema.
    hints = sp.extract_hints("Con Las Estrellas: Viaje a Marte", "Con Las Estrellas: Viaje a Marte", [])
    verdicts = CandidateClassification.model_validate(json.loads(_verdicts(("Viaje a Marte", "topic"))))
    kept = cc.apply_verdicts(hints, verdicts, "Con Las Estrellas: Viaje a Marte")
    assert [g.name for g in kept.guests] == ["Viaje a Marte"]
    dropped = cc.apply_verdicts(hints, verdicts, "Una descripción distinta")
    assert dropped.guests == []


def test_refine_passes_the_description_to_the_corroboration_check():
    client, _ = _client([_verdicts(("Los Ovnis", "topic"))])
    hints = sp.extract_hints("ROCK AND RUL: LOS OVNIS", "#LOSOVNIS", ["Rock and Rul"])
    with client:
        result = cc.refine(client, "http://x", "m", "ROCK AND RUL: LOS OVNIS", "#LOSOVNIS", hints, [])
    assert [g.name for g in result.guests] == ["LOS OVNIS"]


# --- script de evaluación: veredictos guardados y política -----------------------------------

def test_eval_script_stores_raw_verdicts_and_applies_the_policy_offline():
    from scripts import eval_extraction as script

    catalogs = {"programs": PROGRAMS, "hosts": []}
    video = {"title": "Rock & Riders: Jessi Blues", "description": "#JessiBlues\n#Frankgogo"}
    client, calls = _client([_verdicts(("Jessi Blues", "guest"), ("Frankgogo", "guest"))])
    with client:
        verdicts = script.profile_llm_verdicts(client, "http://x", "m", video, catalogs, None)
    assert verdicts == [{"name": "Jessi Blues", "role": "guest"}, {"name": "Frankgogo", "role": "guest"}]
    assert len(calls) == 1

    default = script.profile_llm_prediction(video, catalogs, None, verdicts, {})
    assert default["guests"] == ["Jessi Blues"]
    promoted = script.profile_llm_prediction(video, catalogs, None, verdicts, {"promote_hashtags": True})
    assert promoted["guests"] == ["Jessi Blues", "Frankgogo"]
    assert promoted["program"] == "Rock & Riders"


def test_eval_script_does_not_call_the_llm_without_doubtful_candidates():
    from scripts import eval_extraction as script

    catalogs = {"programs": ["Inzzania TV"], "hosts": []}
    video = {"title": "INZZANIA TV CON DANTE INVITADO VALK", "description": ""}
    client, calls = _client([_verdicts()])
    with client:
        assert script.profile_llm_verdicts(client, "http://x", "m", video, catalogs, None) == []
    assert calls == []


# --- segunda opinión del LLM para invitados --------------------------------------------------

EMDA_TEXT = (
    "El Mechero Del Abuelo\nHoy en nuestro programa Presentamos invitados, "
    "con nosotros EMECE MILLA y SATURNO BEATS.... no te lo puedes perder"
)


def test_second_opinion_accepts_names_that_appear_literally_in_the_text():
    names = cc.second_opinion_guests([], ["Emece Milla", "Saturno Beats"], EMDA_TEXT)
    assert names == ["Emece Milla", "Saturno Beats"]


def test_second_opinion_rejects_names_that_are_not_in_the_text():
    assert cc.second_opinion_guests([], ["Nombre Inventado", "AB"], EMDA_TEXT) == []


def test_second_opinion_does_not_repeat_rule_guests_hosts_or_programs():
    names = cc.second_opinion_guests(
        ["EMECE MILLA"], ["Emece Milla", "Saturno Beats", "El Mechero Del Abuelo"], EMDA_TEXT,
        excluded=["El Mechero del Abuelo", "MC Luka"],
    )
    assert names == ["Saturno Beats"]


def test_second_opinion_fallback_only_when_the_rules_found_nobody():
    assert cc.second_opinion_guests(["Ana"], ["Saturno Beats"], EMDA_TEXT, mode="fallback") == []
    assert cc.second_opinion_guests([], ["Saturno Beats"], EMDA_TEXT, mode="fallback") == ["Saturno Beats"]


def test_second_opinion_rejects_an_unknown_mode():
    with pytest.raises(ValueError, match="second_opinion_guests"):
        cc.second_opinion_guests([], ["Saturno Beats"], EMDA_TEXT, mode="otro")


def test_eval_script_second_opinion_adds_literal_llm_guests_to_the_base_prediction():
    from scripts import eval_extraction as script

    base = {"guests": ["EMECE MILLA"], "hosts": ["MC Luka"], "program": "El Mechero del Abuelo"}
    video = {"title": "El Mechero Del Abuelo", "description": "con nosotros EMECE MILLA y SATURNO BEATS"}
    llm = [{"name": "Saturno Beats"}, {"name": "MC Luka"}, {"name": "Inventado Total"}]
    catalogs = {"programs": ["El Mechero del Abuelo"], "hosts": ["MC Luka"]}
    result = script.second_opinion_prediction(base, video, llm, catalogs, "union")
    assert result["guests"] == ["EMECE MILLA", "Saturno Beats"]
    assert result["hosts"] == ["MC Luka"] and result["program"] == "El Mechero del Abuelo"
    assert script.second_opinion_prediction(base, video, llm, catalogs, "fallback")["guests"] == ["EMECE MILLA"]


# --- extracción enfocada de invitados (prompt simple) ------------------------------------------

def _simple_response(*names: str) -> str:
    return json.dumps({"invitados": list(names)})


def test_simple_guest_names_returns_clean_names_and_drops_empty_ones():
    client, calls = _client([_simple_response("  Moon   Mandala ", "", "Los Ovnis")])
    with client:
        names = cc.simple_guest_names(client, "http://x", "m", "Título", "Descripción")
    assert names == ["Moon Mandala", "Los Ovnis"]
    assert "invitados" in calls[0]["format"]["properties"]  # su propio esquema, no el del análisis completo
    assert "Título: Título" in calls[0]["prompt"]


def test_simple_guest_names_truncates_long_descriptions():
    client, calls = _client([_simple_response()])
    with client:
        assert cc.simple_guest_names(client, "http://x", "m", "T", "x" * 5000) == []
    assert "x" * (cc.MAX_DESCRIPTION_CHARS + 1) not in calls[0]["prompt"]


def test_simple_guest_names_retries_on_invalid_output_then_succeeds():
    client, calls = _client(["no es json", _simple_response("Ana")])
    with client:
        assert cc.simple_guest_names(client, "http://x", "m", "T", "D") == ["Ana"]
    assert len(calls) == 2


def test_simple_guest_names_raises_a_clear_error_after_all_attempts():
    client, calls = _client([httpx.ConnectError("sin red")])
    with client, pytest.raises(ClassifierError, match="simple_guest_names"):
        cc.simple_guest_names(client, "http://x", "m", "T", "D", max_attempts=2)
    assert len(calls) == 2


def test_eval_script_simple_guests_entry_wraps_the_names():
    from scripts import eval_extraction as script

    client, _ = _client([_simple_response("Moon Mandala")])
    with client:
        entry = script.simple_guests_entry(client, "http://x", "m", {"title": "T", "description": "D"})
    assert entry == [{"name": "Moon Mandala"}]
