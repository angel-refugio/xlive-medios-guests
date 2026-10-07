"""Pruebas del perfil por serie (etapa 1 de la mejora de extracción, sin LLM ni red).

Los ejemplos son títulos y descripciones reales de la muestra del canal.
"""
import pytest

from app.services import series_profile as sp
from app.services.series_profile import SeriesProfileError
from scripts import eval_extraction as script

RAIZ = "Raíz y Cultura"
PROGRAMS = [
    RAIZ, "Revista Penthouse Television", "Inzzania TV", "El Mechero del Abuelo",
    "Metaverso Sónico", "Deportes y Política", "Rock & Riders", "V2H TV",
    "Con Las Estrellas", "Estrellas",
]


def _videos(prefix: str, descriptions: list[str], title: str = "") -> dict[str, dict]:
    return {
        f"{prefix}{i}": {"title": title or f"{prefix}: Invitado {i}", "description": d}
        for i, d in enumerate(descriptions)
    }


# --- utilidades de texto -----------------------------------------------------------------

def test_compact_ignores_accents_case_and_punctuation():
    assert sp.compact("V2H T.V.") == "v2htv"
    assert sp.compact("Música  Expansiva") == "musicaexpansiva"


def test_split_camel_only_splits_mixed_case_tags():
    assert sp._split_camel("KarimmKury") == "Karimm Kury"
    assert sp._split_camel("juancid") == "juancid"
    assert sp._split_camel("REYLOBO") == "REYLOBO"
    assert sp._split_camel("LuisRodolfo Najera") == "LuisRodolfo Najera"


def test_extract_hashtags_keeps_tags_with_spaces_and_several_per_line():
    description = "#Rockmexicano\n#Alucin\n#Whiskin Roll\n#Rodlevario #Otro"
    assert sp.extract_hashtags(description) == [
        "Rockmexicano", "Alucin", "Whiskin Roll", "Rodlevario", "Otro",
    ]
    assert sp.extract_hashtags(None) == []
    assert sp.extract_hashtags("sin etiquetas") == []


def test_extract_hashtags_strips_separators():
    assert sp.extract_hashtags("#A | #B / #C") == ["A", "B", "C"]


def test_split_names_by_commas_ampersand_and_y():
    assert sp.split_names("Patricia Muñiz, Luis Rodolfo Najera") == ["Patricia Muñiz", "Luis Rodolfo Najera"]
    assert sp.split_names("Pueblo Nuevo y El Vividor") == ["Pueblo Nuevo", "El Vividor"]
    assert sp.split_names("Mayahuel & Mauricio Rayas") == ["Mayahuel", "Mauricio Rayas"]
    assert sp.split_names("Conchita Lopez Bobadilla - Koko Duran") == ["Conchita Lopez Bobadilla", "Koko Duran"]


def test_split_names_keeps_pair_when_a_hashtag_joins_it():
    assert sp.split_names("Ulises y Nacho") == ["Ulises", "Nacho"]
    assert sp.split_names("Ulises y Nacho", {"ulisesynacho"}) == ["Ulises y Nacho"]


def test_split_names_drops_noise():
    assert sp.split_names('ENTREVISTA "TREMENS"') == ["TREMENS"]
    assert sp.split_names("BANDA LOS VIVOS TAMBIEN PENAN") == ["LOS VIVOS TAMBIEN PENAN"]
    assert sp.split_names("Terpeneando Cap 17") == ["Terpeneando"]
    # Una frase entre comillas partida por " y " no es un nombre.
    assert sp.split_names('Roger Magar y "Seguros para motociletas y motociclistas"') == ["Roger Magar"]
    assert sp.split_names("") == []


# --- programa ---------------------------------------------------------------------------

def test_detect_program_by_containment_ignoring_accents_and_dots():
    assert sp.detect_program("Raiz y Cultura: Capitan Colibri", PROGRAMS) == RAIZ
    assert sp.detect_program("V2H T.V. 📱", PROGRAMS) == "V2H TV"
    assert sp.detect_program("METAVERSO SONICO CONDUCE LESLY ZOMBIE", PROGRAMS) == "Metaverso Sónico"


