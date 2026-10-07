"""Fase 3, mejora de extracción (etapa 1): perfil por serie, determinista, sin LLM ni red.

Ver la "Tercera adenda" de docs/PHASE3_PLAN.md. El rol de una persona (invitado o conductor)
depende de la serie, no del video: quien se repite en los videos de una serie es conductor o
producción; quien aparece una sola vez es invitado. Este módulo:

1. `detect_program`: asigna el programa SOLO contra el catálogo existente (nunca inventa uno).
2. `build_profiles`: agrupa los videos por serie y detecta los conductores por recurrencia
   (al menos `MIN_HOST_VIDEOS` videos y `MIN_HOST_RATIO` de la serie).
3. `extract_hints`: para un video, nombres candidatos con rol (`host` / `guest` / `unknown`)
   a partir del título (`Programa: A, B y C`, `Conduce X`, `con X`, `invitado X`), la
   descripción (`presentamos a X`, `como invitado a X`) y los hashtags (`#KarimmKury`).

Todo lo que produce es candidato: la etapa 2 (LLM) solo clasifica estos nombres y un humano los
valida en Staging Review.
"""
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.services.catalogs import normalize_name

logger = logging.getLogger(__name__)

# Umbral de recurrencia acordado con el usuario (2026-10-02): conductor si aparece en al menos
# 3 videos de la serie y en al menos el 50 % de ellos.
MIN_HOST_VIDEOS = 3
MIN_HOST_RATIO = 0.5

# Hashtags que no son personas aunque se repitan (canal, formato, género). Es una lista corta y
# editable; un conductor que esté en el catálogo siempre cuenta, aunque su hashtag esté aquí.
GENERIC_TAGS = frozenset({
    "xlivemedios", "expandetetv", "entrevista", "entrevistas", "musica", "soundsystem",
    "rockmexicano", "luchalibre", "luchalibremexicana", "hiphop", "freestyle", "dub", "reggae",
    "mexicano", "envivo", "reportajeurbano", "educacion", "musicaexpansiva",
})

_HONORIFIC_KEYS = frozenset({"ing", "lic", "dr", "dra", "mtro", "mtra", "prof", "sr", "sra"})
_MIN_COMPACT_CONTAINED = 5     # un programa de menos letras no se busca "dentro" del título
_FUZZY_PROGRAM_RATIO = 0.88     # "Rock and Rull" ~ "Rock and Rul"
_FUZZY_HOST_RATIO = 0.9         # "Karim Kury" ~ "Karimm Kury" (solo para conductores conocidos)
_MIN_FUZZY_HOST_CHARS = 6
_MAX_NAME_WORDS = 6
_NAME_CONNECTORS = {"de", "del", "la", "las", "los", "el", "y", "e", "van", "von"}

# Prefijos de ruido que no forman parte del nombre ("Entrevista: X", "Banda X", "Cap 17").
_NOISE_PREFIX_RE = re.compile(
    r"(?i)^(?:invitad[oa]s?\s+especial(?:es)?|invitad[oa]s?|entrevistando\s+a|entrevista|"
    r"banda|grupo|live\s+set\s+de|cap(?:itulo)?\.?\s*\d+)\s*[:\-]?\s*"
)
_CAP_NUMBER_RE = re.compile(r"(?i)\bcap(?:itulo)?\.?\s*\d+\b")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_EMOJI_AND_SYMBOLS_RE = re.compile(r"[^\w\s&,;:'\"()\-./áéíóúñÁÉÍÓÚÑüÜ@]")
_SPLIT_RE = re.compile(r"\s*(?:,|;|&|\s-\s|\s+y\s+|\s+e\s+)\s*", re.IGNORECASE)

