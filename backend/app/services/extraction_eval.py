"""Evaluación del extractor de invitados, conductores y programa contra la referencia (gold set).

Mide qué tan bien extrae el pipeline (hoy: regex + LLM local; después: perfil por serie + LLM)
comparando contra `backend/data/gold/guests_gold.json`. Es solo lógica de comparación: no llama
a Ollama ni toca la base de datos (eso lo hace `scripts/eval_extraction.py`), así que se prueba
sin red. Ver la "Tercera adenda" de docs/PHASE3_PLAN.md.

Reglas de puntuación (acordadas con el usuario al armar la referencia):
- `guests` / `hosts` de la referencia son nombres seguros: acertarlos suma, omitirlos resta.
- `possible_guests` / `possible_hosts` son dudosos: proponerlos u omitirlos no cuenta.
- `outside_metadata` son nombres que el usuario vio fuera del título/descripción guardados: el
  extractor no puede encontrarlos, así que omitirlos no resta (proponerlos tampoco cuenta).
- `host_aliases` permite que un conductor se reconozca por un apodo ("Raul" / "Rul").
"""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.services.catalogs import normalize_name

logger = logging.getLogger(__name__)

_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")
_NON_WORD_RE = re.compile(r"[^\w\s@]")
# Tratamientos que no distinguen a una persona ("Dr. Froylán Cervantes" == "Froylán Cervantes").
_HONORIFICS = {"dr", "dra", "lic", "ing", "mtro", "mtra", "prof"}
_MIN_CONTAINED_CHARS = 4


class EvalError(RuntimeError):
    """Fallo al cargar o comparar datos de la evaluación; el mensaje indica módulo y función."""


@dataclass
class Prediction:
    """Lo que extrajo el pipeline para un video (nombres en texto libre, como los devolvió)."""

    guests: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)
    program: str = ""


@dataclass
class VideoScore:
    video_id: str
    gold_guest_count: int = 0
    guest_tp: int = 0
    guest_fp: int = 0
    guest_fn: int = 0
    host_tp: int = 0
    host_fp: int = 0
    host_fn: int = 0
    program_ok: bool = True
    reviewed: bool = False
    missed_guests: list[str] = field(default_factory=list)
    extra_guests: list[str] = field(default_factory=list)
    missed_hosts: list[str] = field(default_factory=list)
    extra_hosts: list[str] = field(default_factory=list)
    # Nombres propuestos con el rol equivocado (invitado que en realidad es conductor o al revés).
    role_swaps: list[str] = field(default_factory=list)
    expected_program: str = ""
    predicted_program: str = ""

    @property
    def errors(self) -> int:
        return self.guest_fp + self.guest_fn + self.host_fp + self.host_fn + (0 if self.program_ok else 1)


@dataclass
class Summary:
    videos: int = 0
    guest_tp: int = 0
    guest_fp: int = 0
    guest_fn: int = 0
    host_tp: int = 0
    host_fp: int = 0
    host_fn: int = 0
    program_correct: int = 0
    videos_guests_exact: int = 0
    videos_without_guests: int = 0
    videos_without_guests_false_alarm: int = 0
    role_swaps: int = 0

    @staticmethod
    def _ratio(num: int, den: int) -> float | None:
        return num / den if den else None

    @property
    def guest_precision(self) -> float | None:
        return self._ratio(self.guest_tp, self.guest_tp + self.guest_fp)

    @property
    def guest_recall(self) -> float | None:
        return self._ratio(self.guest_tp, self.guest_tp + self.guest_fn)

    @property
    def host_precision(self) -> float | None:
        return self._ratio(self.host_tp, self.host_tp + self.host_fp)

    @property
    def host_recall(self) -> float | None:
        return self._ratio(self.host_tp, self.host_tp + self.host_fn)

    @property
    def program_accuracy(self) -> float | None:
        return self._ratio(self.program_correct, self.videos)


# --- carga de datos ---------------------------------------------------------------------

