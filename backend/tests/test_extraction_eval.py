"""Pruebas de la evaluación del extractor contra la referencia (adenda 3 de la fase 3).

Sin red ni Ollama real: el LLM se simula con httpx.MockTransport y los archivos son temporales.
"""
import json
from pathlib import Path

import httpx
import pytest

from app.services import extraction_eval as ev
from app.services.extraction_eval import EvalError, Prediction
from scripts import eval_extraction as script


# --- comparación de nombres -------------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("Karimm Kury", "karimm  kury"),
    ("Froylán Cervantes", "Froylan Cervantes"),
    ("Dr. Froylán Cervantes Torrijos", "Froylán Cervantes Torrijos"),
    ("Socio BCB (Rodrigo Marbàn)", "Socio BCB"),
    ("Arween", "Arween Tarot"),
    ("Raul (Rul)", "Raul"),
    ("SK@PE", "sk@pe"),
])
def test_names_match_verdadero(a, b):
    assert ev.names_match(a, b)


@pytest.mark.parametrize("a,b", [
    ("Less", "Lesly Zombie"),          # se compara por palabras completas, no por letras
    ("Jo", "Jose Luis"),               # la parte contenida debe tener al menos 4 letras
    ("Rod Levario", "Charli Valerio"),
    ("", "Dante"),
    ("Dr.", "Dr"),                     # solo tratamientos: sin nombre real
])
def test_names_match_falso(a, b):
    assert not ev.names_match(a, b)


def test_name_key_quita_acentos_parentesis_y_tratamientos():
    assert ev.name_key("Dra. María Pérez (psicóloga)") == "maria perez"


# --- score_video ------------------------------------------------------------------------

def _gold(**kw):
    base = {"guests": [], "hosts": []}
    base.update(kw)
    return base


def test_score_video_perfecto():
    g = _gold(program="Inzzania TV", guests=["Anne Barbosa"], hosts=["Dante"])
    s = ev.score_video("v", g, Prediction(["Anne Barbosa"], ["Dante"], "Inzzania TV"))
    assert (s.guest_tp, s.guest_fp, s.guest_fn) == (1, 0, 0)
    assert (s.host_tp, s.host_fp, s.host_fn) == (1, 0, 0)
    assert s.program_ok and s.errors == 0


def test_score_video_faltante_y_de_mas():
    g = _gold(guests=["Ana", "Benito Juarez"])
    s = ev.score_video("v", g, Prediction(["Benito Juarez", "Zoila Vaca"]))
    assert (s.guest_tp, s.guest_fp, s.guest_fn) == (1, 1, 1)
    assert s.missed_guests == ["Ana"] and s.extra_guests == ["Zoila Vaca"]


def test_score_video_dudosos_no_penalizan_ni_suman():
    g = _gold(guests=["Ana Lopez"], possible_guests=["Viaje Marte"], possible_hosts=["Sandra Olicon"])
    s = ev.score_video("v", g, Prediction(["Ana Lopez", "Viaje Marte", "Sandra Olicon"]))
    assert (s.guest_tp, s.guest_fp, s.guest_fn) == (1, 0, 0)
    s2 = ev.score_video("v", g, Prediction(["Ana Lopez"]))
    assert (s2.guest_tp, s2.guest_fp, s2.guest_fn) == (1, 0, 0)


def test_score_video_outside_metadata_no_resta_si_falta():
    g = _gold(guests=["Roger Magar", "Jose Luis Diaz"], outside_metadata=["Jose Luis Diaz"])
    s = ev.score_video("v", g, Prediction(["Roger Magar"]))
    assert (s.guest_tp, s.guest_fn, s.gold_guest_count) == (1, 0, 1)
    s2 = ev.score_video("v", g, Prediction(["Roger Magar", "Jose Luis Diaz"]))
    assert s2.guest_fp == 0


def test_score_video_rol_cambiado_cuenta_como_error_y_se_reporta():
    g = _gold(guests=["Valk"], hosts=["Dante"])
    s = ev.score_video("v", g, Prediction(guests=["Dante"], hosts=["Valk"]))
    assert s.guest_fp == 1 and s.guest_fn == 1 and s.host_fp == 1 and s.host_fn == 1
    assert sorted(s.role_swaps) == ["Dante", "Valk"]


