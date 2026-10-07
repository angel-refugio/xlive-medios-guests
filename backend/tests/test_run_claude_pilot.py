"""Pruebas del script del piloto con Claude Code: `claude -p` se simula, no se ejecuta."""
import json
from types import SimpleNamespace

import pytest

from app.services.claude_extraction import ClaudeExtractionError
from scripts import run_claude_pilot as pilot


def _samples(tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir(exist_ok=True)
    videos = [
        {"id": "a1", "title": "Serie A: Uno", "description": "d", "published_at": "2024-01-01T00:00:00Z"},
        {"id": "a2", "title": "Serie A: Dos", "description": "d", "published_at": "2024-02-01T00:00:00Z"},
        {"id": "s1", "title": "Titulo suelto", "description": "d", "published_at": "2024-03-01T00:00:00Z"},
    ]
    (samples / "sample_1.json").write_text(json.dumps({"videos": videos}), encoding="utf-8")
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps({"videos": {
        i: {"program": None, "guests": [], "hosts": []} for i in ("a1", "a2", "s1")
    }}), encoding="utf-8")
    return samples, gold


def _args(tmp_path, *extra):
    samples, gold = _samples(tmp_path)
    return pilot.build_parser().parse_args([
        "--gold", str(gold), "--samples-dir", str(samples),
        "--out-dir", str(tmp_path / "pilot"), "--eval-dir", str(tmp_path / "eval"), *extra,
    ])


class FakeClaude:
    """Reemplaza subprocess.run: responde con un guest por video y cuenta las llamadas.

    `invalid_first` = respuestas con JSON inválido antes de la primera buena (0 = siempre buena;
    un número muy grande = siempre inválida).
    """

    def __init__(self, fail_first: bool = False, invalid_first: int = 0):
        self.calls = 0
        self.fail_first = fail_first
        self.invalid_first = invalid_first
        self.prompts: list[str] = []

    def __call__(self, command, input=None, **kwargs):
        self.calls += 1
        self.prompts.append(input)
        if self.fail_first and self.calls == 1:
            return SimpleNamespace(returncode=1, stdout="", stderr="límite de uso")
        if self.calls <= self.invalid_first:
            stdout = json.dumps({"result": "esto no es json", "usage": {"input_tokens": 100, "output_tokens": 50}})
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        ids = [v["video_id"] for v in json.loads(input[input.index("{"):])["videos"]]
        result = json.dumps({"instructions_version": "v1", "videos": [
            {"video_id": i, "guests": [{"name": f"Invitado {i}"}],
             "unassigned_contacts": [{"type": "celular", "value": "5512345678"}]}
            for i in ids
        ]})
        stdout = json.dumps({
            "result": result, "total_cost_usd": 0.1,
            "modelUsage": {"claude-sonnet-5-5": {}},
            "usage": {"input_tokens": 100, "output_tokens": 50},
        })
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


@pytest.fixture(autouse=True)
def _claude_en_el_path(monkeypatch):
    monkeypatch.setattr(pilot.shutil, "which", lambda name: "claude")


def test_run_guarda_lotes_y_predicciones_para_la_evaluacion(tmp_path, capsys):
    args = _args(tmp_path, "--price-in", "3", "--price-out", "15")
    runner = FakeClaude()
    assert pilot.run(args, runner) == 0
    assert runner.calls == 2                                  # lote de la serie A + lote de sueltos
    assert len(list((tmp_path / "pilot").glob("batch_*.json"))) == 2
    cache = json.loads(pilot.eval_cache_path(tmp_path / "eval", "sonnet", "v2").read_text(encoding="utf-8"))
    assert cache["a1"] == {"guests": ["Invitado a1"], "hosts": [], "program": ""}
    out = capsys.readouterr().out
    assert "Videos con resultado: 3" in out and "sin asignar: 3" in out
    assert "Modelo(s) que respondieron: claude-sonnet-5-5" in out
    saved = json.loads(next((tmp_path / "pilot").glob("batch_*.json")).read_text(encoding="utf-8"))
    assert saved["usage"]["models"] == ["claude-sonnet-5-5"]
    assert "Costo equivalente en API" in out
    assert "5512345678" not in out                            # los contactos no se imprimen