def test_detect_program_prefers_the_longest_match():
    assert sp.detect_program("Con las Estrellas: Arwen", PROGRAMS) == "Con Las Estrellas"
    assert sp.detect_program("Estrellas: Quebrantahuesos", PROGRAMS) == "Estrellas"


def test_detect_program_tolerates_a_typo_before_the_colon():
    assert sp.detect_program("Inzannia TV: Romy Blues", PROGRAMS) == "Inzzania TV"


def test_detect_program_never_invents_one():
    assert sp.detect_program("Música Expansiva: Confractum", PROGRAMS) == ""
    assert sp.detect_program("Cualquier título", []) == ""


# --- perfiles por serie -----------------------------------------------------------------

def test_build_profiles_detects_recurring_hosts_only():
    videos = _videos("Revista Penthouse Television", [
        "#RevistaPenthouseTelevision\n#KarimmKury\n#XLiveMedios",
        "#RevistaPenthouseTelevision\n#KarimmKury\n#XLiveMedios",
        "#RevistaPenthouseTelevision\n#KarimmKury\n#XLiveMedios\n#Juanito",
    ])
    series, profiles = sp.build_profiles(videos, PROGRAMS)
    profile = profiles[series["Revista Penthouse Television0"]]
    assert profile.program == "Revista Penthouse Television"
    assert profile.videos == 3
    assert list(profile.hosts.values()) == ["Karimm Kury"]  # Juanito (1 video) y los hashtags genéricos no
    assert profile.host_counts == {"karimmkury": 3}


def test_build_profiles_needs_three_videos_and_half_of_the_series():
    two = _videos("Inzzania TV", ["#Dante", "#Dante"])
    _, profiles = sp.build_profiles(two, PROGRAMS)
    assert next(iter(profiles.values())).hosts == {}

    # 3 de 7 videos (43 %) no alcanza el 50 %.
    others = [f"#Otro{i}" for i in range(4)]
    rare = _videos("Inzzania TV", ["#Dante"] * 3 + others)
    _, profiles = sp.build_profiles(rare, PROGRAMS)
    assert next(iter(profiles.values())).hosts == {}

    enough = _videos("Inzzania TV", ["#Dante"] * 4 + others[:3])
    _, profiles = sp.build_profiles(enough, PROGRAMS)
    assert list(next(iter(profiles.values())).hosts.values()) == ["Dante"]


def test_build_profiles_catalog_host_needs_only_two_videos():
    videos = _videos("El Mechero del Abuelo", ["#McLuka", "#McLuka", "#Otro", "#Otro2", "#Otro3"])
    _, profiles = sp.build_profiles(videos, PROGRAMS, catalog_hosts=["MC Luka"])
    assert list(next(iter(profiles.values())).hosts.values()) == ["MC Luka"]  # con la grafía del catálogo


def test_build_profiles_ignores_series_name_and_generic_tags():
    videos = _videos("Deportes y Política", ["#DeportesyPolitica\n#XLiveMedios\n#Expandetetv"] * 4)
    _, profiles = sp.build_profiles(videos, PROGRAMS)
    assert next(iter(profiles.values())).hosts == {}


def test_build_profiles_groups_unknown_series_by_title_prefix():
    videos = {
        "a": {"title": "Serie Nueva: Uno", "description": "#Anfitrion"},
        "b": {"title": "Serie Nueva: Dos", "description": "#Anfitrion"},
        "c": {"title": "serie nueva: Tres", "description": "#Anfitrion"},
        "d": {"title": "Sin dos puntos", "description": ""},
    }
    series, profiles = sp.build_profiles(videos, [])
    assert series["a"] == series["b"] == series["c"] == "serienueva"
    assert series["d"] == ""
    assert profiles["serienueva"].program == ""
    assert list(profiles["serienueva"].hosts.values()) == ["Anfitrion"]