def test_score_video_alias_de_conductor():
    g = _gold(hosts=["Raul"], host_aliases={"Raul": ["Rul"]})
    s = ev.score_video("v", g, Prediction(hosts=["Rul"]))
    assert (s.host_tp, s.host_fp, s.host_fn) == (1, 0, 0)


def test_score_video_no_cuenta_dos_veces_el_mismo_nombre():
    g = _gold(guests=["Ana Lopez"])
    s = ev.score_video("v", g, Prediction(["Ana Lopez", "ana lopez", "Ana López"]))
    assert (s.guest_tp, s.guest_fp) == (1, 0)


@pytest.mark.parametrize("expected,predicted,ok", [
    ("", "", True),                       # sin programa y no se inventó uno
    ("", "Inzzania TV", False),           # se inventó un programa
    ("Inzzania TV", "", False),           # faltó el programa
    ("Inzzania TV", "inzzania tv", True),
    ("Inzzania TV", "Raíz y Cultura", False),
])
def test_score_video_programa(expected, predicted, ok):
    s = ev.score_video("v", _gold(program=expected), Prediction(program=predicted))
    assert s.program_ok is ok


# --- summarize y reporte ----------------------------------------------------------------

def test_summarize_razones_y_alarmas_falsas():
    scores = [
        ev.score_video("a", _gold(guests=["Ana Lopez"]), Prediction(["Ana Lopez"])),
        ev.score_video("b", _gold(guests=[]), Prediction(["Inventado Uno"])),   # falsa alarma
        ev.score_video("c", _gold(guests=["Beto Ruiz"]), Prediction([])),
    ]
    s = ev.summarize(scores)
    assert (s.guest_tp, s.guest_fp, s.guest_fn) == (1, 1, 1)
    assert s.guest_precision == 0.5 and s.guest_recall == 0.5
    assert s.videos_guests_exact == 1
    assert (s.videos_without_guests, s.videos_without_guests_false_alarm) == (1, 1)


def test_summarize_sin_datos_da_none_no_division_por_cero():
    s = ev.summarize([])
    assert s.guest_precision is None and s.host_recall is None and s.program_accuracy is None


def test_format_report_incluye_revisados_y_peores():
    scores = [
        ev.score_video("a", _gold(guests=["Ana Lopez"], reviewed=True), Prediction([])),
        ev.score_video("b", _gold(guests=["Beto Ruiz"]), Prediction(["Beto Ruiz"])),
    ]
    text = ev.format_report(scores)
    assert "== Todos (2 videos) ==" in text
    assert "Solo revisados por el usuario (1 videos)" in text
    assert "- a | faltan invitados: Ana Lopez" in text
    assert "- b |" not in text          # un video sin errores no sale entre los peores


def test_format_report_sin_revisados_omite_esa_seccion():
    text = ev.format_report([ev.score_video("b", _gold(), Prediction())])
    assert "Solo revisados" not in text


# --- carga de datos ---------------------------------------------------------------------

def test_load_gold_ok(tmp_path):
    p = tmp_path / "gold.json"
    p.write_text(json.dumps({"videos": {"v": {"guests": [], "hosts": []}}}), encoding="utf-8")
    assert "v" in ev.load_gold(p)


def test_load_gold_archivo_inexistente_da_error_claro(tmp_path):
    with pytest.raises(EvalError, match=r"extraction_eval\.load_gold"):
        ev.load_gold(tmp_path / "no_existe.json")


def test_load_gold_json_invalido(tmp_path):
    p = tmp_path / "gold.json"
    p.write_text("{no es json", encoding="utf-8")
    with pytest.raises(EvalError, match="No se pudo leer"):
        ev.load_gold(p)