_WORD = r"[A-ZÁÉÍÓÚÑ][\wáéíóúñü'’-]*"
# Las palabras de un nombre no cruzan líneas: título y descripción se unen con un salto de línea
# y, con `\s+`, "presenta a MC PELA" salía como "MC PELA Hoy" (primera palabra de la descripción).
_NAME_RE = rf"{_WORD}(?:[ \t]+(?:(?:de|del|la|las|los|el)[ \t]+)?{_WORD}){{0,4}}"
# Descripción: "presentamos a X", "como invitado a X", "contamos con X". Solo la frase es
# insensible a mayúsculas; el nombre sigue exigiendo mayúscula inicial.
_DESC_GUEST_RE = re.compile(
    rf"(?i:presentamos\s+a|como\s+invitad[oa]s?\s+a|de\s+invitad[oa]s?\s+a|"
    rf"invitad[oa]s?\s+a|presenta\s+(?:a|live\s+set\s+de)|invitad[oa]s?\s*:)\s+(?i:(?:la|el|los|las)\s+)?({_NAME_RE})"
)
# Descripción: "Conduce: A & B", "Conducen Dj A y B". Los nombres no cruzan líneas y deben empezar
# con mayúscula, para no tomar prosa ("conduce el programa nuestro amigo").
_LINE_NAME = rf"{_WORD}(?:[ \t]+(?:(?:de|del|la|las|los|el)[ \t]+)?{_WORD}){{0,4}}"
_DESC_HOST_RE = re.compile(
    rf"(?i:\bconduc\w*\b)[ \t]*:?\s*({_LINE_NAME}(?:(?:[ \t]*[,&][ \t]*|[ \t]+(?i:y|e)[ \t]+){_LINE_NAME})*)"
)
# "Invitados, con nosotros A y B" / "con nosotros, A": quien se anuncia "con nosotros" es invitado.
# El artículo ("a", "al"…) va en minúscula para no confundirlo con un nombre como "Al Pacino".
_DESC_WITH_US_RE = re.compile(
    rf"(?i:con\s+nosotros)[ \t]*,?[ \t]*(?:(?:a|al|la|el)[ \t]+)?"
    rf"({_LINE_NAME}(?:(?:[ \t]*[,&][ \t]*|[ \t]+(?i:y|e)[ \t]+){_LINE_NAME})*)"
)
# Título: quién conduce y quién es invitado, cuando lo dice con palabras.
_TITLE_HOST_RE = re.compile(r"(?i)\b(?:conduc\w+|con)\b\s*:?\s*(?P<rest>[^:/📱]+)")
_TITLE_PRESENTS_RE = re.compile(r"(?i)^\s*(?P<who>[^:/]+?)\s+presenta\s*:")
_TITLE_GUEST_RE = re.compile(r"(?i)\binvitad[oa]s?\b\s*(?:especial\s*)?:?\s*(?P<rest>[^:/📱]+)")
# Dónde termina el nombre de quien conduce dentro de "con X invitado Y" / "con X presenta a Y".
_HOST_TERMINATOR_RE = re.compile(r"(?i)\s+(?:invitad[oa]s?|presenta\w*|conduc\w+|con)\b.*$|\(.*$")
# Dónde termina el nombre del invitado en "invitado X conduce Y".
_GUEST_TERMINATOR_RE = re.compile(r"(?i)\s+(?:conduc\w+|con|presenta\w*)\b.*$")


class SeriesProfileError(RuntimeError):
    """Entrada inválida para el perfil por serie; el mensaje indica módulo y función."""


def _is_series_tag(key: str, series_keys: set[str]) -> bool:
    """Hashtag del programa mismo: igual al nombre de la serie o contenido en él (`#MagX` en
    "MagX Entreteiment"). Una clave de menos de 3 letras no se compara por contención."""
    return key in series_keys or (len(key) >= 3 and any(key in s for s in series_keys))


# --- utilidades de texto ----------------------------------------------------------------

def compact(text: str) -> str:
    """Clave sin acentos, mayúsculas, espacios ni puntuación: "V2H T.V." -> "v2htv"."""
    return re.sub(r"[\W_]+", "", normalize_name(text))


# Separador entre el nombre del programa y los invitados en el título: ":" o ";".
_TITLE_SEP_RE = re.compile(r"[:;]")


