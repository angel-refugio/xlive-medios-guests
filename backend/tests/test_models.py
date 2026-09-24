"""Pruebas de restricciones y opcionalidad del modelo de datos."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Borough, Contact, ContactType, Guest, GuestCategory, Participation, Program,
    Video, VideoType, guest_category_links,
)


def _video(yt_id="abc123", **kw):
    return Video(youtube_video_id=yt_id, title="Título", **kw)


# --- Opcionalidad -----------------------------------------------------------

def test_guest_only_needs_full_name(session):
    g = Guest(full_name="Invitado Mínimo")
    session.add(g)
    session.commit()
    assert g.approx_age is None and g.borough_id is None
    assert g.contacts == [] and g.categories == []


def test_video_without_guests_or_optional_fields(session):
    v = _video()
    session.add(v)
    session.commit()
    assert v.guest_status == "pending"
    assert v.program_id is None and v.video_type_id is None
    assert v.participations == []


# --- Unicidad ---------------------------------------------------------------

def test_youtube_video_id_is_unique(session):
    session.add(_video("dup"))
    session.commit()
    session.add(_video("dup"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_participation_unique_per_guest_video(session):
    g, v = Guest(full_name="A"), _video()
    session.add_all([g, v])
    session.commit()
    session.add(Participation(guest_id=g.id, video_id=v.id))
    session.commit()
    session.add(Participation(guest_id=g.id, video_id=v.id))
    with pytest.raises(IntegrityError):
        session.commit()


def test_guest_can_appear_in_many_videos(session):
    g = Guest(full_name="A")
    v1, v2 = _video("v1"), _video("v2")
    session.add_all([g, v1, v2])
    session.commit()
    session.add_all([
        Participation(guest_id=g.id, video_id=v1.id),
        Participation(guest_id=g.id, video_id=v2.id),
    ])
    session.commit()
    assert len(g.participations) == 2


@pytest.mark.parametrize("model", [GuestCategory, VideoType, ContactType, Program, Borough])
def test_catalog_name_is_unique(session, model):
    session.add(model(name="X"))
    session.commit()
    session.add(model(name="X"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_category_not_repeated_for_guest(session):
    cat = GuestCategory(name="Cantante")
    g = Guest(full_name="A", categories=[cat])
    session.add(g)
    session.commit()
    # Insert directo: la PK compuesta debe impedir el duplicado en la BD.
    with pytest.raises(IntegrityError):
        session.execute(
            guest_category_links.insert().values(guest_id=g.id, category_id=cat.id)
        )


def test_guest_has_multiple_categories(session):
    g = Guest(full_name="A", categories=[GuestCategory(name="Cantante"), GuestCategory(name="Escultor")])
    session.add(g)
    session.commit()
    assert {c.name for c in g.categories} == {"Cantante", "Escultor"}


# --- CHECK ------------------------------------------------------------------

def test_negative_age_rejected(session):
    session.add(Guest(full_name="A", approx_age=-1))
    with pytest.raises(IntegrityError):
        session.commit()


def test_video_cannot_be_part_of_itself(session):
    v = _video()
    session.add(v)
    session.commit()
    v.part_of_video_id = v.id
    with pytest.raises(IntegrityError):
        session.commit()


def test_video_part_of_another_video(session):
    v1 = _video("v1")
    session.add(v1)
    session.commit()
    v2 = _video("v2", part_of_video_id=v1.id)
    session.add(v2)
    session.commit()
    assert v2.part_of_video_id == v1.id


def test_invalid_guest_status_rejected(session):
    session.add(_video(guest_status="otro"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_invalid_contact_source_rejected(session):
    ct, g = ContactType(name="Celular"), Guest(full_name="A")
    session.add_all([ct, g])
    session.commit()
    session.add(Contact(guest_id=g.id, contact_type_id=ct.id, value="555", source="scraping"))
    with pytest.raises(IntegrityError):
        session.commit()


# --- ON DELETE --------------------------------------------------------------

def test_deleting_guest_cascades_contacts_and_participations(session):
    ct, v = ContactType(name="Celular"), _video()
    g = Guest(full_name="A")
    session.add_all([ct, v, g])
    session.commit()
    session.add_all([
        Contact(guest_id=g.id, contact_type_id=ct.id, value="555"),
        Participation(guest_id=g.id, video_id=v.id),
    ])
    session.commit()

    session.delete(g)
    session.commit()

    assert session.scalars(select(Contact)).all() == []
    assert session.scalars(select(Participation)).all() == []
    assert session.get(Video, v.id) is not None  # el video permanece


def test_catalog_in_use_cannot_be_deleted(session):
    borough = Borough(name="Coyoacán")
    session.add(borough)
    session.commit()
    session.add(Guest(full_name="A", borough_id=borough.id))
    session.commit()

    session.delete(borough)
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_original_video_keeps_its_parts(session):
    v1 = _video("v1")
    session.add(v1)
    session.commit()
    v2 = _video("v2", part_of_video_id=v1.id)
    session.add(v2)
    session.commit()

    session.delete(v1)
    session.commit()
    session.refresh(v2)
    assert v2.part_of_video_id is None