def test_load_gold_sin_listas_da_error_con_el_id(tmp_path):
    p = tmp_path / "gold.json"
    p.write_text(json.dumps({"videos": {"malo": {"guests": "Ana", "hosts": []}}}), encoding="utf-8")
    with pytest.raises(EvalError, match="malo"):
        ev.load_gold(p)


def _write_samples(dir_: Path, files: dict[str, list[dict]]) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    for name, videos in files.items():
        (dir_ / name).write_text(json.dumps({"videos": videos}), encoding="utf-8")


def test_load_sample_videos_une_archivos_sin_repetir(tmp_path):
    _write_samples(tmp_path, {
        "sample_1.json": [{"id": "a", "title": "A", "description": "da"}],
        "sample_2.json": [{"id": "a", "title": "A otra vez"}, {"id": "b", "title": "B", "description": None}],
    })
    vids = ev.load_sample_videos(tmp_path)
    assert set(vids) == {"a", "b"}
    assert vids["a"]["title"] == "A" and vids["b"]["description"] == ""


def test_load_sample_videos_archivo_roto_da_error_con_su_nombre(tmp_path):
    (tmp_path / "sample_roto.json").write_text("{", encoding="utf-8")
    with pytest.raises(EvalError, match="sample_roto.json"):
        ev.load_sample_videos(tmp_path)


_REAL_GOLD = script.DEFAULT_GOLD
_REAL_SAMPLES = script.DEFAULT_SAMPLES_DIR


@pytest.mark.skipif(not (_REAL_GOLD.exists() and _REAL_SAMPLES.exists()),
                    reason="backend/data/ está fuera de Git; solo corre en el equipo con los datos")
def test_referencia_real_es_consistente_con_las_muestras():
    gold = ev.load_gold(_REAL_GOLD)
    samples = ev.load_sample_videos(_REAL_SAMPLES)
    assert set(gold) <= set(samples), "hay IDs en la referencia que no están en las muestras"
    assert len(gold) == 150


# --- script: selección, caché y flujo completo ------------------------------------------

def test_select_video_ids_respeta_limite_y_revisados():
    gold = {"a": {"reviewed": True}, "b": {}, "c": {"reviewed": True}, "d": {}}
    samples = {k: {} for k in "abc"}          # 'd' no tiene texto de muestra
    assert script.select_video_ids(gold, samples, None, False) == ["a", "b", "c"]
    assert script.select_video_ids(gold, samples, 2, False) == ["a", "b"]
    assert script.select_video_ids(gold, samples, None, True) == ["a", "c"]


def test_cache_path_limpia_el_nombre_del_modelo(tmp_path):
    p = script.cache_path(tmp_path, "baseline", "qwen2.5:3b")
    assert p.name == "predictions_baseline_qwen2.5_3b.json"


