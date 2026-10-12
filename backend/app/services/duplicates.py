"""Videos duplicados: detección, cuál se conserva y herencia de lo que ya se revisó.

El canal sube el mismo video dos veces: una con 📱 al final del título y otra sin él (título y
descripción iguales, segundos o minutos de diferencia, misma duración). Reglas:

- Se conserva el que NO tiene 📱; si los dos son iguales en eso, el de menor id. La otra es la
  "copia": no se borra, pero sale de la revisión y no cuenta como nada.
- No importa cuál llegó primero. Si la copia ya estaba revisada (invitados, contactos, programa…)
  y después llega el video que se conserva, éste HEREDA todo lo revisado y no vuelve a pedir
  revisión; si la copia no se había tocado, el que se conserva se revisa normal.
- Los dos videos quedan marcados entre sí (`possible_duplicate_of_video_id`), así la regla de
  "copia" (`staging_review._duplicate_copy_clause`) funciona igual sin importar el orden.

`reconcile` es el único punto de entrada: lo llaman las dos rutas de ingesta (el pipeline y el
importador de Claude) y el script de relleno `scripts/reconcile_duplicates.py`. No hace commit.
"""
import logging
import unicodedata
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, exists, select, update
from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.ingestion import StagingContactCandidate, StagingGuestCandidate, StagingVideoSuggestion
from app.models.participation import Participation
from app.models.video import Video
from app.services.catalogs import normalize_name

logger = logging.getLogger(__name__)

MOBILE_MARK = "📱"
# Ventana de `published_at` para considerar dos videos el mismo. Evidencia real (17 pares de la BD):
# la copia se sube con segundos a 12 horas de diferencia. Un programa semanal con descripción
# genérica (solo hashtags) repite título y descripción cada 7 días: eso NO es un duplicado.
DUPLICATE_MAX_TIMEDELTA = timedelta(days=3)
# Dos duraciones conocidas se consideran iguales si difieren poco (en los 17 pares reales: 0-5 s;
# dos episodios distintos del mismo programa semanal difirieron 25 s).
DURATION_TOLERANCE_SECONDS = 10
DURATION_TOLERANCE_RATIO = 0.003


@dataclass
class ReconcileResult:
    """Qué hizo `reconcile` con un video (solo ids y conteos)."""

    twin_id: int
    keeper_id: int
    copy_id: int
    changed: bool = False          # se marcó algún video o se heredó revisión
    inherited: bool = False        # el que se conserva heredó lo revisado de la copia
    participations: int = 0
    contacts: int = 0
    staging_rows: int = 0


def normalize_for_duplicate_check(text: str) -> str:
    """`normalize_name` + quita emoji/símbolos (categoría Unicode "So").

    Caso real: el canal sube el mismo video dos veces con el único cambio de un emoji al final del
    título (p. ej. "...Arween Tarot" vs "...Arween Tarot 📱"), con la descripción idéntica byte por
    byte. `normalize_name` (pensado para nombres de catálogo) no toca emoji, así que sin esto esos
    pares nunca se detectaban como duplicados.
    """
    without_symbols = "".join(c for c in text if unicodedata.category(c) != "So")
    return normalize_name(without_symbols)


def _similar_duration(a: int | None, b: int | None) -> bool:
    """Sin duración conocida (None o 0: YouTube aún no la fijaba) no se puede descartar al par."""
    if not a or not b:
        return True
    return abs(a - b) <= max(DURATION_TOLERANCE_SECONDS, DURATION_TOLERANCE_RATIO * max(a, b))


def find_possible_duplicate(db: Session, video: Video) -> Video | None:
    """Otro video con título+descripción normalizados iguales, duración parecida y `published_at`
    cercano."""
    if video.published_at is None:
        return None
    title_key = normalize_for_duplicate_check(video.title)
    description_key = normalize_for_duplicate_check(video.description or "")
    candidates = db.scalars(
        select(Video)
        .where(
            Video.id != video.id,
            Video.published_at.is_not(None),
            Video.published_at >= video.published_at - DUPLICATE_MAX_TIMEDELTA,
            Video.published_at <= video.published_at + DUPLICATE_MAX_TIMEDELTA,
        )
        .order_by(Video.published_at, Video.id)
    )
    for other in candidates:
        if (
            normalize_for_duplicate_check(other.title) == title_key
            and normalize_for_duplicate_check(other.description or "") == description_key
            and _similar_duration(video.duration_seconds, other.duration_seconds)
        ):
            return other
    return None


def choose_keeper(a: Video, b: Video) -> tuple[Video, Video]:
    """(el que se conserva, la copia): el que no tiene 📱; si empatan, el de menor id."""
    a_mobile, b_mobile = MOBILE_MARK in a.title, MOBILE_MARK in b.title
    if a_mobile != b_mobile:
        return (b, a) if a_mobile else (a, b)
    return (a, b) if a.id < b.id else (b, a)


