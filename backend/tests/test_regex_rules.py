"""Pruebas de las reglas de regex previas al LLM (Fase 3, paso 4). Sin red, sin modelo."""
from app.services.regex_rules import (
    ContactMatch, extract_contacts, extract_name_candidates, is_no_guests_candidate,
)


# --- extract_contacts -----------------------------------------------------------

def test_extract_contacts_sin_descripcion():
    assert extract_contacts(None) == []
    assert extract_contacts("   ") == []


def test_extract_contacts_url_completa():
    contacts = extract_contacts("Sígueme en https://instagram.com/algo y ya.")
    assert contacts == [
        ContactMatch("instagram", "https://instagram.com/algo", "https://instagram.com/algo")
    ]


def test_extract_contacts_url_dominio_desconocido_es_generica():
    contacts = extract_contacts("Más info en https://miweb.com/promo")
    assert contacts[0].type_hint == "url"


def test_extract_contacts_etiqueta_facebook():
    contacts = extract_contacts("FACEBOOK: /XLiveMedios\nOtro texto")
    assert contacts == [ContactMatch("facebook", "/XLiveMedios", "FACEBOOK: /XLiveMedios")]


def test_extract_contacts_etiqueta_ig_es_instagram():
    contacts = extract_contacts("IG: @xlivemedios")
    assert contacts[0].type_hint == "instagram"
    assert contacts[0].value == "@xlivemedios"


def test_extract_contacts_todas_las_etiquetas():
    for label in ("FACEBOOK", "INSTAGRAM", "IG", "YOUTUBE", "TIKTOK"):
        contacts = extract_contacts(f"{label}: valor{label.lower()}")
        assert contacts[0].value == f"valor{label.lower()}"


def test_extract_contacts_correo():
    contacts = extract_contacts("Contacto: contacto@xlivemedios.mx para dudas")
    assert contacts == [
        ContactMatch("email", "contacto@xlivemedios.mx", "contacto@xlivemedios.mx")
    ]


def test_extract_contacts_no_duplica_url_de_etiqueta():
    contacts = extract_contacts("INSTAGRAM: https://instagram.com/xlivemedios")
    assert len(contacts) == 1
    assert contacts[0].type_hint == "instagram"


def test_extract_contacts_varios_no_duplicados():
    description = (
        "FACEBOOK: /XLiveMedios\n"
        "IG: @xlivemedios\n"
        "Correo: hola@xlivemedios.mx\n"
        "Más en https://tiktok.com/@xlivemedios"
    )
    contacts = extract_contacts(description)
    assert {c.type_hint for c in contacts} == {"facebook", "instagram", "email", "tiktok"}


def test_extract_contacts_quita_puntuacion_final():
    contacts = extract_contacts("Video en https://youtube.com/watch?v=abc.")
    assert contacts[0].value == "https://youtube.com/watch?v=abc"


# --- extract_name_candidates -----------------------------------------------------
# Ejemplos textuales citados en docs/PHASE3_PLAN.md ("Patrones regex adicionales").

def test_name_candidate_despues_de_dos_puntos():
    names = extract_name_candidates("Deportes y Politica: Patricia Muñiz, Luis Rodolfo Najera", "")
    assert any(m.name == "Patricia Muñiz" and m.pattern == "after_colon" for m in names)


def test_name_candidate_con_nombre():
    names = extract_name_candidates("Revista Penthouse Television con Karimm Kury", "")
    assert any(m.name == "Karimm Kury" and m.pattern == "con_nombre" for m in names)


def test_name_candidate_mayusculas_entre_parentesis():
    titulo = "MC LUKA Presenta: El Mechero Del Abuelo (NEDMAN GUERRERO)"
    names = extract_name_candidates(titulo, "")
    assert any(m.name == "NEDMAN GUERRERO" and m.pattern == "uppercase_parens" for m in names)


def test_name_candidate_ninguno_en_texto_generico():
    assert extract_name_candidates("Resumen semanal", "Contenido variado de la semana") == []


