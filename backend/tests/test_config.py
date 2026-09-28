"""Pruebas de los getters de configuración de Ollama (Fase 3, paso 1)."""
import pytest

from app.core.config import get_ollama_base_url, get_ollama_model


def test_get_ollama_base_url_usa_valor_de_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://otro-host:11434")
    assert get_ollama_base_url() == "http://otro-host:11434"


def test_get_ollama_base_url_default_localhost(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert get_ollama_base_url() == "http://localhost:11434"


def test_get_ollama_model_usa_valor_de_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
    assert get_ollama_model() == "qwen2.5:3b"


def test_get_ollama_model_lanza_error_si_falta(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="OLLAMA_MODEL"):
        get_ollama_model()
