"""Pruebas de la hoja de revisión de la referencia (sin red; archivos temporales)."""
import json

import pytest

from app.schemas.claude_extraction import VideoExtraction
from scripts import review_sheet as rs
from scripts.review_sheet import ReviewError


def _video(video_id, guests=(), hosts=(), program=None, contacts=(), unassigned=()):
    return VideoExtraction.model_validate({
        "video_id": video_id, "program": program,
        "guests": [{"name": g} for g in guests], "hosts": [{"name": h} for h in hosts],
        "contacts": list(contacts), "unassigned_contacts": list(unassigned),
    })


def _gold_entry(guests=(), hosts=(), program=None, reviewed=None):
    entry = {"program": program, "guests": list(guests), "hosts": list(hosts)}
    if reviewed:
        entry["reviewed"] = True
    return entry


def _fixture():
    gold = {
        "e1": _gold_entry(["Ana"]),                       # Claude agrega a Beto: 1 error
        "e2": _gold_entry(["Cris", "Dani"]),              # Claude no encuentra a nadie: 2 errores
        "r1": _gold_entry(["Eva"], reviewed=True),        # ya revisado: nunca se vuelve a pedir
        "a1": _gold_entry(["Fer"]), "a2": _gold_entry(["Gus"]), "a3": _gold_entry(["Hugo"]),
        "c1": _gold_entry(["Iris"]),
    }
    extractions = {
        "e1": _video("e1", ["Ana", "Beto"]), "e2": _video("e2"), "r1": _video("r1"),
        "a1": _video("a1", ["Fer"]), "a2": _video("a2", ["Gus"]), "a3": _video("a3", ["Hugo"]),
        "c1": _video("c1", ["Iris"], contacts=[{"type": "instagram", "value": "@iris", "guest": "Iris"}]),
    }
    return gold, extractions


# --- selección --------------------------------------------------------------------------

def test_select_videos_ordena_errores_omite_revisados_y_no_repite():
    gold, extractions = _fixture()
    selection = rs.select_videos(gold, extractions, n_errors=2, n_agree=2, n_contacts=5, seed=1)
    ids = [i for i, _ in selection]
    assert selection[:2] == [("e2", "errores"), ("e1", "errores")]      # más errores primero
    assert "r1" not in ids and len(ids) == len(set(ids))
    assert sum(1 for _, g in selection if g == "coinciden") == 2


def test_select_videos_es_reproducible_con_la_misma_semilla():
    gold, extractions = _fixture()
    assert rs.select_videos(gold, extractions, 1, 2, 0, seed=3) == rs.select_videos(gold, extractions, 1, 2, 0, seed=3)


def test_select_videos_agrega_los_que_tienen_contactos_aunque_coincidan():
    gold, extractions = _fixture()
    selection = rs.select_videos(gold, extractions, n_errors=0, n_agree=0, n_contacts=5)
    assert selection == [("c1", "contactos")]


# --- HTML -------------------------------------------------------------------------------

def test_build_html_trae_enlace_de_youtube_texto_escapado_y_contactos():
    gold, extractions = _fixture()
    samples = {"c1": {"title": "<b>Titulo</b> & más", "description": "desc", "published_at": "2025-01-02T00:00:00Z"}}
    page = rs.build_html([("c1", "contactos")], gold, samples, extractions)
    assert "https://www.youtube.com/watch?v=c1" in page
    assert "&lt;b&gt;Titulo&lt;/b&gt;" in page and "<b>Titulo</b>" not in page
    assert "@iris" in page and 'data-contact="a0"' in page
    assert "Descargar mis respuestas" in page


def test_build_html_recorta_descripciones_largas_en_un_desplegable():
    gold, extractions = _fixture()
    samples = {"e1": {"title": "T", "description": "x" * (rs.DESCRIPTION_PREVIEW_CHARS + 50)}}
    page = rs.build_html([("e1", "errores")], gold, samples, extractions)
    assert "Ver el resto de la descripción" in page


# --- aplicar ----------------------------------------------------------------------------

def _write_gold(tmp_path, gold):
    path = tmp_path / "gold.json"
    path.write_text(json.dumps({"_meta": {}, "videos": gold}), encoding="utf-8")
    return path


def _write_answers(tmp_path, answers):
    path = tmp_path / "respuestas.json"
    path.write_text(json.dumps({"version": 1, "answers": answers}), encoding="utf-8")
    return path


