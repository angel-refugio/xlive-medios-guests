"""Pruebas de la revisión por video de Staging Review (lista, contadores y resolución)."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.catalogs import ContactRelationship, ContactType, Host, Program
from app.models.contact import Contact
from app.models.guest import Guest
from app.models.ingestion import (
    StagingContactCandidate, StagingGuestCandidate, StagingVideoSuggestion,
)
from app.models.participation import Participation
from app.models.video import Video

NOW = datetime(2024, 5, 1, tzinfo=timezone.utc)


def _seed_video(
    engine, yt="v1", title="Video 1", ingested=True, status="pending", published=None,
    duplicate_of=None, guests=(), contacts=(), duration=None,
) -> tuple[int, list[int]]:
    """Crea un video con candidatos pendientes. `guests`: (nombre, confianza); `contacts`:
    (tipo, valor). Devuelve (video_id, ids de candidatos de invitado)."""
    with Session(engine) as s:
        video = Video(
            youtube_video_id=yt, title=title, source="youtube", guest_status=status,
            last_ingested_at=NOW if ingested else None, published_at=published,
            possible_duplicate_of_video_id=duplicate_of, duration_seconds=duration,
        )
        s.add(video)
        s.commit()
        candidates = [
            StagingGuestCandidate(
                video_id=video.id, extracted_name=name, found_in_title=True,
                found_in_description=False, raw_confidence=conf, adjusted_confidence=conf,
                evidence=name, extraction_method="regex",
            )
            for name, conf in guests
        ]
        s.add_all(candidates)
        s.add_all([
            StagingContactCandidate(
                video_id=video.id, type_hint=hint, value=value, raw_confidence=0.6,
                extraction_method="regex",
            )
            for hint, value in contacts
        ])
        s.commit()
        return video.id, [c.id for c in candidates]


def _status(engine, candidate_id) -> str:
    with Session(engine) as s:
        return s.get(StagingGuestCandidate, candidate_id).status


def test_requires_authentication(api_client):
    anonymous = TestClient(api_client.app)
    assert anonymous.get("/staging/review/videos").status_code == 401
    assert anonymous.get("/staging/review/counts").status_code == 401
    assert anonymous.post("/staging/review/videos/1/resolve", json={}).status_code == 401


# --- lista y contadores ----------------------------------------------------------------

def test_lists_ingested_videos_with_pending_candidates_by_confidence(api_client, api_engine):
    _seed_video(api_engine, "v1", "Con candidatos", guests=[("Baja", 0.3), ("Alta", 0.9)],
                contacts=[("instagram", "@alta")])
    _seed_video(api_engine, "v2", "No ingerido", ingested=False, guests=[("Otro", 0.5)])

    body = api_client.get("/staging/review/videos").json()
    assert body["total"] == 1
    video = body["items"][0]
    assert video["title"] == "Con candidatos"
    assert [g["extracted_name"] for g in video["guest_candidates"]] == ["Alta", "Baja"]
    assert video["contact_candidates"] == [{
        "id": video["contact_candidates"][0]["id"], "type_hint": "instagram", "value": "@alta",
        "relationship_name": None, "evidence": None, "doubtful": False, "doubtful_reason": None,
        "guest_name": None, "possible_guest_name": None,
        "guest_candidate_id": None, "suggested_contact_type_id": None,
    }]
    assert {"adjusted_confidence", "evidence", "is_possible_group"} <= set(video["guest_candidates"][0])


def test_counts_per_filter(api_client, api_engine):
    original, _ = _seed_video(api_engine, "v1", "Con invitados", guests=[("Ana", 0.5)])
    _seed_video(api_engine, "v2", "Solo contacto", contacts=[("correo", "a@b.com")])
    _seed_video(api_engine, "v3", "Sin candidatos")
    _seed_video(api_engine, "v4", "Sin invitados", status="no_guests")
    _seed_video(api_engine, "v5", "Duplicado", duplicate_of=original, guests=[("Ana", 0.5)])

    assert api_client.get("/staging/review/counts").json() == {
        # "Duplicado" es la copia de "Con invitados": no cuenta en nada salvo en duplicados.
        "pending": 1, "with_contacts": 1, "doubtful_contacts": 0, "no_candidates": 1,
        "no_guests": 1, "short": 0, "reviewed": 0, "duplicates": 1,
    }


def test_revisados_lista_los_videos_con_invitados_aceptados_y_sus_participantes(api_client, api_engine):
    video_id, (g1,) = _seed_video(api_engine, "v1", "Con Ana", guests=[("Ana", 0.9)])
    _seed_video(api_engine, "v2", "Sin revisar", guests=[("Luis", 0.9)])
    _seed_video(api_engine, "v3", "Sin invitados", status="no_guests")
    assert _titles(api_client, "reviewed") == []

    assert _resolve(api_client, video_id, guests=[{"candidate_id": g1}]).status_code == 200

    counts = api_client.get("/staging/review/counts").json()
    assert counts["reviewed"] == 1 and counts["pending"] == 1 and counts["no_guests"] == 1
    body = api_client.get("/staging/review/videos", params={"filter": "reviewed"}).json()
    assert [v["title"] for v in body["items"]] == ["Con Ana"]
    assert [p["full_name"] for p in body["items"][0]["participants"]] == ["Ana"]
    assert body["items"][0]["guest_candidates"] == []                 # ya no quedan candidatos


def test_los_videos_de_menos_de_un_minuto_van_al_filtro_cortos_y_salen_de_los_demas(api_client, api_engine):
    _seed_video(api_engine, "v1", "Intro 15 s", duration=15, guests=[("Ana", 0.9)])
    _seed_video(api_engine, "v2", "Sin duración fija", duration=0, guests=[("Luis", 0.9)])
    _seed_video(api_engine, "v3", "Justo bajo el corte", duration=59, contacts=[("email", "a@b.com")])
    _seed_video(api_engine, "v4", "En el corte", duration=60, guests=[("Eva", 0.9)])
    _seed_video(api_engine, "v5", "Largo", duration=1340, guests=[("Pía", 0.9)])
    _seed_video(api_engine, "v6", "Sin duración guardada", duration=None, guests=[("Teo", 0.9)])

    assert _titles(api_client, "short") == ["Intro 15 s", "Justo bajo el corte", "Sin duración fija"]
    assert _titles(api_client, "pending") == ["En el corte", "Largo", "Sin duración guardada"]
    assert _titles(api_client, "with_contacts") == []            # su contacto se ve en Cortos, no aquí
    counts = api_client.get("/staging/review/counts").json()
    assert counts["short"] == 3 and counts["pending"] == 3 and counts["with_contacts"] == 0


def test_un_corto_conserva_sus_candidatos_en_el_filtro_cortos(api_client, api_engine):
    _seed_video(api_engine, "v1", "Intro", duration=15, guests=[("Ana", 0.9)], contacts=[("email", "a@b.com")])
    video = api_client.get("/staging/review/videos", params={"filter": "short"}).json()["items"][0]
    assert [g["extracted_name"] for g in video["guest_candidates"]] == ["Ana"]
    assert len(video["contact_candidates"]) == 1


def test_al_marcar_un_corto_sin_invitados_deja_de_contar_como_corto_pendiente(api_client, api_engine):
    video_id, _ = _seed_video(api_engine, "v1", "Intro", duration=15, guests=[("Ana", 0.9)])
    assert api_client.get("/staging/review/counts").json()["short"] == 1

    assert _resolve(api_client, video_id, no_guests=True).status_code == 200

    counts = api_client.get("/staging/review/counts").json()
    assert counts["short"] == 0 and counts["no_guests"] == 1     # ahora es un "sin invitados" más
    assert _titles(api_client, "no_guests") == ["Intro"]


def test_la_copia_con_celular_de_un_corto_no_aparece_en_cortos(api_client, api_engine):
    original, _ = _seed_video(api_engine, "v1", "Intro", duration=15, guests=[("Ana", 0.9)])
    copia, _ = _seed_video(api_engine, "v2", "Intro 📱", duration=14, guests=[("Ana", 0.9)],
                           duplicate_of=original)
    with Session(api_engine) as s:
        s.get(Video, original).possible_duplicate_of_video_id = copia
        s.commit()
    assert _titles(api_client, "short") == ["Intro"]


def _titles(api_client, name):
    body = api_client.get("/staging/review/videos", params={"filter": name}).json()
    return sorted(v["title"] for v in body["items"])


def test_de_un_par_con_celular_se_conserva_el_que_no_lo_tiene(api_client, api_engine):
    normal, _ = _seed_video(api_engine, "v1", "Con las Estrellas", guests=[("Ana", 0.5)])
    movil, _ = _seed_video(api_engine, "v2", "Con las Estrellas 📱", guests=[("Ana", 0.5)],
                           duplicate_of=normal)
    with Session(api_engine) as s:   # la ingesta los marca entre sí
        s.get(Video, normal).possible_duplicate_of_video_id = movil
        s.commit()

    assert _titles(api_client, "pending") == ["Con las Estrellas"]
    assert _titles(api_client, "duplicates") == ["Con las Estrellas 📱"]
    counts = api_client.get("/staging/review/counts").json()
    assert counts["pending"] == 1 and counts["duplicates"] == 1


def test_de_un_par_igual_se_conserva_el_de_menor_id(api_client, api_engine):
    primero, _ = _seed_video(api_engine, "v1", "Mismo título", guests=[("Ana", 0.5)])
    segundo, _ = _seed_video(api_engine, "v2", "Mismo título", guests=[("Ana", 0.5)],
                             duplicate_of=primero)
    with Session(api_engine) as s:
        s.get(Video, primero).possible_duplicate_of_video_id = segundo
        s.commit()

    body = api_client.get("/staging/review/videos").json()
    assert [v["id"] for v in body["items"]] == [primero]
    assert body["items"][0]["is_duplicate_copy"] is False   # el original no lleva el aviso
    copies = api_client.get("/staging/review/videos", params={"filter": "duplicates"}).json()
    assert [v["id"] for v in copies["items"]] == [segundo]
    assert copies["items"][0]["is_duplicate_copy"] is True


def test_la_copia_no_se_borra_y_conserva_sus_candidatos(api_client, api_engine):
    original, _ = _seed_video(api_engine, "v1", "Original", guests=[("Ana", 0.5)])
    copia, candidates = _seed_video(api_engine, "v2", "Original 📱", guests=[("Ana", 0.5)],
                                    duplicate_of=original)
    with Session(api_engine) as s:
        s.get(Video, original).possible_duplicate_of_video_id = copia
        s.commit()
    assert _status(api_engine, candidates[0]) == "pending"   # sigue ahí, solo no se muestra
    assert api_client.get(f"/videos/{copia}").status_code == 200


def test_un_duplicado_marcado_solo_en_un_sentido_tambien_oculta_la_copia(api_client, api_engine):
    original, _ = _seed_video(api_engine, "v1", "Serie: Uno", guests=[("Ana", 0.5)])
    _seed_video(api_engine, "v2", "Serie: Uno 📱", guests=[("Ana", 0.5)], duplicate_of=original)
    assert _titles(api_client, "pending") == ["Serie: Uno"]


def _mark_contacts(engine, video_id, **fields) -> None:
    with Session(engine) as s:
        for contact in s.scalars(select(StagingContactCandidate).where(
                StagingContactCandidate.video_id == video_id)):
            for name, value in fields.items():
                setattr(contact, name, value)
        s.commit()


def test_doubtful_contacts_filter_counts_and_lists_only_pending_doubtful(api_client, api_engine):
    dudoso, _ = _seed_video(api_engine, "v1", "Dudoso", contacts=[("contacto", "a@b.com")])
    _seed_video(api_engine, "v2", "Normal", contacts=[("correo", "c@d.com")])
    cerrado, _ = _seed_video(api_engine, "v3", "Dudoso ya revisado", contacts=[("correo", "e@f.com")])
    _mark_contacts(api_engine, dudoso, doubtful=True, doubtful_reason="tipo no registrado",
                   relationship_name="manager", evidence="Contrataciones: a@b.com",
                   guest_name="Ana", possible_guest_name="Luis")
    _mark_contacts(api_engine, cerrado, doubtful=True, status="rejected")

    counts = api_client.get("/staging/review/counts").json()
    assert counts["doubtful_contacts"] == 1 and counts["with_contacts"] == 2

    body = api_client.get("/staging/review/videos", params={"filter": "doubtful_contacts"}).json()
    assert [v["title"] for v in body["items"]] == ["Dudoso"]
    contact = body["items"][0]["contact_candidates"][0]
    assert contact["doubtful"] is True and contact["doubtful_reason"] == "tipo no registrado"
    assert contact["relationship_name"] == "manager"
    assert contact["evidence"] == "Contrataciones: a@b.com"
    assert (contact["guest_name"], contact["possible_guest_name"]) == ("Ana", "Luis")


def test_each_filter_returns_its_videos(api_client, api_engine):
    original, _ = _seed_video(api_engine, "v1", "Con invitados", guests=[("Ana", 0.5)])
    _seed_video(api_engine, "v2", "Solo contacto", contacts=[("correo", "a@b.com")])
    _seed_video(api_engine, "v3", "Sin candidatos")
    _seed_video(api_engine, "v4", "Sin invitados", status="no_guests")
    _seed_video(api_engine, "v5", "Duplicado", duplicate_of=original)

    def titles(name):
        return sorted(v["title"] for v in api_client.get("/staging/review/videos", params={"filter": name}).json()["items"])

    assert titles("pending") == ["Con invitados"]
    assert titles("with_contacts") == ["Solo contacto"]
    assert titles("no_candidates") == ["Sin candidatos"]   # "Duplicado" es una copia: no se revisa
    assert titles("no_guests") == ["Sin invitados"]
    assert titles("duplicates") == ["Duplicado"]


def test_no_candidates_excludes_videos_with_pending_contacts_and_closed_ones(api_client, api_engine):
    _seed_video(api_engine, "v1", "Solo contacto", contacts=[("correo", "a@b.com")])
    _seed_video(api_engine, "v2", "Ya con invitados", status="has_guests")
    _seed_video(api_engine, "v3", "Vacío")
    titles = [v["title"] for v in api_client.get(
        "/staging/review/videos", params={"filter": "no_candidates"}).json()["items"]]
    assert titles == ["Vacío"]


def test_search_filters_by_title_and_counts_respect_it(api_client, api_engine):
    _seed_video(api_engine, "v1", "Rock y Cultura", guests=[("Ana", 0.5)])
    _seed_video(api_engine, "v2", "Deportes", guests=[("Luis", 0.5)])
    body = api_client.get("/staging/review/videos", params={"q": "rock"}).json()
    assert [v["title"] for v in body["items"]] == ["Rock y Cultura"]
    assert api_client.get("/staging/review/counts", params={"q": "rock"}).json()["pending"] == 1


def test_orders_by_publication_date_and_paginates(api_client, api_engine):
    for i in range(3):
        _seed_video(api_engine, f"v{i}", f"Video {i}", guests=[("Ana", 0.5)],
                    published=datetime(2024, 1, 1 + i, tzinfo=timezone.utc))
    page1 = api_client.get("/staging/review/videos", params={"page_size": 2}).json()
    assert page1["total"] == 3
    assert [v["title"] for v in page1["items"]] == ["Video 2", "Video 1"]
    page2 = api_client.get("/staging/review/videos", params={"page_size": 2, "page": 2}).json()
    assert [v["title"] for v in page2["items"]] == ["Video 0"]


def test_unknown_filter_is_rejected(api_client):
    assert api_client.get("/staging/review/videos", params={"filter": "otro"}).status_code == 422


# --- resolve: aceptar -----------------------------------------------------------------

def test_resolve_accepts_edited_names_creating_guests_and_participations(api_client, api_engine):
    video_id, (c1, c2) = _seed_video(api_engine, guests=[("Ana Lopes", 0.9), ("Luis", 0.5)])
    response = api_client.post(f"/staging/review/videos/{video_id}/resolve", json={
        "guests": [{"candidate_id": c1, "full_name": "Ana López"}, {"candidate_id": c2}],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["guest_status"] == "has_guests" and len(body["accepted_guest_ids"]) == 2

    with Session(api_engine) as s:
        assert sorted(g.full_name for g in s.scalars(select(Guest))) == ["Ana López", "Luis"]
        assert len(s.scalars(select(Participation)).all()) == 2
        assert s.get(Video, video_id).guest_status == "has_guests"
    assert _status(api_engine, c1) == "accepted"
    assert api_client.get("/staging/review/counts").json()["pending"] == 0


def test_resolve_links_the_guest_with_the_same_name_instead_of_duplicating(api_client, api_engine):
    with Session(api_engine) as s:
        s.add(Guest(full_name="Karimm Kury"))
        s.commit()
    video_id, (c1,) = _seed_video(api_engine, guests=[("KARIMM KURY", 0.9)])
    api_client.post(f"/staging/review/videos/{video_id}/resolve", json={"guests": [{"candidate_id": c1}]})
    with Session(api_engine) as s:
        assert [g.full_name for g in s.scalars(select(Guest))] == ["Karimm Kury"]
        assert len(s.scalars(select(Participation)).all()) == 1


def test_resolve_does_not_link_by_similar_name_only(api_client, api_engine):
    with Session(api_engine) as s:
        s.add(Guest(full_name="Ana López García"))
        s.commit()
    video_id, (c1,) = _seed_video(api_engine, guests=[("Ana López", 0.9)])
    api_client.post(f"/staging/review/videos/{video_id}/resolve", json={"guests": [{"candidate_id": c1}]})
    with Session(api_engine) as s:
        assert len(s.scalars(select(Guest)).all()) == 2


def test_resolve_with_explicit_existing_guest(api_client, api_engine):
    with Session(api_engine) as s:
        guest = Guest(full_name="Otro Nombre")
        s.add(guest)
        s.commit()
        guest_id = guest.id
    video_id, (c1,) = _seed_video(api_engine, guests=[("Alias", 0.9)])
    body = api_client.post(f"/staging/review/videos/{video_id}/resolve", json={
        "guests": [{"candidate_id": c1, "existing_guest_id": guest_id}],
    }).json()
    assert body["accepted_guest_ids"] == [guest_id]


# --- resolve: quitar, agregar, sin invitados --------------------------------------------

def test_resolve_rejects_removed_candidates_and_adds_manual_guests(api_client, api_engine):
    video_id, (keep, drop) = _seed_video(api_engine, guests=[("Ana", 0.9), ("Novedades", 0.4)])
    body = api_client.post(f"/staging/review/videos/{video_id}/resolve", json={
        "guests": [{"candidate_id": keep}], "reject_candidate_ids": [drop],
        "added_guests": [{"full_name": "  Luis   Pérez "}],
    }).json()
    assert body["rejected_count"] == 1 and len(body["accepted_guest_ids"]) == 2
    assert _status(api_engine, drop) == "rejected"
    with Session(api_engine) as s:
        assert sorted(g.full_name for g in s.scalars(select(Guest))) == ["Ana", "Luis Pérez"]


def test_resolve_all_rejected_leaves_the_video_pending_and_moves_it_to_no_candidates(api_client, api_engine):
    video_id, (c1,) = _seed_video(api_engine, guests=[("Novedades", 0.4)])
    body = api_client.post(f"/staging/review/videos/{video_id}/resolve", json={"reject_candidate_ids": [c1]}).json()
    assert body["guest_status"] == "pending"
    counts = api_client.get("/staging/review/counts").json()
    assert counts["pending"] == 0 and counts["no_candidates"] == 1


def test_resolve_no_guests_rejects_what_is_left_and_marks_the_video(api_client, api_engine):
    video_id, (c1, c2) = _seed_video(api_engine, guests=[("Especial Drama", 0.4), ("Otro", 0.3)])
    body = api_client.post(f"/staging/review/videos/{video_id}/resolve", json={"no_guests": True}).json()
    assert body["guest_status"] == "no_guests" and body["rejected_count"] == 2
    assert _status(api_engine, c1) == _status(api_engine, c2) == "rejected"
    assert api_client.get("/staging/review/counts").json()["no_guests"] == 1


def test_resolve_no_guests_contradicts_accepting_or_adding(api_client, api_engine):
    video_id, (c1,) = _seed_video(api_engine, guests=[("Ana", 0.9)])
    url = f"/staging/review/videos/{video_id}/resolve"
    assert api_client.post(url, json={"no_guests": True, "guests": [{"candidate_id": c1}]}).status_code == 422
    assert api_client.post(url, json={"no_guests": True, "added_guests": [{"full_name": "Luis"}]}).status_code == 422
    assert _status(api_engine, c1) == "pending"  # no se tocó nada


# --- resolve: validaciones ---------------------------------------------------------------

def test_resolve_validates_before_writing_anything(api_client, api_engine):
    video_id, (c1,) = _seed_video(api_engine, "v1", guests=[("Ana", 0.9)])
    _, (foreign,) = _seed_video(api_engine, "v2", "Otro video", guests=[("Luis", 0.9)])
    url = f"/staging/review/videos/{video_id}/resolve"

    response = api_client.post(url, json={"guests": [{"candidate_id": c1}, {"candidate_id": foreign}]})
    assert response.status_code == 422 and "no pertenece" in response.json()["detail"]
    assert _status(api_engine, c1) == "pending"  # el válido tampoco se aceptó
    with Session(api_engine) as s:
        assert s.scalars(select(Guest)).all() == []


def test_resolve_error_codes(api_client, api_engine):
    video_id, (c1,) = _seed_video(api_engine, guests=[("Ana", 0.9)])
    url = f"/staging/review/videos/{video_id}/resolve"
    assert api_client.post("/staging/review/videos/999/resolve", json={}).status_code == 404
    assert api_client.post(url, json={"guests": [{"candidate_id": 999}]}).status_code == 404
    assert api_client.post(url, json={"guests": [{"candidate_id": c1, "existing_guest_id": 999}]}).status_code == 404
    both = {"guests": [{"candidate_id": c1}], "reject_candidate_ids": [c1]}
    assert api_client.post(url, json=both).status_code == 422
    assert api_client.post(url, json={"added_guests": [{"full_name": "   "}]}).status_code == 422

    assert api_client.post(url, json={"guests": [{"candidate_id": c1}]}).status_code == 200
    assert api_client.post(url, json={"guests": [{"candidate_id": c1}]}).status_code == 409  # ya revisado


def test_resolve_with_nothing_changes_nothing(api_client, api_engine):
    video_id, (c1,) = _seed_video(api_engine, guests=[("Ana", 0.9)])
    body = api_client.post(f"/staging/review/videos/{video_id}/resolve", json={}).json()
    assert body == {
        "video_id": video_id, "guest_status": "pending", "accepted_guest_ids": [],
        "rejected_count": 0, "program_id": None, "host_ids": [],
        "accepted_contact_ids": [], "rejected_contact_count": 0, "added_contact_ids": [],
    }
    assert _status(api_engine, c1) == "pending"


# --- contactos dentro de la resolución del video ---------------------------------------------

def _seed_types(engine, *names) -> dict[str, int]:
    with Session(engine) as s:
        types = [ContactType(name=n) for n in names]
        relation = ContactRelationship(name="manager")
        s.add_all([*types, relation])
        s.commit()
        return {**{t.name: t.id for t in types}, "_manager": relation.id}


def _contact_ids(engine, video_id) -> list[int]:
    with Session(engine) as s:
        return list(s.scalars(select(StagingContactCandidate.id)
                              .where(StagingContactCandidate.video_id == video_id)
                              .order_by(StagingContactCandidate.id)))


def _contact_status(engine, candidate_id) -> str:
    with Session(engine) as s:
        return s.get(StagingContactCandidate, candidate_id).status


def _resolve(api_client, video_id, **body):
    return api_client.post(f"/staging/review/videos/{video_id}/resolve", json=body)


def test_resolve_acepta_el_contacto_y_lo_atribuye_al_invitado_aceptado(api_client, api_engine):
    types = _seed_types(api_engine, "Correo")
    video_id, (g1,) = _seed_video(api_engine, guests=[("Ana", 0.9)], contacts=[("email", "ana@mail.com")])
    (c1,) = _contact_ids(api_engine, video_id)
    _mark_contacts(api_engine, video_id, evidence="Contacto: ana@mail.com")

    body = _resolve(api_client, video_id, guests=[{"candidate_id": g1}], contacts=[{
        "candidate_id": c1, "contact_type_id": types["Correo"], "relationship_id": types["_manager"],
        "guest_candidate_id": g1,
    }]).json()

    assert len(body["accepted_contact_ids"]) == 1 and body["rejected_contact_count"] == 0
    with Session(api_engine) as s:
        contact = s.get(Contact, body["accepted_contact_ids"][0])
        assert contact.guest_id == body["accepted_guest_ids"][0]
        assert (contact.value, contact.source, contact.verified) == ("ana@mail.com", "video_description", False)
        assert contact.relationship_id == types["_manager"]
        assert (contact.video_id, contact.evidence) == (video_id, "Contacto: ana@mail.com")
    assert _contact_status(api_engine, c1) == "accepted"


def test_resolve_atribuye_el_contacto_a_un_invitado_agregado_a_mano(api_client, api_engine):
    types = _seed_types(api_engine, "Celular")
    video_id, _ = _seed_video(api_engine, contacts=[("telefono", "5512345678")])
    (c1,) = _contact_ids(api_engine, video_id)
    body = _resolve(api_client, video_id, added_guests=[{"full_name": "Luis Pérez"}], contacts=[{
        "candidate_id": c1, "contact_type_id": types["Celular"], "added_guest_name": "luis perez",
    }]).json()
    with Session(api_engine) as s:
        assert s.get(Contact, body["accepted_contact_ids"][0]).guest_id == body["accepted_guest_ids"][0]


def test_resolve_asigna_un_contacto_pendiente_a_un_invitado_existente(api_client, api_engine):
    types = _seed_types(api_engine, "Correo")
    video_id, _ = _seed_video(api_engine, status="has_guests", contacts=[("email", "a@b.com")])
    (c1,) = _contact_ids(api_engine, video_id)
    with Session(api_engine) as s:
        guest = Guest(full_name="Ana")
        s.add(guest)
        s.commit()
        guest_id = guest.id
    resp = _resolve(api_client, video_id, contacts=[{
        "candidate_id": c1, "contact_type_id": types["Correo"], "existing_guest_id": guest_id,
    }])
    assert resp.status_code == 200
    with Session(api_engine) as s:
        assert s.get(Contact, resp.json()["accepted_contact_ids"][0]).guest_id == guest_id


def test_resolve_rechaza_los_contactos_descartados_y_deja_pendientes_los_no_mencionados(api_client, api_engine):
    video_id, _ = _seed_video(api_engine, contacts=[("email", "a@b.com"), ("telefono", "5511111111"), ("url", "http://x.com")])
    c1, c2, c3 = _contact_ids(api_engine, video_id)
    body = _resolve(api_client, video_id, reject_contact_ids=[c1]).json()
    assert body["rejected_contact_count"] == 1
    assert [_contact_status(api_engine, c) for c in (c1, c2, c3)] == ["rejected", "pending", "pending"]


def test_resolve_si_el_invitado_del_contacto_no_se_acepta_no_escribe_nada(api_client, api_engine):
    types = _seed_types(api_engine, "Correo")
    video_id, (g1, g2) = _seed_video(api_engine, guests=[("Ana", 0.9), ("Luis", 0.8)],
                                      contacts=[("email", "a@b.com")])
    (c1,) = _contact_ids(api_engine, video_id)
    resp = _resolve(api_client, video_id, guests=[{"candidate_id": g1}], reject_candidate_ids=[g2], contacts=[{
        "candidate_id": c1, "contact_type_id": types["Correo"], "guest_candidate_id": g2,
    }])
    assert resp.status_code == 422
    assert [_status(api_engine, g) for g in (g1, g2)] == ["pending", "pending"]   # nada a medias
    assert _contact_status(api_engine, c1) == "pending"


def test_resolve_valida_los_contactos_antes_de_escribir(api_client, api_engine):
    types = _seed_types(api_engine, "Correo")
    video_id, (g1,) = _seed_video(api_engine, guests=[("Ana", 0.9)], contacts=[("email", "a@b.com")])
    other, _ = _seed_video(api_engine, "v2", "Otro", contacts=[("email", "x@y.com")])
    (c1,) = _contact_ids(api_engine, video_id)
    (foreign,) = _contact_ids(api_engine, other)
    base = {"candidate_id": c1, "contact_type_id": types["Correo"], "guest_candidate_id": g1}
    bad_cases = [
        ({**base, "contact_type_id": 999}, 422),                       # tipo inexistente
        ({**base, "relationship_id": 999}, 422),                       # relación inexistente
        ({**base, "candidate_id": foreign}, 422),                      # contacto de otro video
        ({**base, "candidate_id": 999}, 404),                          # contacto inexistente
        ({"candidate_id": c1, "contact_type_id": types["Correo"], "existing_guest_id": 999}, 404),
        ({"candidate_id": c1, "contact_type_id": types["Correo"]}, 422),  # sin invitado
        ({**base, "added_guest_name": "Ana"}, 422),                    # dos referencias a la vez
    ]
    for contact, expected in bad_cases:
        resp = _resolve(api_client, video_id, guests=[{"candidate_id": g1}], contacts=[contact])
        assert resp.status_code == expected, (contact, resp.text)
        assert _status(api_engine, g1) == "pending"                    # nunca se escribió a medias


def test_resolve_contacto_repetido_se_vincula_al_existente_sin_duplicar(api_client, api_engine):
    types = _seed_types(api_engine, "Correo")
    video_id, (g1,) = _seed_video(api_engine, guests=[("Ana", 0.9)], contacts=[("email", "ANA@mail.com")])
    (c1,) = _contact_ids(api_engine, video_id)
    with Session(api_engine) as s:   # Ana ya existe y ya tiene ese contacto
        ana = Guest(full_name="Ana")
        s.add(ana)
        s.commit()
        existing = Contact(guest_id=ana.id, contact_type_id=types["Correo"], value="ana@mail.com")
        s.add(existing)
        s.commit()
        existing_id = existing.id

    resp = _resolve(api_client, video_id, guests=[{"candidate_id": g1}], contacts=[{
        "candidate_id": c1, "contact_type_id": types["Correo"], "guest_candidate_id": g1,
    }])
    assert resp.status_code == 200 and resp.json()["accepted_contact_ids"] == [existing_id]
    with Session(api_engine) as s:
        assert s.scalar(select(func.count(Contact.id))) == 1
        assert s.get(StagingContactCandidate, c1).linked_contact_id == existing_id
    assert _status(api_engine, g1) == "accepted"


# --- contactos capturados a mano (vistos dentro del video) -------------------------------------

def test_resolve_crea_el_contacto_manual_con_el_video_de_origen(api_client, api_engine):
    types = _seed_types(api_engine, "Celular")
    video_id, (g1,) = _seed_video(api_engine, guests=[("Ana", 0.9)])
    body = _resolve(api_client, video_id, guests=[{"candidate_id": g1}], added_contacts=[{
        "contact_type_id": types["Celular"], "value": " 5512345678 ", "relationship_id": types["_manager"],
        "guest_candidate_id": g1,
    }]).json()

    assert len(body["added_contact_ids"]) == 1 and body["accepted_contact_ids"] == []
    with Session(api_engine) as s:
        contact = s.get(Contact, body["added_contact_ids"][0])
        assert contact.guest_id == body["accepted_guest_ids"][0]
        assert (contact.value, contact.source, contact.verified) == ("5512345678", "manual", False)
        assert (contact.relationship_id, contact.video_id) == (types["_manager"], video_id)
        assert contact.evidence == "Visto en el video"


def test_resolve_agrega_un_contacto_manual_a_un_invitado_ya_revisado_y_a_uno_agregado_a_mano(api_client, api_engine):
    types = _seed_types(api_engine, "Correo")
    video_id, _ = _seed_video(api_engine, status="has_guests")
    with Session(api_engine) as s:
        ana = Guest(full_name="Ana")
        s.add(ana)
        s.commit()
        ana_id = ana.id
    first = _resolve(api_client, video_id, added_contacts=[{
        "contact_type_id": types["Correo"], "value": "ana@mail.com", "existing_guest_id": ana_id,
    }])
    assert first.status_code == 200
    second = _resolve(api_client, video_id, added_guests=[{"full_name": "Luis Pérez"}], added_contacts=[{
        "contact_type_id": types["Correo"], "value": "luis@mail.com", "added_guest_name": "luis perez",
    }]).json()
    with Session(api_engine) as s:
        assert s.get(Contact, first.json()["added_contact_ids"][0]).guest_id == ana_id
        assert s.get(Contact, second["added_contact_ids"][0]).guest_id == second["accepted_guest_ids"][0]


def test_resolve_contacto_manual_repetido_no_se_duplica(api_client, api_engine):
    types = _seed_types(api_engine, "Correo")
    video_id, _ = _seed_video(api_engine, status="has_guests")
    with Session(api_engine) as s:
        ana = Guest(full_name="Ana")
        s.add(ana)
        s.commit()
        existing = Contact(guest_id=ana.id, contact_type_id=types["Correo"], value="ana@mail.com")
        s.add(existing)
        s.commit()
        ana_id, existing_id = ana.id, existing.id
    resp = _resolve(api_client, video_id, added_contacts=[{
        "contact_type_id": types["Correo"], "value": "ANA@mail.com", "existing_guest_id": ana_id,
    }])
    assert resp.status_code == 200 and resp.json()["added_contact_ids"] == [existing_id]
    with Session(api_engine) as s:
        assert s.scalar(select(func.count(Contact.id))) == 1


def test_resolve_valida_los_contactos_manuales_antes_de_escribir(api_client, api_engine):
    types = _seed_types(api_engine, "Correo")
    video_id, (g1, g2) = _seed_video(api_engine, guests=[("Ana", 0.9), ("Luis", 0.8)])
    base = {"contact_type_id": types["Correo"], "value": "a@b.com", "guest_candidate_id": g1}
    bad_cases = [
        ({**base, "contact_type_id": 999}, 422),                       # tipo inexistente
        ({**base, "relationship_id": 999}, 422),                       # relación inexistente
        ({**base, "guest_candidate_id": g2}, 422),                     # su invitado no se acepta aquí
        ({**base, "guest_candidate_id": None, "existing_guest_id": 999}, 404),
        ({**base, "value": "   "}, 422),                               # valor vacío
        ({"contact_type_id": types["Correo"], "value": "a@b.com"}, 422),  # sin invitado
    ]
    for contact, expected in bad_cases:
        resp = _resolve(api_client, video_id, guests=[{"candidate_id": g1}], reject_candidate_ids=[],
                        added_contacts=[contact])
        assert resp.status_code == expected, (contact, resp.text)
        assert _status(api_engine, g1) == "pending"                    # nada a medias
    with Session(api_engine) as s:
        assert s.scalar(select(func.count(Contact.id))) == 0


def test_la_lista_ofrece_tipo_sugerido_invitado_del_contacto_y_participantes(api_client, api_engine):
    types = _seed_types(api_engine, "Correo", "Celular")
    video_id, (g1,) = _seed_video(api_engine, guests=[("Ana", 0.9)],
                                  contacts=[("email", "a@b.com"), ("handle", "@ana")])
    c1, c2 = _contact_ids(api_engine, video_id)
    _mark_contacts(api_engine, video_id, guest_candidate_id=g1)
    with Session(api_engine) as s:
        luis = Guest(full_name="Luis")
        s.add(luis)
        s.commit()
        s.add(Participation(guest_id=luis.id, video_id=video_id))
        s.commit()

    video = api_client.get("/staging/review/videos").json()["items"][0]
    by_id = {c["id"]: c for c in video["contact_candidates"]}
    assert by_id[c1]["suggested_contact_type_id"] == types["Correo"]    # email ~ Correo
    assert by_id[c2]["suggested_contact_type_id"] is None               # un handle no se adivina
    assert by_id[c1]["guest_candidate_id"] == g1
    assert [p["full_name"] for p in video["participants"]] == ["Luis"]


# --- programa y conductores sugeridos --------------------------------------------------------

def _seed_program(engine, name="Raíz y Cultura", hosts=(), active=True) -> int:
    with Session(engine) as s:
        program = Program(name=name, is_active=active)
        program.hosts = [Host(name=h) for h in hosts]
        s.add(program)
        s.commit()
        return program.id


def _seed_suggestion(engine, video_id, program_name=None, hosts=()) -> None:
    with Session(engine) as s:
        s.add(StagingVideoSuggestion(video_id=video_id, program_name=program_name, host_names=list(hosts)))
        s.commit()


def _video_state(engine, video_id):
    with Session(engine) as s:
        video = s.get(Video, video_id)
        suggestion = s.scalars(select(StagingVideoSuggestion).where(StagingVideoSuggestion.video_id == video_id)).first()
        return video.program_id, suggestion.status if suggestion else None


def test_list_includes_the_suggested_program_and_hosts(api_client, api_engine):
    program_id = _seed_program(api_engine)
    video_id, _ = _seed_video(api_engine, guests=[("Ana", 0.9)])
    _seed_suggestion(api_engine, video_id, "Raiz y Cultura", ["DJ Rayas", "Imperial Lion"])

    video = api_client.get("/staging/review/videos").json()["items"][0]
    assert video["suggested_program_id"] == program_id  # se empareja sin acentos
    assert video["suggested_host_names"] == ["DJ Rayas", "Imperial Lion"]
    assert video["program_id"] is None and video["program_host_names"] == []


def test_suggestion_to_an_unknown_or_inactive_program_is_not_matched(api_client, api_engine):
    _seed_program(api_engine, "Inactivo", active=False)
    video_id, _ = _seed_video(api_engine, guests=[("Ana", 0.9)])
    _seed_suggestion(api_engine, video_id, "Inactivo")
    assert api_client.get("/staging/review/videos").json()["items"][0]["suggested_program_id"] is None


def test_a_video_with_only_a_pending_suggestion_counts_as_pending(api_client, api_engine):
    video_id, _ = _seed_video(api_engine)  # sin candidatos de invitado
    _seed_suggestion(api_engine, video_id, hosts=["DJ Rayas"])
    counts = api_client.get("/staging/review/counts").json()
    assert counts["pending"] == 1 and counts["no_candidates"] == 0
    assert [v["id"] for v in api_client.get("/staging/review/videos").json()["items"]] == [video_id]


def test_assigned_program_lists_its_active_hosts(api_client, api_engine):
    program_id = _seed_program(api_engine, hosts=["Zeta", "Alfa", "Viejo"])
    with Session(api_engine) as s:
        s.scalars(select(Host).where(Host.name == "Viejo")).one().is_active = False
        s.commit()
    video_id, _ = _seed_video(api_engine, guests=[("Ana", 0.9)])
    with Session(api_engine) as s:
        s.get(Video, video_id).program_id = program_id
        s.commit()
    video = api_client.get("/staging/review/videos").json()["items"][0]
    assert video["program_id"] == program_id and video["program_host_names"] == ["Alfa", "Zeta"]


def test_resolve_sets_the_program_and_links_hosts_creating_the_missing_ones(api_client, api_engine):
    program_id = _seed_program(api_engine, hosts=["Ya Existente"])
    with Session(api_engine) as s:
        s.add(Host(name="DJ Rayas"))
        s.commit()
    video_id, _ = _seed_video(api_engine, guests=[("Ana", 0.9)])
    _seed_suggestion(api_engine, video_id, "Raíz y Cultura", ["dj rayas", "Imperial Lion"])

    body = api_client.post(f"/staging/review/videos/{video_id}/resolve", json={
        "program_id": program_id, "host_names": ["dj rayas", "Imperial Lion", "DJ  RAYAS"],
    }).json()
    assert body["program_id"] == program_id and len(body["host_ids"]) == 2

    with Session(api_engine) as s:
        assert sorted(h.name for h in s.get(Program, program_id).hosts) == ["DJ Rayas", "Imperial Lion", "Ya Existente"]
        assert len(s.scalars(select(Host)).all()) == 3  # "dj rayas" reutilizó al existente
    assert _video_state(api_engine, video_id) == (program_id, "accepted")


def test_resolve_hosts_use_the_program_the_video_already_has(api_client, api_engine):
    program_id = _seed_program(api_engine)
    video_id, _ = _seed_video(api_engine)
    with Session(api_engine) as s:
        s.get(Video, video_id).program_id = program_id
        s.commit()
    assert api_client.post(f"/staging/review/videos/{video_id}/resolve", json={"host_names": ["Dante"]}).status_code == 200
    with Session(api_engine) as s:
        assert [h.name for h in s.get(Program, program_id).hosts] == ["Dante"]


def test_resolve_hosts_need_a_program_and_write_nothing_otherwise(api_client, api_engine):
    video_id, (c1,) = _seed_video(api_engine, guests=[("Ana", 0.9)])
    response = api_client.post(f"/staging/review/videos/{video_id}/resolve", json={
        "guests": [{"candidate_id": c1}], "host_names": ["Dante"],
    })
    assert response.status_code == 422 and "elige primero el programa" in response.json()["detail"]
    assert _status(api_engine, c1) == "pending"
    with Session(api_engine) as s:
        assert s.scalars(select(Host)).all() == [] and s.scalars(select(Guest)).all() == []


def test_resolve_program_and_host_errors(api_client, api_engine):
    inactive = _seed_program(api_engine, "Apagado", active=False)
    active = _seed_program(api_engine, "Activo")
    with Session(api_engine) as s:
        s.add(Host(name="Desactivado", is_active=False))
        s.commit()
    video_id, _ = _seed_video(api_engine)
    url = f"/staging/review/videos/{video_id}/resolve"
    assert api_client.post(url, json={"program_id": 999}).status_code == 422
    assert api_client.post(url, json={"program_id": inactive}).status_code == 422
    response = api_client.post(url, json={"program_id": active, "host_names": ["Desactivado"]})
    assert response.status_code == 422 and "desactivado" in response.json()["detail"]
    assert api_client.post(url, json={"host_names": ["  "]}).status_code == 422
    assert _video_state(api_engine, video_id) == (None, None)  # nada se escribió


def test_resolving_without_program_or_hosts_rejects_the_suggestion(api_client, api_engine):
    video_id, (c1,) = _seed_video(api_engine, guests=[("Ana", 0.9)])
    _seed_suggestion(api_engine, video_id, "Raíz y Cultura", ["DJ Rayas"])
    api_client.post(f"/staging/review/videos/{video_id}/resolve", json={"guests": [{"candidate_id": c1}]})
    assert _video_state(api_engine, video_id) == (None, "rejected")
    assert api_client.get("/staging/review/counts").json()["pending"] == 0


def test_no_guests_with_program_keeps_the_reviewed_program(api_client, api_engine):
    program_id = _seed_program(api_engine)
    video_id, _ = _seed_video(api_engine, guests=[("Especial Drama", 0.4)])
    _seed_suggestion(api_engine, video_id, "Raíz y Cultura")
    body = api_client.post(f"/staging/review/videos/{video_id}/resolve", json={
        "no_guests": True, "program_id": program_id,
    }).json()
    assert body["guest_status"] == "no_guests" and body["program_id"] == program_id
    assert _video_state(api_engine, video_id) == (program_id, "accepted")


# --- dudosos y conductores habituales ----------------------------------------------------------

def test_list_includes_doubtful_names_and_usual_hosts_without_repeating_the_mentioned_ones(api_client, api_engine):
    program_id = _seed_program(api_engine, hosts=["Imperial Lion"])
    video_id, _ = _seed_video(api_engine, guests=[("Ana", 0.9)])
    with Session(api_engine) as s:
        s.add(StagingVideoSuggestion(
            video_id=video_id, program_name="Raíz y Cultura", host_names=["Dante"],
            doubtful_names=[{"name": "Frankgogo", "guess": "host"}],
            usual_host_names=["Dante", "DJ Rayas"],
        ))
        s.commit()

    video = api_client.get("/staging/review/videos").json()["items"][0]
    assert video["doubtful_names"] == [{"name": "Frankgogo", "guess": "host"}]
    # Dante ya lo menciona el texto; los habituales son los de la serie más los del catálogo.
    assert video["usual_host_names"] == ["DJ Rayas", "Imperial Lion"]
    assert video["suggested_program_id"] == program_id


def test_usual_hosts_come_from_the_assigned_program_too(api_client, api_engine):
    program_id = _seed_program(api_engine, hosts=["Zeta", "Alfa"])
    video_id, _ = _seed_video(api_engine, guests=[("Ana", 0.9)])
    with Session(api_engine) as s:
        s.get(Video, video_id).program_id = program_id
        s.commit()
    video = api_client.get("/staging/review/videos").json()["items"][0]
    assert video["usual_host_names"] == ["Alfa", "Zeta"]
    assert video["doubtful_names"] == []


def test_a_video_without_suggestion_has_no_doubtful_or_usual(api_client, api_engine):
    _seed_video(api_engine, guests=[("Ana", 0.9)])
    video = api_client.get("/staging/review/videos").json()["items"][0]
    assert video["doubtful_names"] == [] and video["usual_host_names"] == []


def test_a_video_with_only_doubtful_names_counts_as_pending(api_client, api_engine):
    video_id, _ = _seed_video(api_engine)
    with Session(api_engine) as s:
        s.add(StagingVideoSuggestion(video_id=video_id, doubtful_names=[{"name": "Frankgogo", "guess": "unknown"}]))
        s.commit()
    assert api_client.get("/staging/review/counts").json()["pending"] == 1