def has_review_work(db: Session, video: Video) -> bool:
    """El video ya pasó por una revisión humana: tiene invitados confirmados, participaciones o
    candidatos aceptados/rechazados. "Sin invitados" por sí solo no cuenta: también lo marca la
    ingesta automática (es un candidato), y sin otra huella no se puede distinguir de un humano."""
    if video.guest_status == "has_guests":
        return True
    if db.scalar(select(exists().where(Participation.video_id == video.id))):
        return True
    return any(
        db.scalar(select(exists().where(model.video_id == video.id, model.status != "pending")))
        for model in (StagingGuestCandidate, StagingContactCandidate, StagingVideoSuggestion)
    )


def _move_participations(db: Session, copy: Video, keeper: Video) -> int:
    moved = 0
    for participation in db.scalars(select(Participation).where(Participation.video_id == copy.id)).all():
        already = db.scalar(select(Participation).where(
            Participation.video_id == keeper.id, Participation.guest_id == participation.guest_id))
        if already is None:
            participation.video_id = keeper.id
            moved += 1
        else:                       # el invitado ya participaba en el que se conserva: no se duplica
            if participation.notes and not already.notes:
                already.notes = participation.notes
            db.delete(participation)
    db.flush()
    return moved


def _move_staging_rows(db: Session, copy: Video, keeper: Video) -> int:
    """El que se conserva cambia sus candidatos PENDIENTES (los de su propio análisis) por los de la
    copia, ya revisados. Si él también tenía algo revisado, se conserva y se suma lo de la copia."""
    for model in (StagingContactCandidate, StagingGuestCandidate, StagingVideoSuggestion):
        db.execute(delete(model).where(model.video_id == keeper.id, model.status == "pending"))
    db.flush()
    moved = 0
    if db.scalar(select(exists().where(StagingVideoSuggestion.video_id == keeper.id))):
        db.execute(delete(StagingVideoSuggestion).where(StagingVideoSuggestion.video_id == copy.id))
    for model in (StagingGuestCandidate, StagingContactCandidate, StagingVideoSuggestion):
        moved += db.execute(update(model).where(model.video_id == copy.id).values(video_id=keeper.id)).rowcount or 0
    db.flush()
    return moved


def inherit_review(db: Session, copy: Video, keeper: Video) -> ReconcileResult:
    """Pasa todo lo revisado de la copia al video que se conserva. La copia queda sin revisión."""
    result = ReconcileResult(twin_id=copy.id, keeper_id=keeper.id, copy_id=copy.id, inherited=True, changed=True)
    result.participations = _move_participations(db, copy, keeper)
    result.contacts = db.execute(
        update(Contact).where(Contact.video_id == copy.id).values(video_id=keeper.id)
    ).rowcount or 0
    result.staging_rows = _move_staging_rows(db, copy, keeper)

    for field in ("program_id", "video_type_id", "event_borough_id"):
        if getattr(keeper, field) is None and getattr(copy, field) is not None:
            setattr(keeper, field, getattr(copy, field))
    if keeper.guest_status == "pending" and copy.guest_status != "pending":
        keeper.guest_status = copy.guest_status
    if keeper.part_of_video_id == copy.id:
        keeper.part_of_video_id = None
    if keeper.part_of_video_id is None and copy.part_of_video_id not in (None, keeper.id):
        keeper.part_of_video_id = copy.part_of_video_id
    db.execute(update(Video).where(Video.part_of_video_id == copy.id, Video.id != keeper.id)
               .values(part_of_video_id=keeper.id))
    copy.guest_status = "pending"       # ya no tiene nada propio: reconciliar de nuevo no hace nada
    db.flush()
    db.expire_all()
    return result


def reconcile(db: Session, video: Video) -> ReconcileResult | None:
    """Detecta el gemelo de `video`, deja a los dos marcados y, si la copia ya estaba revisada, pasa
    esa revisión al video que se conserva. Idempotente. No hace commit."""
    where = "app.services.duplicates.reconcile"
    twin = find_possible_duplicate(db, video)
    if twin is None:
        return None
    keeper, copy = choose_keeper(video, twin)
    changed = False
    if video.possible_duplicate_of_video_id != twin.id:
        video.possible_duplicate_of_video_id = twin.id
        changed = True
    if twin.possible_duplicate_of_video_id is None:
        twin.possible_duplicate_of_video_id = video.id
        changed = True
    db.flush()

    if has_review_work(db, copy):
        result = inherit_review(db, copy, keeper)
        result.twin_id = twin.id
        logger.info(
            "[%s] Video %s es copia del %s y ya estaba revisado: hereda %s participaciones, %s "
            "contactos y %s candidatos", where, copy.id, keeper.id, result.participations,
            result.contacts, result.staging_rows,
        )
        return result
    if changed:
        logger.info("[%s] Videos %s y %s marcados como duplicados (se conserva el %s)",
                    where, video.id, twin.id, keeper.id)
    return ReconcileResult(twin_id=twin.id, keeper_id=keeper.id, copy_id=copy.id, changed=changed)
