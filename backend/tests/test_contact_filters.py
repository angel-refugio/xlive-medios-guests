"""Pruebas de la lista de enlaces y cuentas a ignorar al extraer contactos."""
import json

import pytest

from app.schemas.claude_extraction import BatchExtraction, VideoExtraction
from app.services import contact_filters as cf
from app.services.contact_filters import ContactFilterError


def _video(contacts=(), unassigned=()):
    return VideoExtraction.model_validate({
        "video_id": "v1", "contacts": list(contacts), "unassigned_contacts": list(unassigned),
    })


def _contact(value, kind="web"):
    return {"type": kind, "value": value}


@pytest.mark.parametrize("raw,expected", [
    ("HTTPS://WWW.StreamYard.com/pal/d/48378033", "streamyard.com/pal/d/48378033"),
    ("  @XLiveMedios ", "@xlivemedios"),
    ("http://ejemplo.com", "ejemplo.com"),
    ("55 1234 5678", "55 1234 5678"),
])
def test_normalize_contact(raw, expected):
    assert cf.normalize_contact(raw) == expected


def test_load_ignored_patterns_por_defecto_incluye_streamyard_y_la_cuenta_del_canal():
    patterns = cf.load_ignored_patterns()
    assert "streamyard.com" in patterns and "@xlivemedios" in patterns


def test_load_ignored_patterns_normaliza_y_quita_repetidos(tmp_path):
    path = tmp_path / "ignorados.json"
    path.write_text(json.dumps({"patterns": ["WWW.StreamYard.com", "streamyard.com", "  ", "@Canal"]}), encoding="utf-8")
    assert cf.load_ignored_patterns(path) == ["streamyard.com", "@canal"]


@pytest.mark.parametrize("content", ["{", json.dumps({"otro": []}), json.dumps({"patterns": "x"}), json.dumps({"patterns": [1]})])
def test_load_ignored_patterns_archivo_invalido_da_error_de_modulo(tmp_path, content):
    path = tmp_path / "ignorados.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ContactFilterError, match=r"contact_filters\.load_ignored_patterns"):
        cf.load_ignored_patterns(path)


def test_load_ignored_patterns_archivo_inexistente(tmp_path):
    with pytest.raises(ContactFilterError, match="ignorados.json"):
        cf.load_ignored_patterns(tmp_path / "ignorados.json")


def test_is_ignored_detecta_el_enlace_de_streamyard_con_cualquier_formato():
    patterns = ["streamyard.com"]
    assert cf.is_ignored("https://streamyard.com/pal/d/48378033", patterns)
    assert cf.is_ignored("HTTP://WWW.STREAMYARD.COM/pal", patterns)
    assert not cf.is_ignored("https://instagram.com/ana", patterns)
    assert not cf.is_ignored("anything", [])


def test_filter_video_quita_asignados_y_sin_asignar_y_cuenta():
    video = _video(
        contacts=[_contact("https://streamyard.com/pal/d/1"), _contact("@ana", "instagram")],
        unassigned=[_contact("@XLiveMedios", "instagram"), _contact("5512345678", "celular")],
    )
    assert cf.filter_video(video, ["streamyard.com", "@xlivemedios"]) == 2
    assert [c.value for c in video.contacts] == ["@ana"]
    assert [c.value for c in video.unassigned_contacts] == ["5512345678"]


def test_filter_batch_suma_los_descartados_de_todos_los_videos():
    batch = BatchExtraction.model_validate({"instructions_version": "v4", "videos": [
        {"video_id": "a", "unassigned_contacts": [_contact("streamyard.com/x")]},
        {"video_id": "b", "contacts": [_contact("streamyard.com/y"), _contact("@bea", "instagram")]},
    ]})
    assert cf.filter_batch(batch, ["streamyard.com"]) == 2
    assert batch.videos[0].unassigned_contacts == [] and len(batch.videos[1].contacts) == 1


def test_filter_batch_no_escribe_valores_en_los_logs(caplog):
    batch = BatchExtraction.model_validate({"instructions_version": "v4", "videos": [
        {"video_id": "a", "unassigned_contacts": [_contact("streamyard.com/secreto123")]},
    ]})
    with caplog.at_level("INFO"):
        cf.filter_batch(batch, ["streamyard.com"])
    assert "secreto123" not in caplog.text and "1 contacto" in caplog.text
