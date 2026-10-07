"""Pruebas del endpoint del botón "Ingesta" (POST /ingestion/runs). Sin red ni Ollama reales."""
from fastapi.testclient import TestClient

from app.api import ingestion as api_module
from app.models.ingestion import IngestionRun


def test_requires_authentication(api_client):
    anonymous = TestClient(api_client.app)
    assert anonymous.post("/ingestion/runs", json={"batch_size": 5}).status_code == 401


def test_falta_youtube_api_key_da_422(api_client, monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
    resp = api_client.post("/ingestion/runs", json={"batch_size": 5})
    assert resp.status_code == 422
    assert "YOUTUBE_API_KEY" in resp.json()["detail"]


def test_corrida_exitosa_devuelve_los_conteos_y_errores(api_client, monkeypatch):
    def fake_trigger(db, batch_size):
        run = IngestionRun(
            status="completed", trigger="manual", requested_batch_size=batch_size,
            processed_count=5, success_count=4, error_count=1,
        )
        db.add(run)
        db.commit()
        return run

    monkeypatch.setattr(api_module.pipeline, "trigger_manual_run", fake_trigger)
    resp = api_client.post("/ingestion/runs", json={"batch_size": 5})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "completed"
    assert body["requested_batch_size"] == 5
    assert body["processed_count"] == 5
    assert body["success_count"] == 4
    assert body["error_count"] == 1
    assert body["errors"] == []


def test_batch_size_por_defecto_si_se_omite(api_client, monkeypatch):
    captured = {}

    def fake_trigger(db, batch_size):
        captured["batch_size"] = batch_size
        run = IngestionRun(status="completed")
        db.add(run)
        db.commit()
        return run

    monkeypatch.setattr(api_module.pipeline, "trigger_manual_run", fake_trigger)
    resp = api_client.post("/ingestion/runs", json={})
    assert resp.status_code == 201
    from app.services.pipeline import DEFAULT_BATCH_SIZE
    assert captured["batch_size"] == DEFAULT_BATCH_SIZE


def test_batch_size_invalido_da_422(api_client):
    resp = api_client.post("/ingestion/runs", json={"batch_size": 0})
    assert resp.status_code == 422