def test_load_cache_roto_da_error_claro(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(EvalError, match="Caché ilegible"):
        script.load_cache(p)


def test_gold_catalogs_junta_programas_y_conductores_sin_repetir():
    gold = {"a": {"program": "P1", "hosts": ["H1", "H2"]}, "b": {"program": "P1", "hosts": ["H1"]},
            "c": {"hosts": []}}
    assert script.gold_catalogs(gold) == {"programs": ["P1"], "hosts": ["H1", "H2"]}


def _analysis(guest="Anne Barbosa", host="Dante", program="Inzzania TV"):
    return {
        "no_guests_opinion": False,
        "guests": [{"name": guest, "found_in_title": True, "found_in_description": False,
                    "is_possible_group": False, "category_match": None,
                    "category_is_new_suggestion": False, "raw_confidence": 0.8, "evidence": guest}],
        "contacts": [], "video_type_match": None, "event_borough_match": None,
        "host_match": host, "program_match": program,
    }


def _setup(tmp_path):
    gold = {"videos": {
        "v1": {"program": "Inzzania TV", "guests": ["Anne Barbosa"], "hosts": ["Dante"], "reviewed": True},
        "v2": {"guests": [], "hosts": []},
    }}
    (tmp_path / "gold.json").write_text(json.dumps(gold), encoding="utf-8")
    _write_samples(tmp_path / "samples", {"sample_1.json": [
        {"id": "v1", "title": "Inzzania TV: Anne Barbosa", "description": "#Dante"},
        {"id": "v2", "title": "Video sin nombre", "description": ""},
    ]})
    return script.build_parser().parse_args([
        "--gold", str(tmp_path / "gold.json"), "--samples-dir", str(tmp_path / "samples"),
        "--out-dir", str(tmp_path / "out"), "--model", "m", "--base-url", "http://x",
    ])


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_run_flujo_completo_escribe_cache_y_reporta(tmp_path, capsys):
    args = _setup(tmp_path)
    calls = []

    def handler(request):
        calls.append(json.loads(request.content)["prompt"])
        return httpx.Response(200, json={"response": json.dumps(_analysis())})

    assert script.run(args, client=_client(handler)) == 0
    out = capsys.readouterr().out
    assert len(calls) == 2
    assert "Videos evaluados: 2 de 2" in out
    assert "Solo revisados por el usuario (1 videos)" in out
    assert "50.0%" in out                    # precisión de invitados: v1 acierta, v2 inventa uno
    cache = json.loads(script.cache_path(tmp_path / "out", "baseline", "m").read_text(encoding="utf-8"))
    assert cache["v1"]["hosts"] == ["Dante"] and cache["v1"]["program"] == "Inzzania TV"
    # los catálogos simulados salieron de la referencia y llegaron al prompt
    assert all("Inzzania TV" in p and "Dante" in p for p in calls)


def test_run_se_reanuda_sin_repetir_llamadas(tmp_path, capsys):
    args = _setup(tmp_path)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"response": json.dumps(_analysis())})

    script.run(args, client=_client(handler))
    calls.clear()
    assert script.run(args, client=_client(handler)) == 0
    assert calls == []                       # todo estaba en el caché


def test_run_rescore_only_no_llama_al_llm(tmp_path, capsys):
    args = _setup(tmp_path)
    args.rescore_only = True

    def handler(request):
        raise AssertionError("no debe llamar al LLM con --rescore-only")

    assert script.run(args, client=_client(handler)) == 0
    assert "Videos evaluados: 0 de 2" in capsys.readouterr().out


def test_run_un_video_que_falla_no_detiene_la_evaluacion(tmp_path, capsys):
    args = _setup(tmp_path)

    def handler(request):
        if "Video sin nombre" in json.loads(request.content)["prompt"]:
            raise httpx.ConnectError("Ollama apagado")
        return httpx.Response(200, json={"response": json.dumps(_analysis())})

    assert script.run(args, client=_client(handler)) == 0
    out = capsys.readouterr().out
    assert "con error del LLM: 1" in out
    cache = json.loads(script.cache_path(tmp_path / "out", "baseline", "m").read_text(encoding="utf-8"))
    assert "error" in cache["v2"] and "error" not in cache["v1"]


def test_run_only_reviewed_y_limit(tmp_path, capsys):
    args = _setup(tmp_path)
    args.only_reviewed = True
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"response": json.dumps(_analysis())})

    script.run(args, client=_client(handler))
    assert len(calls) == 1                   # solo v1 está revisado


def test_run_sin_videos_para_evaluar_devuelve_1(tmp_path):
    args = _setup(tmp_path)
    args.limit = None
    (tmp_path / "gold.json").write_text(json.dumps({"videos": {}}), encoding="utf-8")
    assert script.run(args, client=_client(lambda r: httpx.Response(500))) == 1


def test_main_con_referencia_inexistente_devuelve_1(tmp_path, capsys):
    code = script.main(["--gold", str(tmp_path / "no.json"), "--samples-dir", str(tmp_path),
                        "--out-dir", str(tmp_path), "--model", "m", "--base-url", "http://x"])
    assert code == 1
    assert "load_gold" in capsys.readouterr().err


def test_names_match_same_name_written_with_and_without_spaces():
    assert ev.names_match("7SinsTattoStudio", "7 Sins Tatto Studio")
    assert ev.names_match("HunterBBoy", "Hunter BBoy")
    assert not ev.names_match("Ana", "A Na")  # muy corto para comparar sin espacios