def test_build_profiles_rejects_bad_input():
    with pytest.raises(SeriesProfileError, match="build_profiles"):
        sp.build_profiles("no es un dict", [])  # type: ignore[arg-type]


# --- pistas de un video -----------------------------------------------------------------

def _raiz_profile() -> sp.SeriesProfile:
    videos = _videos(RAIZ, ["#RaizyCultura\n#DjRayas\n#ImperialLion\n#XLiveMedios"] * 4)
    series, profiles = sp.build_profiles(videos, PROGRAMS)
    return profiles[series[f"{RAIZ}0"]]


def test_series_hosts_after_the_colon_are_hosts_not_guests():
    profile = _raiz_profile()
    guests, hosts, program = sp.predict(
        "Raiz y Cultura: Imperial Lion y DJ Rayas", "#entrevista\n#musica\n#dub", PROGRAMS, profile,
    )
    assert program == RAIZ
    assert guests == []
    assert sorted(sp.compact(h) for h in hosts) == ["djrayas", "imperiallion"]


def test_same_names_without_profile_are_guests():
    guests, hosts, _ = sp.predict("Raiz y Cultura: Imperial Lion y DJ Rayas", "", PROGRAMS, None)
    assert guests == ["Imperial Lion", "DJ Rayas"]
    assert hosts == []


def test_guest_and_series_hosts_from_hashtags():
    profile = _raiz_profile()
    hints = sp.extract_hints(
        "Raiz y Cultura: Capitan Colibri", "#RaizyCultura\n#DjRayas\n#ImperialLion\n#CapitanColibri",
        PROGRAMS, profile,
    )
    assert [g.name for g in hints.guests] == ["Capitan Colibri"]
    assert sorted(sp.compact(h.name) for h in hints.hosts) == ["djrayas", "imperiallion"]
    assert hints.unknown == []  # CapitanColibri ya está como invitado: no se repite


def test_conduce_marker_in_title():
    hints = sp.extract_hints("A LO MEXA: CONDUCE MC INDIGENTE", "", ["A Lo Mexa"])
    assert [(h.name, h.source) for h in hints.hosts] == [("MC INDIGENTE", "title_conduce")]
    assert hints.guests == []


def test_con_marker_after_the_program_name():
    hints = sp.extract_hints("Revista Penthouse Television con Karimm Kury", "", PROGRAMS)
    assert [(h.name, h.source) for h in hints.hosts] == [("Karimm Kury", "title_con")]
    assert hints.guests == []


def test_con_host_and_invitado_in_the_same_title():
    guests, hosts, program = sp.predict("INZZANIA TV CON DANTE INVITADO VALK", "", PROGRAMS)
    assert (guests, hosts, program) == (["VALK"], ["DANTE"], "Inzzania TV")


def test_invitado_before_conduce():
    guests, hosts, _ = sp.predict(
        "METAVERSO SONICO INVITADO YOGA FIRE CONDUCE LESLY ZOMBIE", "", PROGRAMS,
    )
    assert guests == ["YOGA FIRE"]
    assert hosts == ["LESLY ZOMBIE"]


def test_conduce_before_invitados():
    guests, hosts, _ = sp.predict(
        "METAVERSO SONICO CONDUCE LESLY ZOMBIE INVITADOS TRATADO LIRIKO", "", PROGRAMS,
    )
    assert guests == ["TRATADO LIRIKO"]
    assert hosts == ["LESLY ZOMBIE"]


def test_presenta_marks_the_host_and_uppercase_parens_the_guest():
    guests, hosts, program = sp.predict(
        "MC LUKA PRESENTA: El Mechero del Abuelo (NEDMAN GUERRERO)", "", PROGRAMS,
    )
    assert (guests, hosts, program) == (["NEDMAN GUERRERO"], ["MC LUKA"], "El Mechero del Abuelo")


def test_program_presenting_itself_is_not_a_host():
    guests, hosts, _ = sp.predict("V2H presenta: Ajusco MAFIA.", "", PROGRAMS)
    assert hosts == []
    assert guests == ["Ajusco MAFIA"]


