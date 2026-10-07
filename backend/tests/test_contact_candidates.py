"""Pruebas de los contactos candidatos por regex (v5) y su asociación con Claude."""
import pytest

from app.schemas.claude_extraction import VideoExtraction
from app.services import contact_candidates as cc

IGNORED = ["streamyard.com", "@xlivemedios"]


def _values(candidates):
    return [c.value for c in candidates]


def _by_type(candidates, kind):
    return [c.value for c in candidates if c.type == kind]


# --- extracción -------------------------------------------------------------------------

def test_extrae_links_correos_handles_y_telefonos_con_su_tipo():
    description = (
        "Síguelo en https://instagram.com/ana_perez y escríbele a ana@correo.com\n"
        "Contrata al +52 55 1234 5678 o @anaperez_oficial"
    )
    found = cc.extract_candidates("Ana en vivo", description, IGNORED)
    assert _by_type(found, "instagram") == ["https://instagram.com/ana_perez"]
    assert _by_type(found, "email") == ["ana@correo.com"]
    assert _by_type(found, "telefono") == ["+52 55 1234 5678"]
    assert _by_type(found, "handle") == ["@anaperez_oficial"]


@pytest.mark.parametrize("phone", ["5512345678", "55 1234 5678", "55-1234-5678", "(55) 1234 5678".replace("(", "").replace(")", ""),
                                   "555 123 4567", "+52 5512345678", "52 55 1234 5678"])
def test_reconoce_telefonos_mexicanos_de_10_digitos_con_o_sin_lada(phone):
    assert _by_type(cc.extract_candidates("t", f"Whatsapp {phone}"), "telefono")


@pytest.mark.parametrize("text", [
    "Publicado el 2024-05-12 a las 20:30", "Video número 123456", "https://youtu.be/1234567890?t=12",
    "Año 2023 2024 2025", "0000000000",
])
def test_no_confunde_fechas_ids_ni_numeros_repetidos_con_telefonos(text):
    assert not _by_type(cc.extract_candidates("t", text), "telefono")


def test_un_handle_no_se_toma_de_un_correo_ni_de_una_url():
    found = cc.extract_candidates("t", "Mail: ana@correo.com https://tiktok.com/@ana_baila")
    assert _by_type(found, "handle") == []


def test_el_handle_que_ya_esta_en_una_url_no_se_repite():
    found = cc.extract_candidates("t", "https://instagram.com/cheloramirezmusic\n@cheloramirezmusic y @otra_cuenta")
    assert _by_type(found, "handle") == ["@otra_cuenta"]


def test_el_handle_quita_el_punto_final_de_la_oracion():
    assert _by_type(cc.extract_candidates("t", "Búscalo en @ana_perez."), "handle") == ["@ana_perez"]


def test_la_lista_de_ignorados_quita_streamyard_y_la_cuenta_del_canal():
    description = (
        "🎙️ ¡Consulta StreamYard y obtén un descuento de $10! https://streamyard.com/pal/d/48378033...\n"
        "Síguenos @xlivemedios\nInvitado: https://instagram.com/ana"
    )
    found = cc.extract_candidates("t", description, IGNORED)
    assert _values(found) == ["https://instagram.com/ana"]


def test_sin_lista_de_ignorados_no_se_descarta_nada():
    assert any("streamyard" in v for v in _values(cc.extract_candidates("t", "https://streamyard.com/pal/d/1")))


def test_ids_consecutivos_evidencia_y_sin_repetir_el_mismo_valor():
    description = "Contacto: ana@correo.com\nOtra vez ana@correo.com"
    found = cc.extract_candidates("t", description)
    assert [c.id for c in found] == ["c1"]
    assert found[0].evidence == "Contacto: ana@correo.com"
    assert found[0].as_prompt_dict() == {"id": "c1", "type": "email", "value": "ana@correo.com",
                                         "evidence": "Contacto: ana@correo.com"}