def load_gold(path: Path) -> dict[str, dict]:
    """Lee la referencia y valida su forma. Un archivo ilegible o mal formado detiene la corrida."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        videos = data["videos"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        msg = f"[app.services.extraction_eval.load_gold] No se pudo leer {path}: {exc}"
        logger.error(msg)
        raise EvalError(msg) from exc
    for video_id, entry in videos.items():
        if not isinstance(entry.get("guests"), list) or not isinstance(entry.get("hosts"), list):
            msg = (
                f"[app.services.extraction_eval.load_gold] El video {video_id} no tiene "
                "'guests' y 'hosts' como listas"
            )
            logger.error(msg)
            raise EvalError(msg)
    return videos


def load_sample_videos(samples_dir: Path) -> dict[str, dict]:
    """IDs -> {title, description} de todos los JSON de muestras (sin repetir IDs)."""
    videos: dict[str, dict] = {}
    for path in sorted(Path(samples_dir).glob("sample_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for video in data["videos"]:
                videos.setdefault(video["id"], {
                    "title": video["title"], "description": video.get("description") or "",
                })
        except (OSError, ValueError, KeyError, TypeError) as exc:
            msg = f"[app.services.extraction_eval.load_sample_videos] No se pudo leer {path.name}: {exc}"
            logger.error(msg)
            raise EvalError(msg) from exc
    return videos


# --- comparación de nombres -------------------------------------------------------------

def name_key(name: str) -> str:
    """Clave de comparación: sin acentos, mayúsculas, paréntesis, puntuación ni tratamientos."""
    without_parens = _PARENTHETICAL_RE.sub(" ", name)
    cleaned = _NON_WORD_RE.sub(" ", normalize_name(without_parens))
    return " ".join(t for t in cleaned.split() if t not in _HONORIFICS)


def names_match(a: str, b: str) -> bool:
    """Mismo nombre, o uno contenido en el otro por palabras completas.

    "Arween" coincide con "Arween Tarot"; "Less" no coincide con "Lesly Zombie" (se compara por
    palabras, no por letras). Por seguridad, la parte contenida debe tener al menos 4 letras.
    """
    ka, kb = name_key(a), name_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    # "7SinsTattoStudio" y "7 Sins Tatto Studio" son el mismo nombre escrito con y sin espacios.
    glued_a, glued_b = ka.replace(" ", ""), kb.replace(" ", "")
    if glued_a == glued_b and len(glued_a) >= _MIN_CONTAINED_CHARS:
        return True
    short, long_ = sorted((ka.split(), kb.split()), key=len)
    if len(" ".join(short)) < _MIN_CONTAINED_CHARS:
        return False
    return any(long_[i:i + len(short)] == short for i in range(len(long_) - len(short) + 1))


def _dedupe(names: list[str]) -> list[str]:
    unique: list[str] = []
    for name in names:
        if name_key(name) and not any(names_match(name, seen) for seen in unique):
            unique.append(name)
    return unique


def _match_lists(
    gold_names: list[str], predicted: list[str], aliases: dict[str, list[str]] | None = None,
) -> tuple[int, list[str], list[str]]:
    """Empareja uno a uno. Devuelve (aciertos, gold sin emparejar, predichos sin emparejar)."""
    aliases = aliases or {}
    remaining = list(predicted)
    hits = 0
    missed: list[str] = []
    for gold_name in gold_names:
        candidates = [gold_name, *aliases.get(gold_name, [])]
        found = next((p for p in remaining if any(names_match(p, c) for c in candidates)), None)
        if found is None:
            missed.append(gold_name)
        else:
            remaining.remove(found)
            hits += 1
    return hits, missed, remaining


# --- puntuación -------------------------------------------------------------------------

def score_video(video_id: str, gold: dict, prediction: Prediction) -> VideoScore:
    """Compara la predicción de un video contra su entrada de la referencia."""
    outside = gold.get("outside_metadata", [])
    neutral = [*gold.get("possible_guests", []), *gold.get("possible_hosts", []), *outside]
    gold_guests = [g for g in gold["guests"] if not any(names_match(g, o) for o in outside)]
    gold_hosts = gold["hosts"]

    guest_hits, missed_guests, extra_guests = _match_lists(gold_guests, _dedupe(prediction.guests))
    host_hits, missed_hosts, extra_hosts = _match_lists(
        gold_hosts, _dedupe(prediction.hosts), gold.get("host_aliases"),
    )

    def real_extras(extra: list[str], other_role_gold: list[str]) -> tuple[list[str], list[str]]:
        """(extras que penalizan, de ellos los que son el rol contrario). Los dudosos no penalizan."""
        kept = [n for n in extra if not any(names_match(n, x) for x in neutral)]
        swaps = [n for n in kept if any(names_match(n, x) for x in other_role_gold)]
        return kept, swaps

    extra_guests, guest_swaps = real_extras(extra_guests, gold_hosts)
    extra_hosts, host_swaps = real_extras(extra_hosts, gold_guests)

    expected = gold.get("program") or ""
    predicted = prediction.program or ""
    program_ok = (not predicted) if not expected else bool(predicted and names_match(expected, predicted))

    return VideoScore(
        video_id=video_id, gold_guest_count=len(gold_guests),
        guest_tp=guest_hits, guest_fp=len(extra_guests), guest_fn=len(missed_guests),
        host_tp=host_hits, host_fp=len(extra_hosts), host_fn=len(missed_hosts),
        program_ok=program_ok, reviewed=bool(gold.get("reviewed")),
        missed_guests=missed_guests, extra_guests=extra_guests,
        missed_hosts=missed_hosts, extra_hosts=extra_hosts,
        role_swaps=[*guest_swaps, *host_swaps],
        expected_program=expected, predicted_program=predicted,
    )


def summarize(scores: list[VideoScore]) -> Summary:
    s = Summary(videos=len(scores))
    for v in scores:
        s.guest_tp += v.guest_tp
        s.guest_fp += v.guest_fp
        s.guest_fn += v.guest_fn
        s.host_tp += v.host_tp
        s.host_fp += v.host_fp
        s.host_fn += v.host_fn
        s.program_correct += int(v.program_ok)
        s.role_swaps += len(v.role_swaps)
        if v.guest_fp == 0 and v.guest_fn == 0:
            s.videos_guests_exact += 1
        if v.gold_guest_count == 0:
            s.videos_without_guests += 1
            if v.guest_fp > 0:
                s.videos_without_guests_false_alarm += 1
    return s


# --- reporte ----------------------------------------------------------------------------

def _pct(value: float | None) -> str:
    return "  n/d" if value is None else f"{value * 100:5.1f}%"


def _summary_lines(label: str, s: Summary) -> list[str]:
    return [
        f"== {label} ({s.videos} videos) ==",
        f"Invitados   precisión {_pct(s.guest_precision)}  recall {_pct(s.guest_recall)}"
        f"   (aciertos {s.guest_tp}, de más {s.guest_fp}, faltan {s.guest_fn})",
        f"Conductores precisión {_pct(s.host_precision)}  recall {_pct(s.host_recall)}"
        f"   (aciertos {s.host_tp}, de más {s.host_fp}, faltan {s.host_fn})",
        f"Programa    acierto {_pct(s.program_accuracy)}   ({s.program_correct} de {s.videos})",
        f"Videos con la lista de invitados exacta: {s.videos_guests_exact} de {s.videos}",
        f"Videos sin invitados en la referencia: {s.videos_without_guests}; "
        f"con invitados inventados: {s.videos_without_guests_false_alarm}",
        f"Roles cambiados (invitado <-> conductor): {s.role_swaps}",
    ]


def format_report(scores: list[VideoScore], worst: int = 15) -> str:
    """Reporte de texto: resumen general, resumen de los revisados por el usuario y peores videos."""
    lines = _summary_lines("Todos", summarize(scores))
    reviewed = [v for v in scores if v.reviewed]
    if reviewed:
        lines += ["", *_summary_lines("Solo revisados por el usuario", summarize(reviewed))]
    worst_videos = sorted((v for v in scores if v.errors), key=lambda v: (-v.errors, v.video_id))[:worst]
    if worst_videos:
        lines += ["", f"== Los {len(worst_videos)} videos con más errores =="]
        for v in worst_videos:
            parts = []
            if v.missed_guests:
                parts.append(f"faltan invitados: {', '.join(v.missed_guests)}")
            if v.extra_guests:
                parts.append(f"invitados de más: {', '.join(v.extra_guests)}")
            if v.missed_hosts:
                parts.append(f"faltan conductores: {', '.join(v.missed_hosts)}")
            if v.extra_hosts:
                parts.append(f"conductores de más: {', '.join(v.extra_hosts)}")
            if not v.program_ok:
                parts.append(f"programa: esperado '{v.expected_program or '(ninguno)'}', "
                             f"obtenido '{v.predicted_program or '(ninguno)'}'")
            lines.append(f"- {v.video_id} | " + " ; ".join(parts))
    return "\n".join(lines)