def test_lotes_antiguos_sin_modelo_se_resumen_como_no_registrado(tmp_path, capsys):
    pilot.run(_args(tmp_path), FakeClaude())
    for path in (tmp_path / "pilot").glob("batch_*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["usage"]["models"]
        path.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    assert pilot.run(_args(tmp_path, "--summary-only"), FakeClaude()) == 0
    assert "no registrado" in capsys.readouterr().out


def test_run_no_repite_lotes_ya_guardados(tmp_path):
    args = _args(tmp_path)
    runner = FakeClaude()
    pilot.run(args, runner)
    pilot.run(args, runner)
    assert runner.calls == 2


def test_run_lote_fallido_se_reintenta_en_la_siguiente_corrida(tmp_path, capsys):
    args = _args(tmp_path)
    runner = FakeClaude(fail_first=True)
    assert pilot.run(args, runner) == 0
    assert "1 lote(s) fallaron" in capsys.readouterr().out
    assert len(list((tmp_path / "pilot").glob("batch_*.json"))) == 1
    pilot.run(args, runner)
    assert len(list((tmp_path / "pilot").glob("batch_*.json"))) == 2


def test_run_limit_usa_solo_los_primeros_videos(tmp_path):
    args = _args(tmp_path, "--limit", "2")
    runner = FakeClaude()
    pilot.run(args, runner)
    cache = json.loads(pilot.eval_cache_path(tmp_path / "eval", "sonnet", "v2").read_text(encoding="utf-8"))
    assert set(cache) == {"a1", "a2"}


def test_lote_con_el_mismo_numero_pero_otros_videos_no_se_salta(tmp_path, capsys):
    # Con --limit 1 el lote 1 es [a1]; con todos, el lote 1 es [a1, a2]: no deben confundirse.
    pilot.run(_args(tmp_path, "--limit", "1"), FakeClaude())
    runner = FakeClaude()
    assert pilot.run(_args(tmp_path), runner) == 0
    cache = json.loads(pilot.eval_cache_path(tmp_path / "eval", "sonnet", "v2").read_text(encoding="utf-8"))
    assert set(cache) == {"a1", "a2", "s1"}
    assert runner.calls == 2                                  # [a1, a2] y [s1]; el lote [a1] no cuenta
    assert "sin resultado" not in capsys.readouterr().out


def test_summary_only_no_llama_a_claude(tmp_path, capsys):
    args = _args(tmp_path)
    pilot.run(args, FakeClaude())
    summary_args = _args(tmp_path, "--summary-only")
    runner = FakeClaude()
    assert pilot.run(summary_args, runner) == 0
    assert runner.calls == 0 and "Videos con resultado: 3" in capsys.readouterr().out


def test_summary_only_sin_lotes_avisa(tmp_path, capsys):
    assert pilot.run(_args(tmp_path, "--summary-only"), FakeClaude()) == 1
    assert "Todavía no hay lotes" in capsys.readouterr().out


def test_overhead_guarda_los_tokens_fijos_y_el_resumen_los_resta(tmp_path, capsys):
    assert pilot.run(_args(tmp_path, "--overhead"), FakeClaude()) == 0
    assert (tmp_path / "pilot" / "overhead.json").exists()
    capsys.readouterr()
    assert pilot.run(_args(tmp_path, "--price-in", "3", "--price-out", "15"), FakeClaude()) == 0
    out = capsys.readouterr().out
    assert "Tokens fijos de Claude Code por llamada" in out and "Sin los tokens fijos" in out


def test_with_catalog_pasa_programas_y_conductores_de_la_referencia(tmp_path):
    args = _args(tmp_path, "--with-catalog")
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    gold["videos"]["a1"].update({"program": "Serie A", "hosts": ["Luis Pérez"]})
    args.gold.write_text(json.dumps(gold), encoding="utf-8")
    runner = FakeClaude()
    assert pilot.run(args, runner) == 0
    payload = json.loads(runner.prompts[0][runner.prompts[0].index("{"):])
    assert payload["known_programs"] == ["Serie A"] and payload["known_hosts"] == ["Luis Pérez"]
    saved = json.loads(next((tmp_path / "pilot").glob("batch_*.json")).read_text(encoding="utf-8"))
    assert saved["with_catalog"] is True and saved["instructions_version"] == "v2"


def test_sin_with_catalog_no_se_envian_catalogos(tmp_path):
    runner = FakeClaude()
    pilot.run(_args(tmp_path), runner)
    payload = json.loads(runner.prompts[0][runner.prompts[0].index("{"):])
    assert payload["known_programs"] == [] and payload["known_hosts"] == []


def test_json_invalido_se_reintenta_una_vez_y_cuenta_los_tokens_de_ambos_intentos(tmp_path):
    runner = FakeClaude(invalid_first=1)
    assert pilot.run(_args(tmp_path, "--limit", "2"), runner) == 0   # un solo lote: [a1, a2]
    assert runner.calls == 2
    saved = json.loads(next((tmp_path / "pilot").glob("batch_*.json")).read_text(encoding="utf-8"))
    assert saved["usage"]["input_tokens"] == 200 and saved["usage"]["calls"] == 2


def test_json_invalido_en_los_dos_intentos_deja_el_lote_pendiente(tmp_path, capsys):
    runner = FakeClaude(invalid_first=99)
    assert pilot.run(_args(tmp_path, "--limit", "2"), runner) == 1
    assert runner.calls == 2
    assert not list((tmp_path / "pilot").glob("batch_*.json"))
    assert "Todavía no hay lotes" in capsys.readouterr().out


def test_nombres_de_cache_y_carpeta_por_version(tmp_path):
    assert pilot.eval_cache_path(tmp_path, "sonnet", "v1").name == "predictions_claude_code_sonnet.json"
    assert pilot.eval_cache_path(tmp_path, "sonnet", "v2").name == "predictions_claude_code_v2_sonnet.json"
    assert pilot.default_out_dir("v1").name == "pilot" and pilot.default_out_dir("v2").name == "pilot_v2"


def test_instructions_v1_usa_las_instrucciones_y_el_nombre_de_v1(tmp_path, capsys):
    runner = FakeClaude()
    assert pilot.run(_args(tmp_path, "--instructions", "v1"), runner) == 0
    assert pilot.eval_cache_path(tmp_path / "eval", "sonnet", "v1").exists()
    assert "--extractor claude_code --model sonnet" in capsys.readouterr().out


def test_run_claude_sin_comando_en_el_path(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot.shutil, "which", lambda name: None)
    with pytest.raises(ClaudeExtractionError, match=r"claude_command"):
        pilot.claude_command("sonnet", "instrucciones")


def test_run_claude_codigo_de_salida_distinto_de_cero():
    runner = lambda *a, **k: SimpleNamespace(returncode=2, stdout="", stderr="boom")  # noqa: E731
    with pytest.raises(ClaudeExtractionError, match=r"run_claude.*código 2"):
        pilot.run_claude(["claude"], "hola", runner)


def test_run_claude_error_del_sistema_se_convierte_en_error_del_modulo():
    def runner(*a, **k):
        raise OSError("no existe")
    with pytest.raises(ClaudeExtractionError, match=r"run_claude"):
        pilot.run_claude(["claude"], "hola", runner)


def test_load_results_lote_ilegible_da_error_con_su_nombre(tmp_path):
    out = tmp_path / "pilot"
    out.mkdir()
    (out / "batch_0001.json").write_text("{", encoding="utf-8")
    with pytest.raises(ClaudeExtractionError, match="batch_0001.json"):
        pilot.load_results(out)


def test_claude_command_corre_sin_herramientas_ni_sesion():
    command = pilot.claude_command("sonnet", "instrucciones")
    assert command[:3] == ["claude", "-p", "--output-format"]
    assert "--tools" in command and command[command.index("--tools") + 1] == ""
    assert "--no-session-persistence" in command