def test_title_without_catalog_does_not_take_the_program_for_a_host():
    guests, hosts, program = sp.predict("Con Las Estrellas: Arwen", "", [])
    assert (guests, hosts, program) == (["Arwen"], [], "")


def test_text_after_a_colon_with_lowercase_parens_ignores_the_parens():
    guests, _, _ = sp.predict("Masculina-mente: Renato Corona ( Asesor Patrimonial)", "", [])
    assert guests == ["Renato Corona"]


def test_description_announces_the_guest():
    guests, hosts, program = sp.predict(
        "V2H TV", "Hoy en V2H TV contamos como invitado a BENCK!\n\nOtra línea", PROGRAMS,
    )
    assert (guests, hosts, program) == (["BENCK"], [], "V2H TV")


def test_description_does_not_take_lowercase_text_as_a_name():
    guests, _, _ = sp.predict(
        "Con Las Estrellas: Pendular", "Presentamos a un colectivo que esta de aniversario", PROGRAMS,
    )
    assert guests == ["Pendular"]


def test_unknown_hashtags_are_not_proposed_as_guests():
    hints = sp.extract_hints(
        "Rock & Riders: Jessi Blues", "#Rock&riders\n#JessiBlues\n#Frankgogo\n#Expandetetv", PROGRAMS,
    )
    assert [g.name for g in hints.guests] == ["Jessi Blues"]
    assert [(u.name, u.role) for u in hints.unknown] == [("Frankgogo", "unknown")]
    assert sp.predict(
        "Rock & Riders: Jessi Blues", "#Rock&riders\n#JessiBlues\n#Frankgogo", PROGRAMS,
    )[0] == ["Jessi Blues"]


def test_catalog_spelling_wins_for_hosts():
    hints = sp.extract_hints(
        "A LO MEXA: CONDUCE MC INDIGENTE", "", ["A Lo Mexa"], catalog_hosts=["MC Indigente"],
    )
    assert [h.name for h in hints.hosts] == ["MC Indigente"]


def test_a_name_is_reported_once():
    hints = sp.extract_hints("Serie: Ana Pérez", "Presentamos a Ana Pérez", [])
    assert [g.name for g in hints.guests] == ["Ana Pérez"]


def test_empty_title_and_description_give_empty_hints():
    hints = sp.extract_hints("", None, PROGRAMS)
    assert (hints.program, hints.hosts, hints.guests, hints.unknown) == ("", [], [], [])


# --- integración con el script de evaluación -----------------------------------------------

def test_eval_script_profile_predictions_use_the_whole_series():
    samples = _videos(RAIZ, ["#RaizyCultura\n#DjRayas\n#ImperialLion"] * 3)
    samples["x"] = {"title": "Raiz y Cultura: Imperial Lion y DJ Rayas", "description": ""}
    catalogs = {"programs": [RAIZ], "hosts": ["DJ Rayas", "Imperial Lion"]}
    result = script.profile_predictions(samples, ["x"], catalogs)
    assert result["x"]["program"] == RAIZ
    assert result["x"]["guests"] == []
    assert sorted(result["x"]["hosts"]) == ["DJ Rayas", "Imperial Lion"]


def test_hashtag_contained_in_the_series_name_is_not_a_host():
    # `#MagX` es parte del nombre del programa "MagX Entreteiment", no una persona.
    programs = ["MagX Entreteiment"]
    videos = _videos("MagX Entreteiment", ["#MagX\n#MagXEntreteiment\n#KalaMrCrime"] * 4)
    _, profiles = sp.build_profiles(videos, programs)
    assert list(next(iter(profiles.values())).hosts.values()) == ["Kala Mr Crime"]
    hints = sp.extract_hints("MagX Entreteiment: Lil-H", "#MagX\n#LilH", programs)
    assert [(u.name) for u in hints.unknown] == []


def test_short_hashtag_is_not_matched_by_containment():
    # "gm" (2 letras) no se descarta por estar dentro de otro texto: es el conductor GM.
    videos = _videos("Circus TV", ["#CircusTV\n#GM"] * 3)
    _, profiles = sp.build_profiles(videos, ["Circus TV"])
    assert list(next(iter(profiles.values())).hosts.values()) == ["GM"]