def _split_title(text: str) -> tuple[str, str]:
    """Parte el texto en (antes, después) del primer ":" o ";"."""
    parts = _TITLE_SEP_RE.split(text, maxsplit=1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def _strip_noise(text: str) -> str:
    text = _EMOJI_AND_SYMBOLS_RE.sub(" ", text)
    text = _CAP_NUMBER_RE.sub(" ", text)
    return " ".join(text.split())


def _clean_piece(piece: str) -> str:
    piece = piece.strip(" \t\"'“”‘’¨´`.:;!¡?¿()-")
    piece = _NOISE_PREFIX_RE.sub("", piece).strip(" \t\"'“”‘’¨´`.:;!¡?¿()-")
    return " ".join(piece.split())


def _is_plausible_name(piece: str) -> bool:
    words = piece.split()
    if not piece or len(words) > _MAX_NAME_WORDS or not any(c.isalpha() for c in piece):
        return False
    if len(compact(piece)) < 2:
        return False
    # Un tratamiento solo ("Ing", de "el Ing. Israel") no es un nombre: la regla de nombres se
    # corta en el punto y dejaría el tratamiento suelto.
    return compact(piece) not in _HONORIFIC_KEYS


def split_names(segment: str, tag_keys: frozenset[str] | set[str] = frozenset()) -> list[str]:
    """Parte "A, B y C" en nombres. Si dos trozos juntos coinciden con un hashtag del video
    ("Ulises y Nacho" con `#UlisesyNacho`), se dejan como un solo nombre."""
    cleaned = _strip_noise(segment)
    wrapped = cleaned.strip(" .")
    if len(wrapped) > 1 and wrapped[0] == '"' and wrapped[-1] == '"' and wrapped.count('"') == 2:
        cleaned = wrapped[1:-1]  # '"A & B".' -> 'A & B'
    raw = [p for p in _SPLIT_RE.split(cleaned) if p.count('"') % 2 == 0]
    pieces = [p for p in (_clean_piece(p) for p in raw) if p]
    merged: list[str] = []
    i = 0
    while i < len(pieces):
        if i + 1 < len(pieces) and compact(f"{pieces[i]} y {pieces[i + 1]}") in tag_keys:
            merged.append(f"{pieces[i]} y {pieces[i + 1]}")
            i += 2
        else:
            merged.append(pieces[i])
            i += 1
    return [p for p in merged if _is_plausible_name(p)]


def _split_camel(tag: str) -> str:
    """`KarimmKury` -> "Karimm Kury"; una etiqueta toda en minúsculas o mayúsculas no se parte."""
    if tag.isupper() or tag.islower() or " " in tag:
        return " ".join(tag.split())
    return " ".join(re.sub(r"(?<=[a-záéíóúñü0-9])(?=[A-ZÁÉÍÓÚÑ])", " ", tag).split())


def extract_hashtags(description: str | None) -> list[str]:
    """Etiquetas de la descripción, tal como se escribieron (sin la `#`). Una etiqueta termina
    en otra `#` o en el salto de línea, así que `#Whiskin Roll` queda completa."""
    tags: list[str] = []
    for line in (description or "").splitlines():
        if "#" not in line:
            continue
        for chunk in line.split("#")[1:]:
            tag = chunk.strip(" \t|/•.,")
            if tag:
                tags.append(tag)
    return tags


# --- programa (solo contra catálogo) -----------------------------------------------------

def _title_prefix(title: str) -> str:
    return _split_title(title)[0] if _TITLE_SEP_RE.search(title) else ""


def detect_program(title: str, programs: list[str]) -> str:
    """Programa del catálogo que aparece en el título, o "" si ninguno (nunca se inventa).

    1) El programa más largo cuyo nombre compacto está contenido en el título compacto;
    2) si no, el parecido (difflib) entre el texto antes de los dos puntos y cada programa,
    que cubre erratas como "Rock and Rull".
    """
    title_key = compact(title)
    candidates = sorted(((compact(p), p) for p in programs if p), key=lambda kp: -len(kp[0]))
    for key, program in candidates:
        if len(key) >= _MIN_COMPACT_CONTAINED and key in title_key:
            return program
    prefix_key = compact(_title_prefix(title))
    if prefix_key:
        best, best_ratio = "", 0.0
        for key, program in candidates:
            ratio = SequenceMatcher(None, prefix_key, key).ratio()
            if ratio > best_ratio:
                best, best_ratio = program, ratio
        if best_ratio >= _FUZZY_PROGRAM_RATIO:
            return best
    return ""


# --- nombres a partir del título y la descripción -----------------------------------------

@dataclass
class NameHint:
    """Un nombre candidato con el rol que sugiere la evidencia determinista."""

    name: str
    role: str      # "host" | "guest" | "unknown"
    source: str    # de dónde salió: title_conduce, title_con, title_presenta, title_guest,
    #                title_after_colon, description_guest, hashtag, series_host
    evidence: str = ""


@dataclass
class VideoHints:
    program: str = ""
    hosts: list[NameHint] = field(default_factory=list)
    guests: list[NameHint] = field(default_factory=list)
    unknown: list[NameHint] = field(default_factory=list)


def _fold(text: str) -> str:
    """Sin acentos y en minúsculas, conservando el largo (para poder cortar el texto original)."""
    return "".join(unicodedata.normalize("NFD", c)[0] for c in text).casefold()


def _remove_program(text: str, program: str) -> str:
    """Quita el nombre del programa del texto para que "Con Las Estrellas" no parezca "con X"."""
    key = compact(program) if program else ""
    if not key:
        return text
    pattern = r"[\W_]*".join(re.escape(c) for c in key)
    match = re.search(pattern, _fold(text))
    return f"{text[:match.start()]} {text[match.end():]}" if match else text


def _title_host_names(
    title: str, program: str, tag_keys: set[str], programs: list[str],
) -> list[tuple[str, str]]:
    """Conductores que el título dice con palabras: (nombre, fuente)."""
    rest_title = _remove_program(title, program)
    out: list[tuple[str, str]] = []
    presents = _TITLE_PRESENTS_RE.match(title)
    if presents:
        who = presents.group("who")
        who_key = compact(who)
        # "V2H presenta: ..." es el programa presentándose, no una persona que conduce; se
        # compara contra todo el catálogo porque el título puede abreviarlo ("V2H" por "V2H TV").
        is_program = any(
            key and (who_key in key or key in who_key)
            for key in (compact(p) for p in [*programs, program])
        )
        if not is_program:
            out += [(n, "title_presenta") for n in split_names(_remove_program(who, program), tag_keys)]
    for m in _TITLE_HOST_RE.finditer(rest_title):
        starts_title = not rest_title[:m.start()].strip()
        if starts_title and m.group(0).lower().startswith("con ") and not program:
            continue  # "Con Las Estrellas: ..." sin catálogo: es el nombre del programa
        marker = "title_conduce" if m.group(0).lower().startswith("conduc") else "title_con"
        rest = _HOST_TERMINATOR_RE.sub("", m.group("rest"))
        out += [(n, marker) for n in split_names(rest, tag_keys)]
    return out


def _title_guest_names(title: str, program: str, tag_keys: set[str]) -> list[tuple[str, str]]:
    """Invitados del título: tras "invitado" y tras los dos puntos: (nombre, fuente)."""
    out: list[tuple[str, str]] = []
    rest_title = _remove_program(title, program)
    for m in _TITLE_GUEST_RE.finditer(rest_title):
        rest = _GUEST_TERMINATOR_RE.sub("", m.group("rest"))
        out += [(n, "title_guest") for n in split_names(rest, tag_keys)]
    if _TITLE_SEP_RE.search(title):
        segment = _remove_program(_split_title(title)[1], program).split(" / ")[0]
        host_marker = _TITLE_HOST_RE.search(segment)
        if host_marker:
            segment = segment[:host_marker.start()]
        # Un nombre en MAYÚSCULAS entre paréntesis es el invitado ("(NEDMAN GUERRERO)"); lo demás
        # entre paréntesis ("(Asesor Patrimonial)") no es un nombre.
        for inner in re.findall(r"\(([^)]*)\)", segment):
            if inner.isupper():
                out += [(n, "title_after_colon") for n in split_names(inner, tag_keys)]
        segment = re.sub(r"\([^)]*\)", " ", segment)
        out += [(n, "title_after_colon") for n in split_names(segment, tag_keys)]
    return out


def _description_host_names(description: str | None) -> list[str]:
    """Conductores que la descripción anuncia con "Conduce: X" / "Conducen X y Y"."""
    names: list[str] = []
    for group in _DESC_HOST_RE.findall(description or ""):
        names += split_names(group)
    return names


def _header_guest_names(
    title: str, program: str, description: str | None, tag_keys: set[str],
) -> list[tuple[str, str]]:
    """Título sin dos puntos pero con la descripción abriendo "TÍTULO: A, B": ("ROCK AND RUL" y
    "ROCK AND RUL: VINCENT VAN TRIO"). Solo cuenta la primera línea con texto, y solo si lo que
    va antes de los dos puntos es el título o el programa."""
    first = next((ln.strip() for ln in (description or "").splitlines() if ln.strip()), "")
    if not _TITLE_SEP_RE.search(first) or first.startswith("#"):
        return []
    prefix_key = compact(_split_title(first)[0])
    if not prefix_key or prefix_key not in {compact(title), compact(program)}:
        return []
    return _title_guest_names(first, program, tag_keys)


def _description_guest_names(title: str, description: str | None) -> list[str]:
    """Invitados que el texto anuncia con palabras ("presentamos a X", "como invitado a X",
    "con nosotros X y Y")."""
    text = f"{title}\n{description or ''}"
    names = [" ".join(m.split()) for m in _DESC_GUEST_RE.findall(text)]
    for group in _DESC_WITH_US_RE.findall(text):
        names += split_names(group)
    return names


# --- perfiles por serie -------------------------------------------------------------------

@dataclass
class SeriesProfile:
    """Qué se sabe de una serie: su programa de catálogo y sus conductores por recurrencia."""

    key: str
    program: str
    videos: int
    hosts: dict[str, str] = field(default_factory=dict)   # clave compacta -> nombre a mostrar
    host_counts: dict[str, int] = field(default_factory=dict)


def series_key(title: str, program: str) -> str:
    """Programa del catálogo si lo hay; si no, el texto antes de los dos puntos; si no, vacío."""
    return compact(program) if program else compact(_title_prefix(title))


def _video_name_keys(
    title: str, description: str | None, program: str, series_keys: set[str], programs: list[str],
) -> dict[str, str]:
    """Nombres candidatos a conductor de un video: clave compacta -> nombre a mostrar.

    Salen de los hashtags que no son del programa ni genéricos, y de los conductores que el
    título dice con palabras. Una clave cuenta una vez por video.
    """
    names: dict[str, str] = {}
    tags = extract_hashtags(description)
    tag_keys = {compact(t) for t in tags}
    for tag in tags:
        key = compact(tag)
        if len(key) < 2 or key in GENERIC_TAGS or _is_series_tag(key, series_keys) or key.isdigit():
            continue
        names.setdefault(key, _split_camel(tag))
    for name, _source in _title_host_names(title, program, tag_keys, programs):
        names.setdefault(compact(name), name)
    for name in _description_host_names(description):
        names.setdefault(compact(name), name)
    return names


def build_profiles(
    videos: dict[str, dict], programs: list[str], catalog_hosts: list[str] | None = None,
) -> tuple[dict[str, str], dict[str, SeriesProfile]]:
    """Agrupa `videos` ({id: {title, description}}) por serie y detecta conductores.

    Devuelve (serie de cada video, perfiles). Un nombre es conductor si aparece en al menos
    `MIN_HOST_VIDEOS` videos de la serie y en `MIN_HOST_RATIO` de ellos, o si está en el
    catálogo de conductores y aparece en al menos 2 videos de la serie.
    """
    if not isinstance(videos, dict):
        msg = "[app.services.series_profile.build_profiles] 'videos' debe ser {id: {title, description}}"
        logger.error(msg)
        raise SeriesProfileError(msg)

    catalog = {compact(h): h for h in (catalog_hosts or []) if compact(h)}
    video_series: dict[str, str] = {}
    members: dict[str, list[str]] = defaultdict(list)
    program_of: dict[str, str] = {}
    for video_id, video in videos.items():
        program = detect_program(video["title"], programs)
        key = series_key(video["title"], program)
        video_series[video_id] = key
        if key:
            members[key].append(video_id)
            program_of.setdefault(key, program)

    profiles: dict[str, SeriesProfile] = {}
    for key, ids in members.items():
        series_keys = {key}
        counts: Counter[str] = Counter()
        display: dict[str, str] = {}
        for video_id in ids:
            video = videos[video_id]
            found = _video_name_keys(
                video["title"], video.get("description"), program_of[key], series_keys, programs,
            )
            for name_key, name in found.items():
                counts[name_key] += 1
                display.setdefault(name_key, name)
        profile = SeriesProfile(key=key, program=program_of[key], videos=len(ids))
        for name_key, n in counts.items():
            recurring = n >= MIN_HOST_VIDEOS and n / len(ids) >= MIN_HOST_RATIO
            known_host = name_key in catalog and n >= 2
            if recurring or known_host:
                profile.hosts[name_key] = catalog.get(name_key, display[name_key])
                profile.host_counts[name_key] = n
        profiles[key] = profile
    return video_series, profiles


# --- pistas de un video -------------------------------------------------------------------

def extract_hints(
    title: str, description: str | None, programs: list[str],
    profile: SeriesProfile | None = None, catalog_hosts: list[str] | None = None,
) -> VideoHints:
    """Nombres candidatos de un video, con rol, usando el perfil de su serie.

    Reglas de rol: un nombre que es conductor de la serie es `host` aunque aparezca tras los
    dos puntos; lo que dice "conduce X" / "con X" / "X presenta:" es `host`; lo que sigue a
    "invitado" o a los dos puntos y no es conductor de la serie es `guest`; un hashtag que no
    aparece en el título ni es conductor queda `unknown` (puede ser tema, no persona).
    """
    program = detect_program(title, programs)
    tags = extract_hashtags(description)
    tag_keys = {compact(t) for t in tags}
    catalog = {compact(h): h for h in (catalog_hosts or []) if compact(h)}
    series_hosts = dict(profile.hosts) if profile else {}
    hints = VideoHints(program=program)
    seen: set[str] = set()

    known_hosts = {**catalog, **series_hosts}

    def spelling(name: str) -> str:
        return known_hosts.get(compact(name)) or name

    def canonical_host(name: str) -> str:
        """Grafía del conductor conocido más parecida ("Karim Kury" -> "Karimm Kury")."""
        key = compact(name)
        if key in known_hosts or len(key) < _MIN_FUZZY_HOST_CHARS:
            return spelling(name)
        ratios = {k: SequenceMatcher(None, key, k).ratio() for k in known_hosts}
        best = max(ratios, key=ratios.get, default=None)
        return known_hosts[best] if best and ratios[best] >= _FUZZY_HOST_RATIO else name

    def add(bucket: list[NameHint], name: str, role: str, source: str) -> None:
        shown = canonical_host(name) if role == "host" else spelling(name)
        key = compact(shown)
        if not key or key in seen:
            return
        seen.add(key)
        bucket.append(NameHint(name=shown, role=role, source=source, evidence=name))

    for name, source in _title_host_names(title, program, tag_keys, programs):
        add(hints.hosts, name, "host", source)
    for name in _description_host_names(description):
        add(hints.hosts, name, "host", "description_conduce")
    guest_names = _title_guest_names(title, program, tag_keys)
    if not _TITLE_SEP_RE.search(title):
        guest_names += _header_guest_names(title, program, description, tag_keys)
    for name, source in guest_names:
        if compact(name) in series_hosts:
            add(hints.hosts, name, "host", "series_host")
        else:
            add(hints.guests, name, "guest", source)
    for name in _description_guest_names(title, description):
        if compact(name) in series_hosts:
            add(hints.hosts, name, "host", "series_host")
        else:
            add(hints.guests, name, "guest", "description_guest")

    series_keys = {compact(program)} if program else set()
    if profile:
        series_keys.add(profile.key)
    for key, name in series_hosts.items():
        if key in tag_keys:
            add(hints.hosts, name, "host", "series_host")
    for tag in tags:
        key = compact(tag)
        if (len(key) < 2 or key in GENERIC_TAGS or _is_series_tag(key, series_keys)
                or key.isdigit() or key in seen):
            continue
        add(hints.unknown, _split_camel(tag), "unknown", "hashtag")
    return hints


def predict(
    title: str, description: str | None, programs: list[str],
    profile: SeriesProfile | None = None, catalog_hosts: list[str] | None = None,
) -> tuple[list[str], list[str], str]:
    """(invitados, conductores, programa) solo con reglas, para medir esta etapa sin LLM.

    Los hashtags de rol desconocido NO se proponen como invitados: pueden ser temas. Eso es
    justo lo que la etapa 2 (LLM) debe decidir.
    """
    hints = extract_hints(title, description, programs, profile, catalog_hosts)
    return [h.name for h in hints.guests], [h.name for h in hints.hosts], hints.program