def test_sin_descripcion_ni_contactos_devuelve_lista_vacia():
    assert cc.extract_candidates("Solo título", None) == []
    assert cc.extract_candidates("t", "Texto sin ningún dato de contacto") == []


def test_tambien_busca_en_el_titulo():
    assert _by_type(cc.extract_candidates("Ana @ana_perez", ""), "handle") == ["@ana_perez"]


# --- asociación con Claude --------------------------------------------------------------

def _video(links=()):
    return VideoExtraction.model_validate({"video_id": "v1", "contact_links": list(links)})


def _candidates():
    return cc.extract_candidates("t", "https://instagram.com/ana\nana@correo.com\n+52 55 1234 5678\n@otra_cuenta")


def test_resolve_asigna_separa_y_conserva_tipo_y_valor_de_la_regex():
    video = _video([
        {"candidate_id": "c1", "guest": "Ana Pérez", "relationship": "propio"},
        {"candidate_id": "c2", "guest": None, "doubtful": True, "doubtful_reason": "varios invitados posibles"},
        {"candidate_id": "c3", "guest": "Ana Pérez", "relationship": "manager"},
        {"candidate_id": "c4", "guest": None, "possible_guest": "Beto"},
    ])
    result = cc.resolve_contacts(video, _candidates())
    assert result == {"discarded": 0, "unknown_links": 0, "not_evaluated": 0}
    assert [(c.type, c.value, c.relationship) for c in video.contacts] == [
        ("instagram", "https://instagram.com/ana", "propio"), ("telefono", "+52 55 1234 5678", "manager"),
    ]
    assert [(c.value, c.doubtful, c.doubtful_reason) for c in video.unassigned_contacts][0] == (
        "ana@correo.com", True, "varios invitados posibles")
    assert video.unassigned_contacts[1].possible_guest == "Beto"


def test_resolve_descarta_los_contactos_de_conductores_o_cuentas_ajenas():
    video = _video([{"candidate_id": "c1", "discard": True}, {"candidate_id": "c2", "guest": "Ana"},
                    {"candidate_id": "c3", "guest": "Ana"}, {"candidate_id": "c4", "guest": "Ana"}])
    result = cc.resolve_contacts(video, _candidates())
    assert result["discarded"] == 1 and len(video.contacts) == 3 and not video.unassigned_contacts


def test_resolve_un_candidato_sin_decision_queda_sin_asignar_y_dudoso():
    video = _video([{"candidate_id": "c1", "guest": "Ana"}])
    result = cc.resolve_contacts(video, _candidates())
    assert result["not_evaluated"] == 3 and len(video.contacts) == 1
    assert all(c.doubtful and c.doubtful_reason == "no evaluado por Claude" for c in video.unassigned_contacts)
    assert len(video.unassigned_contacts) == 3          # la regex no se pierde aunque Claude omita candidatos


def test_resolve_ignora_ids_inventados_y_no_crea_contactos_nuevos(caplog):
    video = _video([{"candidate_id": "c99", "guest": "Ana"}, {"candidate_id": "c1", "guest": "Ana"}])
    with caplog.at_level("WARNING"):
        result = cc.resolve_contacts(video, _candidates())
    assert result["unknown_links"] == 1
    assert len(video.contacts) + len(video.unassigned_contacts) == 4   # exactamente los 4 de la regex


def test_resolve_reemplaza_lo_que_claude_haya_puesto_en_contacts():
    video = VideoExtraction.model_validate({
        "video_id": "v1", "contacts": [{"type": "web", "value": "inventado.com", "guest": "Ana"}],
    })
    cc.resolve_contacts(video, [])
    assert video.contacts == [] and video.unassigned_contacts == []


def test_resolve_no_escribe_valores_en_los_logs(caplog):
    candidates = cc.extract_candidates("t", "ana_secreta@correo.com")
    video = _video()
    with caplog.at_level("WARNING"):
        cc.resolve_contacts(video, candidates)
    assert "ana_secreta" not in caplog.text and "1 sin evaluar" in caplog.text