def test_host_typo_maps_to_the_known_host():
    # El título escribe "Karim Kury"; el conductor conocido de la serie es "Karimm Kury".
    hints = sp.extract_hints(
        "Revista Penthouse Television con Karim Kury", "", PROGRAMS, catalog_hosts=["Karimm Kury"],
    )
    assert [h.name for h in hints.hosts] == ["Karimm Kury"]


def test_fuzzy_host_does_not_rename_a_different_short_name():
    hints = sp.extract_hints("Serie CONDUCE Dante", "", [], catalog_hosts=["Dane"])
    assert [h.name for h in hints.hosts] == ["Dante"]  # menos de 6 letras: sin comparación difusa


def test_guest_names_are_never_renamed_to_a_host():
    hints = sp.extract_hints("Serie: Karim Kury", "", [], catalog_hosts=["Karimm Kury"])
    assert [g.name for g in hints.guests] == ["Karim Kury"]


def test_title_without_colon_takes_the_guest_from_the_description_header():
    guests, hosts, program = sp.predict(
        "ROCK  AND RUL", "ROCK AND RUL: VINCENT VAN TRIO", ["Rock and Rul"],
    )
    assert (guests, hosts, program) == (["VINCENT VAN TRIO"], [], "Rock and Rul")


def test_description_header_is_ignored_when_its_prefix_is_not_the_title():
    guests, _, _ = sp.predict("Un título", "Otra cosa: Nombre Propio", [])
    assert guests == []
    assert sp.predict("Un título", "#Etiqueta: Nombre Propio", [])[0] == []


# --- "Conduce X" en la descripción --------------------------------------------------------

def test_description_conduce_marker_gives_the_hosts():
    guests, hosts, _ = sp.predict(
        "MagX Entreteiment", ".MagX Entreteiment\nConduce:\nMC KALA MR CRIME", ["MagX Entreteiment"],
    )
    assert guests == []
    assert hosts == ["MC KALA MR CRIME"]


def test_description_conducen_marker_with_two_hosts():
    hints = sp.extract_hints(
        "Raiz y Cultura", "Programa especializado en sound system\nConducen Dj Rayas & Imperial Lion",
        PROGRAMS,
    )
    assert [(h.name, h.source) for h in hints.hosts] == [
        ("Dj Rayas", "description_conduce"), ("Imperial Lion", "description_conduce"),
    ]


def test_description_conduce_ignores_prose_and_lowercase_text():
    assert sp.predict("Un título", "Conduce el programa nuestro amigo", [])[1] == []
    assert sp.predict("Un título", "Hoy conducen unos invitados especiales", [])[1] == []


def test_description_conduce_does_not_cross_lines_or_take_hashtags():
    description = "Conduce Dj Rayas\nImperial Lion presenta\n#Conduce"
    assert sp.predict("Un título", description, [])[1] == ["Dj Rayas"]


def test_description_conduce_counts_toward_the_series_hosts():
    videos = _videos("El Mechero del Abuelo", ["Conduce MC LUKA"] * 3 + ["Sin conductor"])
    _, profiles = sp.build_profiles(videos, PROGRAMS)
    assert list(next(iter(profiles.values())).hosts.values()) == ["MC LUKA"]


def test_description_conduce_host_uses_the_catalog_spelling():
    hints = sp.extract_hints(
        "El Mechero del Abuelo", "Conduce MC LUKA", PROGRAMS, catalog_hosts=["MC Luka"],
    )
    assert [h.name for h in hints.hosts] == ["MC Luka"]


# --- "con nosotros X" y nombres que no cruzan líneas ----------------------------------------

EMDA_DESCRIPTION = (
    "Hoy en nuestro programa El Mechero Del Abuelo (EMDA) Presentamos unsos grandes Invitados, "
    "con nosotros EMECE MILLA y SATURNO BEATS.... no te lo puedes perder.... "
    "No olvides comentar y dejar tu like"
)