def test_name_candidate_no_duplica_nombre_repetido_en_titulo_y_descripcion():
    names = extract_name_candidates("con Karimm Kury", "Platicamos con Karimm Kury")
    assert len([m for m in names if m.name == "Karimm Kury"]) == 1


# --- extract_name_candidates: patrón de alta señal (high_signal) -----------------
# Caso real que motivó agregarlo: un video con "es el nombre artístico de" en la
# descripción no producía ningún candidato (ni por regex ni por el LLM).

def test_name_candidate_alta_senal_nombre_artistico():
    names = extract_name_candidates(
        "Con las Estrellas Arween Tarot",
        "Arween Tarot es el nombre artístico de Wendolyn Arellano Hernández, una tarotista.",
    )
    assert any(m.name == "Wendolyn Arellano Hernández" and m.pattern == "high_signal" for m in names)


def test_name_candidate_alta_senal_seudonimo_artistico():
    names = extract_name_candidates("", "MC Luka es el seudónimo artístico de Luis Cárdenas.")
    assert any(m.name == "Luis Cárdenas" and m.pattern == "high_signal" for m in names)


def test_name_candidate_alta_senal_invitado_dos_puntos():
    names = extract_name_candidates("Invitado: Juan Perez", "")
    assert any(m.name == "Juan Perez" and m.pattern == "high_signal" for m in names)
    assert len([m for m in names if m.name == "Juan Perez"]) == 1  # no también como after_colon


def test_name_candidate_alta_senal_presenta_a():
    names = extract_name_candidates("El programa presenta a Maria Lopez hoy", "")
    assert any(m.name == "Maria Lopez" and m.pattern == "high_signal" for m in names)


def test_name_candidate_alta_senal_nombre_real():
    names = extract_name_candidates("", "Su nombre real: Ana Torres")
    assert any(m.name == "Ana Torres" and m.pattern == "high_signal" for m in names)


def test_name_candidate_sin_marcador_no_dispara_alta_senal():
    # "presenta" solo (sin "a") no cuenta; ya lo cubre after_colon si hay dos puntos.
    names = extract_name_candidates("MC LUKA Presenta: El Mechero Del Abuelo", "")
    assert not any(m.pattern == "high_signal" for m in names)


# --- is_no_guests_candidate ------------------------------------------------------

def test_no_guests_titulo_y_descripcion_genericos():
    assert is_no_guests_candidate("Resumen semanal", "") is True


def test_no_guests_vocabulario_generico_sin_nombre_ni_descripcion():
    assert is_no_guests_candidate("Gran Foro Vecinal", "") is True


def test_no_guests_falso_si_hay_nombre_en_titulo():
    assert is_no_guests_candidate("Deportes y Politica: Patricia Muñiz, Luis Rodolfo Najera", "") is False


def test_no_guests_falso_si_hay_palabra_clave_invitado():
    assert (
        is_no_guests_candidate("Programa especial", "Hoy platicamos con un invitado sorpresa")
        is False
    )


def test_no_guests_falso_si_hay_marcador_fuerte():
    assert is_no_guests_candidate("Invitado: alguien", "") is False


def test_no_guests_falso_si_hay_nombre_artistico():
    assert is_no_guests_candidate("X es el nombre artístico de Y", "") is False


def test_no_guests_falso_si_hay_descripcion_no_vacia():
    assert is_no_guests_candidate("Resumen semanal", "Un video más de la semana") is False


def test_no_guests_falso_con_nombre_en_mayusculas_entre_parentesis():
    titulo = "MC LUKA Presenta: El Mechero Del Abuelo (NEDMAN GUERRERO)"
    assert is_no_guests_candidate(titulo, "") is False


def test_no_guests_falso_con_con_nombre():
    assert is_no_guests_candidate("Revista Penthouse Television con Karimm Kury", "") is False


def test_no_guests_nunca_por_default_con_descripcion_ambigua():
    # Descripción no vacía sin nombre ni palabra clave: falla la condición 3 (descripción
    # vacía), así que igual va a la cola normal, no "sin invitados" por default.
    assert is_no_guests_candidate("Video del día", "Contenido variado de la semana") is False