def test_apply_answers_actualiza_la_referencia_marca_revisado_y_hace_respaldo(tmp_path):
    gold, extractions = _fixture()
    gold_path = _write_gold(tmp_path, gold)
    answers = _write_answers(tmp_path, {
        "e1": {"guests": ["Ana", " Ana ", "Beto"], "hosts": ["Luis"], "program": "  ", "reviewed": True},
        "e2": {"guests": ["Otro"], "hosts": [], "program": "X", "reviewed": False},   # sin marcar: se ignora
    })
    result = rs.apply_answers(gold_path, answers, tmp_path / "contactos.json", extractions)
    assert result == {"reviewed": 1, "changed": 1, "contacts_ok": 0, "contacts_bad": 0}
    data = json.loads(gold_path.read_text(encoding="utf-8"))["videos"]
    assert data["e1"]["guests"] == ["Ana", "Beto"] and data["e1"]["hosts"] == ["Luis"]
    assert data["e1"]["program"] is None and data["e1"]["reviewed"] is True
    assert data["e2"] == gold["e2"]                                   # intacto
    backups = list(tmp_path.glob("gold.backup_*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["videos"]["e1"]["guests"] == ["Ana"]


def test_apply_answers_guarda_los_veredictos_de_contactos(tmp_path):
    gold, extractions = _fixture()
    answers = _write_answers(tmp_path, {
        "c1": {"guests": ["Iris"], "hosts": [], "program": None, "reviewed": True, "contacts": {"a0": "bad", "a9": "ok"}},
    })
    contacts_path = tmp_path / "contactos.json"
    result = rs.apply_answers(_write_gold(tmp_path, gold), answers, contacts_path, extractions)
    assert (result["contacts_ok"], result["contacts_bad"]) == (0, 1)       # a9 no existe: se ignora
    saved = json.loads(contacts_path.read_text(encoding="utf-8"))
    assert saved["c1"] == [{"type": "instagram", "value": "@iris", "guest": "Iris", "verdict": "bad"}]


def test_apply_answers_video_desconocido_da_error_y_no_cambia_nada(tmp_path):
    gold, extractions = _fixture()
    gold_path = _write_gold(tmp_path, gold)
    before = gold_path.read_text(encoding="utf-8")
    answers = _write_answers(tmp_path, {"zzz": {"guests": [], "hosts": [], "reviewed": True}})
    with pytest.raises(ReviewError, match=r"apply_answers.*zzz"):
        rs.apply_answers(gold_path, answers, tmp_path / "c.json", extractions)
    assert gold_path.read_text(encoding="utf-8") == before and not list(tmp_path.glob("*.backup_*"))


def test_apply_answers_sin_videos_revisados_da_error(tmp_path):
    gold, extractions = _fixture()
    answers = _write_answers(tmp_path, {"e1": {"guests": ["Ana"], "hosts": [], "reviewed": False}})
    with pytest.raises(ReviewError, match="Ninguna respuesta"):
        rs.apply_answers(_write_gold(tmp_path, gold), answers, tmp_path / "c.json", extractions)


def test_apply_answers_lista_mal_formada_da_error_con_el_video(tmp_path):
    gold, extractions = _fixture()
    answers = _write_answers(tmp_path, {"e1": {"guests": "Ana", "hosts": [], "reviewed": True}})
    with pytest.raises(ReviewError, match=r"e1.*guests"):
        rs.apply_answers(_write_gold(tmp_path, gold), answers, tmp_path / "c.json", extractions)


def test_apply_answers_archivo_roto_da_error_de_modulo(tmp_path):
    gold, extractions = _fixture()
    bad = tmp_path / "malo.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(ReviewError, match=r"review_sheet\.apply_answers"):
        rs.apply_answers(_write_gold(tmp_path, gold), bad, tmp_path / "c.json", extractions)


# --- datos y línea de comandos ----------------------------------------------------------

def test_load_extractions_carpeta_vacia_da_error(tmp_path):
    with pytest.raises(ReviewError, match=r"load_extractions"):
        rs.load_extractions(tmp_path)


def _write_pilot(tmp_path, extractions):
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    (pilot / "batch_0001_x.json").write_text(json.dumps({
        "result": {"instructions_version": "v3", "videos": [v.model_dump() for v in extractions.values()]},
    }), encoding="utf-8")
    return pilot


def test_export_y_apply_de_punta_a_punta(tmp_path, capsys):
    gold, extractions = _fixture()
    gold_path = _write_gold(tmp_path, gold)
    pilot = _write_pilot(tmp_path, extractions)
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "sample_1.json").write_text(json.dumps({"videos": [
        {"id": i, "title": f"Titulo {i}", "description": "d", "published_at": "2025-01-01T00:00:00Z"} for i in gold
    ]}), encoding="utf-8")
    out = tmp_path / "revision.html"

    assert rs.main(["export", "--gold", str(gold_path), "--pilot-dir", str(pilot),
                    "--samples-dir", str(samples), "--out", str(out)]) == 0
    assert "https://www.youtube.com/watch?v=e1" in out.read_text(encoding="utf-8")
    assert "videos:" in capsys.readouterr().out

    answers = _write_answers(tmp_path, {"e2": {"guests": ["Cris"], "hosts": [], "program": None, "reviewed": True}})
    assert rs.main(["apply", str(answers), "--gold", str(gold_path), "--pilot-dir", str(pilot),
                    "--contacts-review", str(tmp_path / "c.json")]) == 0
    assert json.loads(gold_path.read_text(encoding="utf-8"))["videos"]["e2"]["guests"] == ["Cris"]


def test_main_devuelve_1_y_el_mensaje_cuando_falla(tmp_path, capsys):
    gold, extractions = _fixture()
    code = rs.main(["export", "--gold", str(_write_gold(tmp_path, gold)), "--pilot-dir", str(tmp_path / "no_hay")])
    assert code == 1 and "ERROR" in capsys.readouterr().err