def test_con_nosotros_announces_several_guests():
    guests, hosts, program = sp.predict(
        "El Mechero Del Abuelo", EMDA_DESCRIPTION, ["El Mechero del Abuelo"],
    )
    assert guests == ["EMECE MILLA", "SATURNO BEATS"]
    assert hosts == []  # el texto no dice quién conduce: no se inventa
    assert program == "El Mechero del Abuelo"


def test_con_nosotros_after_a_comma_gives_one_guest():
    guests, _, _ = sp.predict(
        "INZZANIA T.V.",
        "Hoy en INZZANIA T.V.\nPresentamos un invitado espectacular, con nosotros, RONAL JASPPER. No te lo pierdas",
        ["Inzzania TV"],
    )
    assert guests == ["RONAL JASPPER"]


def test_con_nosotros_ignores_prose_and_honorifics_alone():
    assert sp.predict("Un título", "Estamos con nosotros mismos, eso sí", [])[0] == []
    assert sp.predict("Un título", "Hoy con nosotros el Ing. Israel", [])[0] == []


def test_con_nosotros_keeps_a_name_that_looks_like_an_article():
    guests, _, _ = sp.predict("Un título", "Hoy con nosotros Al Pacino y la banda Los Ovnis.", [])
    assert guests == ["Al Pacino"]


def test_a_name_in_the_title_does_not_take_the_first_word_of_the_description():
    guests, hosts, _ = sp.predict(
        "El Mechero Del Abuelo (EMDA) Con McLuka presenta a MC PELA",
        "Hoy en su programa El Mechero Del Abuelo (EMDA)", ["El Mechero del Abuelo"],
    )
    assert guests == ["MC PELA"]
    assert hosts == ["McLuka"]


def test_split_names_drops_a_lone_honorific():
    assert sp.split_names("Ing") == []
    assert sp.split_names("Dr. Ana Pérez") == ["Dr. Ana Pérez"]  # con un nombre detrás sí es válido


# --- ";" como separador, listas entre comillas y "presenta live set de X" --------------------

def test_semicolon_separates_the_program_from_the_guests_like_a_colon():
    guests, _, _ = sp.predict(
        "Revoweed; Maria Powah, Estado del Lexico y Jairo Cortez", "#Revowedd", ["Revoweed"],
    )
    assert guests == ["Maria Powah", "Estado del Lexico", "Jairo Cortez"]
    assert sp.series_key("Serie Nueva; Ana Pérez", "") == "serienueva"


def test_a_quoted_list_is_split_into_its_names():
    guests, _, program = sp.predict(
        'Raìz y Cultura: "Pantibronx Reggae & Almas Militantes".', "", [RAIZ],
    )
    assert guests == ["Pantibronx Reggae", "Almas Militantes"]
    assert program == RAIZ
    assert sp.split_names('"Solo Una Frase"') == ["Solo Una Frase"]


def test_a_phrase_with_a_quote_in_the_middle_is_still_not_a_name_list():
    assert sp.split_names('Roger Magar y "Seguros para motociletas y motociclistas"') == ["Roger Magar"]


def test_presenta_live_set_de_announces_the_guest():
    guests, hosts, program = sp.predict(
        "Raíz y cultura presenta live set de Moon Mandala", "", [RAIZ],
    )
    assert (guests, hosts, program) == (["Moon Mandala"], [], RAIZ)


def test_a_hashtag_that_starts_with_conduc_is_not_a_conduce_marker():
    # "#ConductorFijo" no es "Conductor" + "Fijo": antes el regex partía la palabra y daba al conductor "Fijo".
    assert sp._description_host_names("#ConductorFijo") == []
    assert sp._description_host_names("#ConductoresUnidos\n#Otro") == []
    assert sp._description_host_names("Conductor: Juan Pérez") == ["Juan Pérez"]
    hints = sp.extract_hints("Serie: Ana Pérez", "#ConductorFijo", [])
    assert hints.hosts == []
