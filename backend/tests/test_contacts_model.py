"""Pruebas del modelo objetivo de contactos: normalización, unicidad, sin asignar y relación."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.catalogs import ContactRelationship, ContactType
from app.models.contact import Contact, normalize_contact_value
from app.models.guest import Guest


@pytest.mark.parametrize("raw,expected", [
    ("HTTPS://WWW.Instagram.com/Ana_Perez/", "instagram.com/ana_perez"),
    ("  Ana@Mail.COM ", "ana@mail.com"),
    ("+52 55 1234 5678", "5512345678"),
    ("(55) 1234-5678", "5512345678"),
    ("5512345678", "5512345678"),
    ("@Ana_Perez", "@ana_perez"),
    ("2024", "2024"),                       # muy corto para ser teléfono: texto normal
])
def test_normalize_contact_value(raw, expected):
    assert normalize_contact_value(raw) == expected


def _setup(session):
    guest = Guest(full_name="Ana Pérez")
    ctype = ContactType(name="Correo")
    session.add_all([guest, ctype])
    session.flush()
    return guest, ctype


def test_el_valor_normalizado_se_llena_solo_al_crear_y_al_editar(session):
    guest, ctype = _setup(session)
    contact = Contact(guest_id=guest.id, contact_type_id=ctype.id, value="Ana@Mail.com")
    session.add(contact)
    session.flush()
    assert contact.normalized_value == "ana@mail.com"
    contact.value = "OTRA@mail.com"
    session.flush()
    assert contact.normalized_value == "otra@mail.com"


def test_valores_por_defecto_de_un_contacto_manual(session):
    guest, ctype = _setup(session)
    contact = Contact(guest_id=guest.id, contact_type_id=ctype.id, value="x@mail.com")
    session.add(contact)
    session.flush()
    assert (contact.status, contact.source, contact.verified) == ("validated", "manual", False)
    assert contact.relationship_id is None and contact.video_id is None and contact.evidence is None


def test_no_se_repite_el_mismo_contacto_del_mismo_invitado(session):
    guest, ctype = _setup(session)
    session.add(Contact(guest_id=guest.id, contact_type_id=ctype.id, value="ana@mail.com"))
    session.flush()
    session.add(Contact(guest_id=guest.id, contact_type_id=ctype.id, value="  ANA@mail.com "))
    with pytest.raises(IntegrityError):
        session.flush()


def test_el_mismo_valor_si_puede_estar_en_otro_invitado_o_con_otro_tipo(session):
    guest, ctype = _setup(session)
    other_guest, other_type = Guest(full_name="Beto"), ContactType(name="Web")
    session.add_all([other_guest, other_type])
    session.flush()
    session.add_all([
        Contact(guest_id=guest.id, contact_type_id=ctype.id, value="x@mail.com"),
        Contact(guest_id=other_guest.id, contact_type_id=ctype.id, value="x@mail.com"),
        Contact(guest_id=guest.id, contact_type_id=other_type.id, value="x@mail.com"),
    ])
    session.flush()
    assert len(list(session.scalars(select(Contact)))) == 3


def test_un_contacto_puede_quedar_sin_asignar_y_reasignarse(session):
    _, ctype = _setup(session)
    unassigned = [Contact(guest_id=None, contact_type_id=ctype.id, value="a@mail.com"),
                  Contact(guest_id=None, contact_type_id=ctype.id, value="a@mail.com")]
    session.add_all(unassigned)
    session.flush()                         # sin invitado no hay restricción: se puede decidir después
    guest = Guest(full_name="Ana")
    session.add(guest)
    session.flush()
    unassigned[0].guest_id = guest.id
    session.flush()
    assert unassigned[0].guest.full_name == "Ana"


def test_la_relacion_es_un_catalogo_y_el_estado_solo_admite_valores_validos(session):
    guest, ctype = _setup(session)
    relation = ContactRelationship(name="patrocinador")
    session.add(relation)
    session.flush()
    contact = Contact(guest_id=guest.id, contact_type_id=ctype.id, value="p@mail.com", relationship_id=relation.id)
    session.add(contact)
    session.flush()
    assert contact.relation.name == "patrocinador"
    contact.status = "inventado"
    with pytest.raises(IntegrityError):
        session.flush()


def test_la_relacion_en_uso_no_se_puede_borrar(session):
    guest, ctype = _setup(session)
    relation = ContactRelationship(name="manager")
    session.add(relation)
    session.flush()
    session.add(Contact(guest_id=guest.id, contact_type_id=ctype.id, value="m@mail.com", relationship_id=relation.id))
    session.flush()
    session.delete(relation)
    with pytest.raises(IntegrityError):
        session.flush()


def test_la_api_rechaza_con_409_un_contacto_repetido(api_client):
    guest = api_client.post("/guests", json={"full_name": "Ana"}).json()
    ctype = api_client.post("/contact-types", json={"name": "Correo"}).json()
    url = f"/guests/{guest['id']}/contacts"
    first = api_client.post(url, json={"contact_type_id": ctype["id"], "value": "Ana@Mail.com"})
    assert first.status_code == 201
    repeated = api_client.post(url, json={"contact_type_id": ctype["id"], "value": "  ana@mail.COM"})
    assert repeated.status_code == 409 and "ya tiene un contacto igual" in repeated.json()["detail"]


def test_la_api_rechaza_con_409_editar_un_contacto_para_repetir_otro(api_client):
    guest = api_client.post("/guests", json={"full_name": "Ana"}).json()
    ctype = api_client.post("/contact-types", json={"name": "Correo"}).json()
    url = f"/guests/{guest['id']}/contacts"
    api_client.post(url, json={"contact_type_id": ctype["id"], "value": "a@mail.com"})
    second = api_client.post(url, json={"contact_type_id": ctype["id"], "value": "b@mail.com"}).json()
    resp = api_client.patch(f"{url}/{second['id']}", json={"value": "A@MAIL.com"})
    assert resp.status_code == 409
    same = api_client.patch(f"{url}/{second['id']}", json={"value": "B@mail.com"})   # su propio valor: sí
    assert same.status_code == 200
