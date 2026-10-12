"""Pruebas de duplicados de video: detección, cuál se conserva y herencia de lo ya revisado."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalogs import ContactType, Program
from app.models.contact import Contact
from app.models.guest import Guest
from app.models.ingestion import StagingContactCandidate, StagingGuestCandidate, StagingVideoSuggestion
from app.models.participation import Participation
from app.models.video import Video
from app.schemas.claude_extraction import BatchExtraction, VideoExtraction
from app.services import claude_import, duplicates
from scripts import reconcile_duplicates

T0 = datetime(2026, 7, 14, 15, 0, 0, tzinfo=timezone.utc)
DESC = "Descripción idéntica del programa"


def _video(session, yt, title="Con las Estrellas: Ana", description=DESC, minutes=0, duration=2000, **kw):
    video = Video(
        youtube_video_id=yt, title=title, description=description, source="youtube",
        published_at=T0 + timedelta(minutes=minutes), duration_seconds=duration,
        last_ingested_at=T0, **kw,
    )
    session.add(video)
    session.flush()
    return video


def _pair(session, mobile_first=True, **kw):
    """(con 📱, sin 📱): el primero que se crea es el de menor id."""
    if mobile_first:
        mobile = _video(session, "m", title="Con las Estrellas: Ana 📱", **kw)
        plain = _video(session, "p", minutes=2, **kw)
    else:
        plain = _video(session, "p", **kw)
        mobile = _video(session, "m", title="Con las Estrellas: Ana 📱", minutes=2, **kw)
    return mobile, plain


def _guest_candidate(session, video, name, status="pending", guest_id=None, conf=0.9):
    cand = StagingGuestCandidate(
        video_id=video.id, extracted_name=name, found_in_title=True, found_in_description=False,
        raw_confidence=conf, adjusted_confidence=conf, evidence=name, extraction_method="llm",
        status=status, linked_guest_id=guest_id,
    )
    session.add(cand)
    session.flush()
    return cand


def _contact_candidate(session, video, value, status="pending", contact_id=None):
    cand = StagingContactCandidate(
        video_id=video.id, type_hint="instagram", value=value, normalized_value=value,
        raw_confidence=0.7, extraction_method="regex", status=status, linked_contact_id=contact_id,
    )
    session.add(cand)
    session.flush()
    return cand


def _rows(session, model, video):
    return list(session.scalars(select(model).where(model.video_id == video.id).order_by(model.id)))


def _reviewed_video(session, video, guest_name="Ana López"):
    """Deja al video como lo deja una revisión humana: invitado, participación, contacto, programa."""
    guest = Guest(full_name=guest_name)
    kind = ContactType(name="Instagram")
    program = Program(name="Con las Estrellas")
    session.add_all([guest, kind, program])
    session.flush()
    contact = Contact(guest_id=guest.id, contact_type_id=kind.id, value="@ana", video_id=video.id)
    session.add(contact)
    session.add(Participation(guest_id=guest.id, video_id=video.id, notes="Entrevista"))
    session.flush()
    _guest_candidate(session, video, guest_name, status="accepted", guest_id=guest.id)
    _contact_candidate(session, video, "@ana", status="accepted", contact_id=contact.id)
    session.add(StagingVideoSuggestion(video_id=video.id, program_name="Con las Estrellas",
                                       host_names=[], status="accepted"))
    video.guest_status = "has_guests"
    video.program_id = program.id
    session.flush()
    return guest, contact


# --- detección --------------------------------------------------------------------------

def test_detecta_el_gemelo_aunque_solo_cambie_el_emoji(session):
    mobile, plain = _pair(session)
    assert duplicates.find_possible_duplicate(session, plain).id == mobile.id
    assert duplicates.find_possible_duplicate(session, mobile).id == plain.id


def test_no_es_duplicado_si_la_descripcion_cambia(session):
    _video(session, "a")
    other = _video(session, "b", title="Con las Estrellas: Ana 📱", description="Otra descripción", minutes=2)
    assert duplicates.find_possible_duplicate(session, other) is None


def test_no_es_duplicado_si_la_duracion_es_muy_distinta(session):
    _video(session, "a", duration=3000)
    other = _video(session, "b", title="Con las Estrellas: Ana 📱", minutes=2, duration=1500)
    assert duplicates.find_possible_duplicate(session, other) is None


def test_tolera_pocos_segundos_de_diferencia_en_la_duracion(session):
    _video(session, "a", duration=2276)      # pares reales: hasta 5 s de diferencia
    other = _video(session, "b", title="Con las Estrellas: Ana 📱", minutes=2, duration=2281)
    assert duplicates.find_possible_duplicate(session, other) is not None


def test_duracion_desconocida_o_cero_no_descarta_el_par(session):
    _video(session, "a", duration=0)
    sin_dato = _video(session, "b", title="Con las Estrellas: Ana 📱", minutes=2, duration=None)
    assert duplicates.find_possible_duplicate(session, sin_dato) is not None


def test_un_programa_semanal_con_titulo_y_descripcion_genericos_no_es_duplicado(session):
    # Caso real: "La Bruja Blanca…" se publica cada semana con la misma descripción (hashtags) y
    # duraciones casi iguales (3832 s y 3807 s). Son episodios distintos.
    _video(session, "a", title="La Bruja Blanca", description="#LaBrujaBlanca", duration=3832)
    otro = _video(session, "b", title="La Bruja Blanca", description="#LaBrujaBlanca",
                  duration=3807, minutes=60 * 24 * 7)
    assert duplicates.find_possible_duplicate(session, otro) is None


def test_no_es_duplicado_fuera_de_la_ventana_de_fechas(session):
    _video(session, "a")
    other = _video(session, "b", title="Con las Estrellas: Ana 📱", minutes=60 * 24 * 70)
    assert duplicates.find_possible_duplicate(session, other) is None


def test_elige_el_que_no_tiene_emoji_y_si_empatan_el_de_menor_id(session):
    mobile, plain = _pair(session, mobile_first=True)
    assert duplicates.choose_keeper(mobile, plain) == (plain, mobile)
    a = _video(session, "x", title="Igual")
    b = _video(session, "y", title="Igual", minutes=1)
    assert duplicates.choose_keeper(b, a) == (a, b)


# --- reconcile --------------------------------------------------------------------------

def test_reconcile_marca_los_dos_videos_y_es_idempotente(session):
    mobile, plain = _pair(session)
    first = duplicates.reconcile(session, plain)
    assert first.changed and (first.keeper_id, first.copy_id) == (plain.id, mobile.id)
    assert plain.possible_duplicate_of_video_id == mobile.id
    assert mobile.possible_duplicate_of_video_id == plain.id
    again = duplicates.reconcile(session, mobile)
    assert again.changed is False


def test_reconcile_sin_gemelo_no_hace_nada(session):
    video = _video(session, "solo")
    assert duplicates.reconcile(session, video) is None
    assert video.possible_duplicate_of_video_id is None


def test_si_ninguno_estaba_revisado_cada_uno_conserva_sus_candidatos(session):
    mobile, plain = _pair(session)
    _guest_candidate(session, mobile, "Ana")
    _guest_candidate(session, plain, "Ana")
    result = duplicates.reconcile(session, plain)
    assert result.inherited is False
    assert len(_rows(session, StagingGuestCandidate, mobile)) == 1
    assert len(_rows(session, StagingGuestCandidate, plain)) == 1


# --- herencia: llega primero el 📱 (revisado) y después el gemelo sin 📱 -------------------

def test_el_gemelo_sin_emoji_hereda_todo_lo_que_se_reviso_en_el_de_emoji(session):
    mobile, plain = _pair(session, mobile_first=True)
    guest, contact = _reviewed_video(session, mobile)
    program_id = mobile.program_id
    # el análisis propio del que llega después: nada de esto debe pedir revisión
    _guest_candidate(session, plain, "Ana López")
    _guest_candidate(session, plain, "Luis Nuevo", conf=0.6)
    _contact_candidate(session, plain, "@otro")
    session.add(StagingVideoSuggestion(video_id=plain.id, program_name="Otro", host_names=[], status="pending"))
    session.flush()

    result = duplicates.reconcile(session, plain)

    assert result.inherited and (result.keeper_id, result.copy_id) == (plain.id, mobile.id)
    assert (result.participations, result.contacts) == (1, 1)
    # la participación y el contacto final ahora cuelgan del video que se conserva
    part = session.scalars(select(Participation)).one()
    assert (part.video_id, part.guest_id, part.notes) == (plain.id, guest.id, "Entrevista")
    assert session.get(Contact, contact.id).video_id == plain.id
    # los candidatos ya revisados viajaron; los pendientes del gemelo no existen
    guests = _rows(session, StagingGuestCandidate, plain)
    assert [(g.extracted_name, g.status) for g in guests] == [("Ana López", "accepted")]
    assert [(c.value, c.status) for c in _rows(session, StagingContactCandidate, plain)] == [("@ana", "accepted")]
    assert [(s.program_name, s.status) for s in _rows(session, StagingVideoSuggestion, plain)] == [("Con las Estrellas", "accepted")]
    # el video conserva el estado de la revisión y su programa
    assert plain.guest_status == "has_guests" and plain.program_id == program_id
    # la copia queda vacía y sin revisión propia
    assert mobile.guest_status == "pending"
    for model in (StagingGuestCandidate, StagingContactCandidate, StagingVideoSuggestion, Participation):
        assert _rows(session, model, mobile) == []


def test_reconciliar_otra_vez_no_cambia_ni_borra_nada(session):
    mobile, plain = _pair(session)
    _reviewed_video(session, mobile)
    duplicates.reconcile(session, plain)
    again = duplicates.reconcile(session, plain)
    assert again.changed is False and again.inherited is False
    assert len(_rows(session, Participation, plain)) == 1
    assert len(_rows(session, StagingGuestCandidate, plain)) == 1


def test_si_el_invitado_ya_participaba_en_el_que_se_conserva_no_se_duplica(session):
    mobile, plain = _pair(session)
    guest, _ = _reviewed_video(session, mobile)
    session.add(Participation(guest_id=guest.id, video_id=plain.id))
    session.flush()
    duplicates.reconcile(session, plain)
    parts = list(session.scalars(select(Participation)))
    assert [(p.video_id, p.guest_id, p.notes) for p in parts] == [(plain.id, guest.id, "Entrevista")]


def test_lo_ya_revisado_en_el_que_se_conserva_no_se_pierde(session):
    mobile, plain = _pair(session)
    _reviewed_video(session, mobile)
    previo = _guest_candidate(session, plain, "Luis", status="rejected")
    duplicates.reconcile(session, plain)
    nombres = sorted(g.extracted_name for g in _rows(session, StagingGuestCandidate, plain))
    assert nombres == ["Ana López", "Luis"] and session.get(StagingGuestCandidate, previo.id).status == "rejected"


def test_una_copia_con_candidatos_revisados_y_pendientes_los_pasa_todos(session):
    mobile, plain = _pair(session)
    guest, _ = _reviewed_video(session, mobile)
    _contact_candidate(session, mobile, "@pendiente")      # lo dejó pendiente al revisar
    duplicates.reconcile(session, plain)
    contactos = {(c.value, c.status) for c in _rows(session, StagingContactCandidate, plain)}
    assert contactos == {("@ana", "accepted"), ("@pendiente", "pending")}


def test_sin_invitados_marcado_por_la_ingesta_no_cuenta_como_revisado(session):
    mobile, plain = _pair(session)
    mobile.guest_status = "no_guests"       # lo marcó la regla automática, nadie lo revisó
    _guest_candidate(session, plain, "Ana")
    result = duplicates.reconcile(session, plain)
    assert result.inherited is False
    assert len(_rows(session, StagingGuestCandidate, plain)) == 1


def test_sin_invitados_con_candidatos_rechazados_si_cuenta_como_revisado(session):
    mobile, plain = _pair(session)
    _guest_candidate(session, mobile, "Falso", status="rejected")
    mobile.guest_status = "no_guests"
    _guest_candidate(session, plain, "Falso")
    result = duplicates.reconcile(session, plain)
    assert result.inherited is True
    assert [(g.extracted_name, g.status) for g in _rows(session, StagingGuestCandidate, plain)] == [("Falso", "rejected")]
    assert plain.guest_status == "no_guests"


def test_las_partes_de_la_copia_pasan_a_colgar_del_que_se_conserva(session):
    mobile, plain = _pair(session)
    _reviewed_video(session, mobile)
    parte = _video(session, "parte", title="Otro", description="x", part_of_video_id=mobile.id)
    duplicates.reconcile(session, plain)
    assert session.get(Video, parte.id).part_of_video_id == plain.id


# --- herencia: el orden contrario -------------------------------------------------------

def test_llega_primero_el_original_revisado_y_despues_la_copia_con_emoji(session):
    plain = _video(session, "p")
    guest, _ = _reviewed_video(session, plain)
    mobile = _video(session, "m", title="Con las Estrellas: Ana 📱", minutes=2)
    _guest_candidate(session, mobile, "Ana López")
    result = duplicates.reconcile(session, mobile)
    assert result.inherited is False and (result.keeper_id, result.copy_id) == (plain.id, mobile.id)
    assert len(_rows(session, Participation, plain)) == 1           # el original no se toca
    assert plain.guest_status == "has_guests"


def test_sin_emoji_en_ninguno_hereda_el_de_menor_id(session):
    primero = _video(session, "a", title="Mismo título")
    segundo = _video(session, "b", title="Mismo título", minutes=1)
    _reviewed_video(session, segundo)
    result = duplicates.reconcile(session, primero)
    assert result.inherited and result.keeper_id == primero.id
    assert len(_rows(session, Participation, primero)) == 1


# --- con el importador de Claude (ruta de la carga masiva) ---------------------------------

def _extraction(video_id, *names):
    return VideoExtraction.model_validate({
        "video_id": video_id,
        "guests": [{"name": n, "confidence": 0.9, "evidence": n} for n in names],
    })


def test_import_video_detecta_el_duplicado_y_hereda_la_revision(session):
    mobile, plain = _pair(session)
    mobile.last_ingested_at = None
    plain.last_ingested_at = None
    claude_import.import_video(session, mobile, _extraction("m", "Ana López"),
                               extractor="claude_code", instructions_version="v5")
    candidate = _rows(session, StagingGuestCandidate, mobile)[0]
    guest = Guest(full_name="Ana López")
    session.add(guest)
    session.flush()
    candidate.status, candidate.linked_guest_id = "accepted", guest.id
    session.add(Participation(guest_id=guest.id, video_id=mobile.id))
    mobile.guest_status = "has_guests"
    session.flush()

    result = claude_import.import_video(session, plain, _extraction("p", "Ana López", "Luis Nuevo"),
                                        extractor="claude_code", instructions_version="v5")

    assert result.duplicate_of == mobile.id and result.inherited_review is True
    assert [(g.extracted_name, g.status) for g in _rows(session, StagingGuestCandidate, plain)] == [("Ana López", "accepted")]
    assert plain.guest_status == "has_guests"
    assert len(_rows(session, Participation, plain)) == 1


def test_import_batch_cuenta_los_videos_que_forman_parte_de_un_par(session):
    mobile, plain = _pair(session)
    mobile.last_ingested_at = None
    plain.last_ingested_at = None
    batch = BatchExtraction(instructions_version="v5",
                            videos=[_extraction("m", "Ana"), _extraction("p", "Ana")])
    summary = claude_import.import_batch(session, batch, extractor="claude_code")
    assert summary.errors == [] and summary.duplicates == 2 and summary.inherited_reviews == 0


# --- script de relleno ------------------------------------------------------------------

def test_el_script_de_relleno_marca_los_pares_sin_marcar_y_es_repetible(session):
    mobile, plain = _pair(session)
    _reviewed_video(session, mobile)
    changes = reconcile_duplicates.reconcile_all(session)
    assert len(changes) == 1 and changes[0].inherited
    assert (plain.possible_duplicate_of_video_id, mobile.possible_duplicate_of_video_id) == (mobile.id, plain.id)
    assert len(_rows(session, Participation, plain)) == 1
    assert reconcile_duplicates.reconcile_all(session) == []


# --- la regla de ocultar en la API, sin importar el orden ----------------------------------

def _titles(api_client, name):
    body = api_client.get("/staging/review/videos", params={"filter": name}).json()
    return sorted(v["title"] for v in body["items"])


def test_el_gemelo_sin_emoji_marcado_hacia_el_de_emoji_oculta_al_de_emoji(api_client, api_engine):
    with Session(api_engine) as s:
        mobile, plain = _pair(s)
        _guest_candidate(s, mobile, "Ana")
        _guest_candidate(s, plain, "Ana")
        plain.possible_duplicate_of_video_id = mobile.id       # solo en este sentido
        s.commit()
    assert _titles(api_client, "pending") == ["Con las Estrellas: Ana"]
    assert _titles(api_client, "duplicates") == ["Con las Estrellas: Ana 📱"]


def test_flujo_completo_revisas_el_de_emoji_y_el_gemelo_llega_ya_revisado(api_client, api_engine):
    # 1. llega el 📱 con su análisis y lo revisas desde la app
    with Session(api_engine) as s:
        mobile = _video(s, "m", title="Con las Estrellas: Ana 📱")
        mobile.last_ingested_at = None
        s.commit()
        mobile_id = mobile.id
        claude_import.import_video(s, mobile, _extraction("m", "Ana López"),
                                   extractor="claude_code", instructions_version="v5")
        s.commit()
        candidate_id = _rows(s, StagingGuestCandidate, mobile)[0].id
    assert api_client.post(f"/staging/review/videos/{mobile_id}/resolve", json={
        "guests": [{"candidate_id": candidate_id}],
    }).status_code == 200
    assert _titles(api_client, "reviewed") == ["Con las Estrellas: Ana 📱"]

    # 2. en el siguiente lote llega el mismo video sin 📱, con otro invitado "nuevo" en su análisis
    with Session(api_engine) as s:
        plain = _video(s, "p", minutes=2)
        plain.last_ingested_at = None
        s.commit()
        plain_id = plain.id
        claude_import.import_video(s, plain, _extraction("p", "Ana López", "Luis Nuevo"),
                                   extractor="claude_code", instructions_version="v5")
        s.commit()

    # 3. el que se conserva sale ya revisado; el 📱 se oculta; nada queda pendiente
    assert _titles(api_client, "pending") == []
    assert _titles(api_client, "reviewed") == ["Con las Estrellas: Ana"]
    assert _titles(api_client, "duplicates") == ["Con las Estrellas: Ana 📱"]
    counts = api_client.get("/staging/review/counts").json()
    assert (counts["pending"], counts["reviewed"], counts["duplicates"]) == (0, 1, 1)
    item = api_client.get("/staging/review/videos", params={"filter": "reviewed"}).json()["items"][0]
    assert item["id"] == plain_id and [p["full_name"] for p in item["participants"]] == ["Ana López"]
    assert item["guest_candidates"] == []
    copia = api_client.get("/staging/review/videos", params={"filter": "duplicates"}).json()["items"][0]
    assert copia["is_duplicate_copy"] is True and copia["possible_duplicate_of_video_id"] == plain_id
