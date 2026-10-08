"""Pruebas del script que importa a staging los resultados de Claude Code."""
import json

from sqlalchemy import select

from app.models.ingestion import StagingContactCandidate, StagingGuestCandidate
from app.models.video import Video
from scripts import import_claude_results as script


def _pilot_dir(tmp_path):
    folder = tmp_path / "pilot_v5"
    folder.mkdir(exist_ok=True)
    (folder / "batch_0001_a.json").write_text(json.dumps({
        "instructions_version": "v5",
        "result": {"instructions_version": "v5", "videos": [{
            "video_id": "v1", "program": "Serie A",
            "guests": [{"name": "Ana Pérez", "confidence": 0.9}],
            "contacts": [{"type": "email", "value": "ana@mail.com", "guest": "Ana Pérez"}],
        }, {"video_id": "v2", "guests": [{"name": "Beto"}]}]},
    }), encoding="utf-8")
    return folder


def _samples(tmp_path):
    folder = tmp_path / "samples"
    folder.mkdir(exist_ok=True)
    (folder / "sample_1.json").write_text(json.dumps({"videos": [
        {"id": "v1", "title": "Serie A: Ana Pérez", "description": "d", "published_at": "2025-01-01T00:00:00Z",
         "duration": "PT5M", "tags": []},
        {"id": "v2", "title": "Serie A: Beto", "description": "d", "published_at": "2025-01-02T00:00:00Z",
         "duration": "PT6M", "tags": []},
    ]}), encoding="utf-8")
    return folder


def _args(tmp_path, *extra):
    return script.build_parser().parse_args(
        [str(_pilot_dir(tmp_path)), "--samples-dir", str(_samples(tmp_path)), *extra]
    )


def test_load_video_metadata_lee_las_muestras(tmp_path):
    assert set(script.load_video_metadata(_samples(tmp_path))) == {"v1", "v2"}


def test_create_missing_carga_videos_y_candidatos_y_resume_sin_mostrar_contactos(session, tmp_path, capsys):
    assert script.run(_args(tmp_path, "--create-missing"), session) == 0
    out = capsys.readouterr().out
    assert "Importación terminada" in out and "Videos importados: 2 (creados en la BD: 2)" in out
    assert "Candidatos de invitado: 2" in out and "ana@mail.com" not in out
    assert {g.extractor for g in session.scalars(select(StagingGuestCandidate))} == {"claude_code"}
    assert session.scalar(select(StagingContactCandidate)).value == "ana@mail.com"


def test_sin_create_missing_omite_los_videos_que_no_estan(session, tmp_path, capsys):
    assert script.run(_args(tmp_path), session) == 0
    assert "2 video(s) no están en la BD" in capsys.readouterr().out
    assert session.scalar(select(Video.id)) is None


def test_dry_run_no_guarda_nada(session, tmp_path, capsys):
    assert script.run(_args(tmp_path, "--create-missing", "--dry-run"), session) == 0
    assert "SIMULACIÓN" in capsys.readouterr().out
    assert session.scalar(select(Video.id)) is None and session.scalar(select(StagingGuestCandidate.id)) is None


def test_reimportar_no_duplica(session, tmp_path):
    args = _args(tmp_path, "--create-missing")
    script.run(args, session)
    script.run(args, session)
    assert len(list(session.scalars(select(StagingGuestCandidate)))) == 2
    assert len(list(session.scalars(select(StagingContactCandidate)))) == 1


def test_extractor_api_se_acepta_en_la_linea_de_comandos(tmp_path):
    assert _args(tmp_path, "--extractor", "claude_api").extractor == "claude_api"
