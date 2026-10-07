"""Hoja de revisión de la referencia (gold set): corregirla desde el navegador, sin editar JSON.

Dos pasos, desde backend/:
    python -m scripts.review_sheet export          # genera data/review/revision_v3.html
    python -m scripts.review_sheet apply respuestas.json   # aplica tus correcciones a la referencia

`export` toma los videos donde la extracción de Claude más se aleja de la referencia, unos videos
donde coinciden (para no sesgar la revisión: si solo se miran los desacuerdos, la referencia solo
mejora en una dirección) y videos donde Claude encontró contactos. Cada video trae su enlace de
YouTube, el título, la descripción y los campos editables con lo que dice hoy la referencia.
Abre el HTML en el navegador, corrige, marca "Revisado" y descarga el JSON con tus respuestas
(el progreso se guarda en el navegador).

`apply` actualiza `guests`, `hosts` y `program` de los videos marcados como revisados, les pone
`reviewed = true` y guarda una copia de respaldo de la referencia. El veredicto de cada contacto
se guarda aparte (`data/gold/contacts_review.json`) para medirlos después. Después, la nueva
medición no necesita llamar a Claude: `python -m scripts.eval_extraction --extractor claude_code_v3`.

Todo queda en `backend/data/`, fuera de Git. No toca la base de datos ni YouTube.
"""
import argparse
import html
import json
import logging
import random
import shutil
import sys
from datetime import datetime
from pathlib import Path

from app.schemas.claude_extraction import VideoExtraction
from app.services import claude_extraction, extraction_eval
from app.services.extraction_eval import EvalError, Prediction

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_GOLD = DATA_DIR / "gold" / "guests_gold.json"
DEFAULT_CONTACTS_REVIEW = DATA_DIR / "gold" / "contacts_review.json"
DEFAULT_SAMPLES_DIR = DATA_DIR / "samples"
DEFAULT_PILOT_DIR = DATA_DIR / "pilot_v3"
DEFAULT_OUT = DATA_DIR / "review" / "revision_v3.html"
YOUTUBE_URL = "https://www.youtube.com/watch?v={video_id}"
DESCRIPTION_PREVIEW_CHARS = 1500


class ReviewError(RuntimeError):
    """Fallo al generar o aplicar la hoja de revisión; el mensaje indica módulo y función."""


def _fail(function: str, detail: str, cause: Exception | None = None) -> ReviewError:
    msg = f"[scripts.review_sheet.{function}] {detail}"
    logger.error(msg)
    error = ReviewError(msg)
    error.__cause__ = cause
    return error


# --- datos ------------------------------------------------------------------------------

def load_extractions(pilot_dir: Path) -> dict[str, VideoExtraction]:
    """Resultado completo de Claude por video (invitados, conductores y contactos)."""
    results: dict[str, VideoExtraction] = {}
    for path in sorted(Path(pilot_dir).glob("batch_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for raw in data["result"]["videos"]:
                video = VideoExtraction.model_validate(raw)
                results[video.video_id] = video
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise _fail("load_extractions", f"Lote ilegible {path.name}: {exc}", exc) from exc
    if not results:
        raise _fail("load_extractions", f"No hay lotes en {pilot_dir}; corre primero scripts.run_claude_pilot")
    return results


def select_videos(
    gold: dict[str, dict], extractions: dict[str, VideoExtraction],
    n_errors: int = 15, n_agree: int = 15, n_contacts: int = 10, seed: int = 7,
) -> list[tuple[str, str]]:
    """(id, grupo) a revisar. Se omiten los que el usuario ya revisó (`reviewed`).

    Grupos: "errores" (los de más desacuerdo con la referencia), "coinciden" (muestra al azar
    donde Claude y la referencia coinciden) y "contactos" (Claude encontró contactos).
    """
    scored: list[tuple[int, str]] = []
    agree: list[str] = []
    for video_id, entry in gold.items():
        if entry.get("reviewed") or video_id not in extractions:
            continue
        pred = claude_extraction.to_eval_entry(extractions[video_id])
        score = extraction_eval.score_video(video_id, entry, Prediction(pred["guests"], pred["hosts"], pred["program"]))
        if score.errors:
            scored.append((score.errors, video_id))
        else:
            agree.append(video_id)
    scored.sort(key=lambda t: (-t[0], t[1]))
    chosen = [(video_id, "errores") for _, video_id in scored[:n_errors]]
    taken = {video_id for video_id, _ in chosen}
    rng = random.Random(seed)
    pool = sorted(i for i in agree if i not in taken)
    chosen += [(i, "coinciden") for i in rng.sample(pool, min(n_agree, len(pool)))]
    taken = {video_id for video_id, _ in chosen}
    with_contacts = sorted(
        i for i, entry in gold.items()
        if i in extractions and i not in taken and not entry.get("reviewed")
        and (extractions[i].contacts or extractions[i].unassigned_contacts)
    )
    chosen += [(i, "contactos") for i in with_contacts[:n_contacts]]
    return chosen


# --- HTML -------------------------------------------------------------------------------

_CSS = """
:root{--bg:#f4f7fb;--card:#fff;--ink:#14213d;--muted:#5b6b86;--line:#d5deec;--blue:#1d4ed8;--ok:#15803d;--warn:#b45309}
@media (prefers-color-scheme: dark){:root{--bg:#0e1626;--card:#162238;--ink:#e6edf8;--muted:#9fb0cc;--line:#2a3a57;--blue:#6ea0ff;--ok:#4ade80;--warn:#fbbf24}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
header{position:sticky;top:0;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;z-index:5;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header h1{font-size:16px;margin:0;flex:1 1 220px}button{background:var(--blue);color:#fff;border:0;border-radius:6px;padding:8px 14px;font:inherit;cursor:pointer}
button.sec{background:transparent;color:var(--blue);border:1px solid var(--blue)}main{max-width:980px;margin:0 auto;padding:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:16px}
.card.done{border-color:var(--ok)}.tag{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
h2{font-size:16px;margin:2px 0 6px}a{color:var(--blue)}details{margin:6px 0}summary{cursor:pointer;color:var(--muted)}
pre{white-space:pre-wrap;word-break:break-word;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px;margin:6px 0;font:13px/1.4 ui-monospace,monospace}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin-top:8px}
label{display:block;font-size:13px;color:var(--muted);margin-bottom:2px}textarea,input[type=text],select{width:100%;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px 8px;font:inherit}
textarea{min-height:64px;resize:vertical}.claude{font-size:13px;color:var(--muted);margin-top:2px}.claude b{color:var(--ink)}
.contacts{margin-top:10px;font-size:14px}.contacts li{margin:4px 0}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px}
.small{font-size:13px;color:var(--muted)}
@media (max-width:600px){main{padding:10px}header{padding:8px 10px}}
"""

_JS = """
const KEY = 'revision_' + document.body.dataset.sheet;
const state = JSON.parse(localStorage.getItem(KEY) || '{}');
const lines = t => t.split('\\n').map(s => s.trim()).filter(Boolean);
function collect(card) {
  const id = card.dataset.id;
  const contacts = {};
  card.querySelectorAll('select[data-contact]').forEach(s => { if (s.value) contacts[s.dataset.contact] = s.value; });
  return {
    guests: lines(card.querySelector('[data-f=guests]').value),
    hosts: lines(card.querySelector('[data-f=hosts]').value),
    program: card.querySelector('[data-f=program]').value.trim() || null,
    reviewed: card.querySelector('[data-f=reviewed]').checked,
    contacts: contacts,
  };
}
function save() {
  document.querySelectorAll('.card').forEach(c => { state[c.dataset.id] = collect(c); c.classList.toggle('done', state[c.dataset.id].reviewed); });
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {}
  const n = Object.values(state).filter(v => v.reviewed).length;
  document.getElementById('count').textContent = n + ' de ' + document.querySelectorAll('.card').length + ' revisados';
}
function restore() {
  document.querySelectorAll('.card').forEach(c => {
    const s = state[c.dataset.id]; if (!s) return;
    c.querySelector('[data-f=guests]').value = s.guests.join('\\n');
    c.querySelector('[data-f=hosts]').value = s.hosts.join('\\n');
    c.querySelector('[data-f=program]').value = s.program || '';
    c.querySelector('[data-f=reviewed]').checked = s.reviewed;
    c.querySelectorAll('select[data-contact]').forEach(sel => { sel.value = (s.contacts || {})[sel.dataset.contact] || ''; });
  });
}
function useClaude(btn) {
  const c = btn.closest('.card'), d = JSON.parse(c.dataset.claude);
  c.querySelector('[data-f=guests]').value = d.guests.join('\\n');
  c.querySelector('[data-f=hosts]').value = d.hosts.join('\\n');
  c.querySelector('[data-f=program]').value = d.program || '';
  save();
}
function download() {
  save();
  const answers = {};
  Object.entries(state).forEach(([id, v]) => { if (v.reviewed) answers[id] = v; });
  const blob = new Blob([JSON.stringify({version: 1, sheet: document.body.dataset.sheet, answers}, null, 1)], {type: 'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'respuestas_revision.json'; a.click();
}
document.addEventListener('input', save); document.addEventListener('change', save);
restore(); save();
"""

_GROUP_LABEL = {
    "errores": "Claude y la referencia no coinciden",
    "coinciden": "Coinciden (revisa que de verdad sea correcto)",
    "contactos": "Claude encontró contactos",
}


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def _contacts_html(video_id: str, video: VideoExtraction) -> str:
    items = [("a", i, c) for i, c in enumerate(video.contacts)] + [("u", i, c) for i, c in enumerate(video.unassigned_contacts)]
    if not items:
        return ""
    rows = []
    for kind, i, contact in items:
        where = f"de {_esc(contact.guest)}" if contact.guest else "sin asignar"
        extra = f" · dudoso: {_esc(contact.doubtful_reason or 'sí')}" if contact.doubtful else ""
        rel = f" · {_esc(contact.relationship)}" if contact.relationship else ""
        rows.append(
            f'<li><b>{_esc(contact.type)}</b>: {_esc(contact.value)} <span class="small">({where}{rel}{extra})</span> '
            f'<select data-contact="{kind}{i}" style="width:auto"><option value="">¿Es correcto?</option>'
            f'<option value="ok">Correcto</option><option value="bad">Incorrecto</option></select></li>'
        )
    return f'<div class="contacts"><div class="tag">Contactos que encontró Claude</div><ul>{"".join(rows)}</ul></div>'


def build_html(
    selection: list[tuple[str, str]], gold: dict[str, dict], samples: dict[str, dict],
    extractions: dict[str, VideoExtraction], sheet: str = "v3",
) -> str:
    cards = []
    for n, (video_id, group) in enumerate(selection, start=1):
        sample = samples.get(video_id, {"title": "(sin texto en las muestras)", "description": ""})
        entry = gold[video_id]
        claude = claude_extraction.to_eval_entry(extractions[video_id])
        description = sample["description"] or "(sin descripción)"
        preview, rest = description[:DESCRIPTION_PREVIEW_CHARS], description[DESCRIPTION_PREVIEW_CHARS:]
        more = f"<details><summary>Ver el resto de la descripción</summary><pre>{_esc(rest)}</pre></details>" if rest else ""
        claude_json = json.dumps(claude, ensure_ascii=False)
        cards.append(f"""
<section class="card" data-id="{_esc(video_id)}" data-claude="{_esc(claude_json)}">
  <div class="tag">{n}. {_esc(_GROUP_LABEL.get(group, group))}</div>
  <h2>{_esc(sample['title'])}</h2>
  <div><a href="{_esc(YOUTUBE_URL.format(video_id=video_id))}" target="_blank" rel="noopener">Abrir en YouTube</a>
  <span class="small"> · {_esc(video_id)} · {_esc(sample.get('published_at') or '')[:10]}</span></div>
  <pre>{_esc(preview)}</pre>{more}
  <div class="grid">
    <div><label>Invitados (uno por línea)</label><textarea data-f="guests">{_esc(chr(10).join(entry['guests']))}</textarea>
      <div class="claude">Claude: <b>{_esc(', '.join(claude['guests']) or '—')}</b></div></div>
    <div><label>Conductores (uno por línea)</label><textarea data-f="hosts">{_esc(chr(10).join(entry['hosts']))}</textarea>
      <div class="claude">Claude: <b>{_esc(', '.join(claude['hosts']) or '—')}</b></div></div>
    <div><label>Programa (vacío = ninguno)</label><input type="text" data-f="program" value="{_esc(entry.get('program') or '')}">
      <div class="claude">Claude: <b>{_esc(claude['program'] or '—')}</b></div></div>
  </div>
  {_contacts_html(video_id, extractions[video_id])}
  <div class="row"><button class="sec" type="button" onclick="useClaude(this)">Usar lo de Claude</button>
  <label style="margin:0;color:var(--ink)"><input type="checkbox" data-f="reviewed"> Revisado</label></div>
</section>""")
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Revisión de la referencia</title><style>{_CSS}</style></head>
<body data-sheet="{_esc(sheet)}">
<header><h1>Revisión de la referencia · <span id="count"></span></h1>
<button type="button" onclick="download()">Descargar mis respuestas</button></header>
<main>
<p class="small">Cada recuadro muestra lo que dice hoy la referencia (campos editables) y lo que propuso Claude debajo.
Abre el video, corrige lo que esté mal y marca «Revisado». Solo se aplican los videos marcados. Tu progreso se
guarda en este navegador; al terminar (o cuando quieras) descarga el archivo y pásaselo al script <code>apply</code>.
Un nombre va en invitados si aparece como invitado de ese video; un conductor es quien presenta la serie.</p>
{''.join(cards)}
</main><script>{_JS}</script></body></html>"""


# --- aplicar ----------------------------------------------------------------------------

def _clean_names(values: object, field: str, video_id: str) -> list[str]:
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise _fail("apply_answers", f"El video {video_id} trae '{field}' que no es una lista de textos")
    cleaned: list[str] = []
    for value in values:
        name = " ".join(value.split())
        if name and name not in cleaned:
            cleaned.append(name)
    return cleaned


def apply_answers(
    gold_path: Path, answers_path: Path, contacts_path: Path, extractions: dict[str, VideoExtraction] | None = None,
) -> dict[str, int]:
    """Aplica las respuestas a la referencia (con copia de respaldo). Devuelve conteos."""
    try:
        payload = json.loads(Path(answers_path).read_text(encoding="utf-8"))
        answers = payload["answers"]
        gold_data = json.loads(Path(gold_path).read_text(encoding="utf-8"))
        videos = gold_data["videos"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise _fail("apply_answers", f"No se pudo leer las respuestas o la referencia: {exc}", exc) from exc
    if not isinstance(answers, dict):
        raise _fail("apply_answers", "'answers' debe ser un objeto {video_id: respuesta}")

    unknown = sorted(i for i in answers if i not in videos)
    if unknown:
        raise _fail("apply_answers", f"Videos que no están en la referencia: {unknown[:5]}")

    changed = reviewed = 0
    contact_verdicts: dict[str, list[dict]] = {}
    for video_id, answer in answers.items():
        if not answer.get("reviewed"):
            continue
        entry = videos[video_id]
        new = {
            "guests": _clean_names(answer.get("guests", []), "guests", video_id),
            "hosts": _clean_names(answer.get("hosts", []), "hosts", video_id),
            "program": (" ".join(answer["program"].split()) or None) if isinstance(answer.get("program"), str) else None,
        }
        if any(entry.get(k) != v for k, v in new.items()):
            changed += 1
        entry.update(new)
        entry["reviewed"] = True
        reviewed += 1
        verdicts = answer.get("contacts") or {}
        if verdicts and extractions and video_id in extractions:
            ordered = [("a", i, c) for i, c in enumerate(extractions[video_id].contacts)] + [
                ("u", i, c) for i, c in enumerate(extractions[video_id].unassigned_contacts)]
            contact_verdicts[video_id] = [
                {"type": c.type, "value": c.value, "guest": c.guest, "verdict": verdicts[f"{kind}{i}"]}
                for kind, i, c in ordered if verdicts.get(f"{kind}{i}") in ("ok", "bad")
            ]
    if not reviewed:
        raise _fail("apply_answers", "Ninguna respuesta está marcada como revisada; no se cambió nada")

    backup = Path(gold_path).with_name(f"{Path(gold_path).stem}.backup_{datetime.now():%Y%m%d_%H%M%S}.json")
    shutil.copy2(gold_path, backup)
    Path(gold_path).write_text(json.dumps(gold_data, ensure_ascii=False, indent=1), encoding="utf-8")
    contact_ok = contact_bad = 0
    if contact_verdicts:
        existing: dict = {}
        if Path(contacts_path).exists():
            existing = json.loads(Path(contacts_path).read_text(encoding="utf-8"))
        existing.update(contact_verdicts)
        Path(contacts_path).write_text(json.dumps(existing, ensure_ascii=False, indent=1), encoding="utf-8")
        contact_ok = sum(c["verdict"] == "ok" for v in contact_verdicts.values() for c in v)
        contact_bad = sum(c["verdict"] == "bad" for v in contact_verdicts.values() for c in v)
    logger.info("[scripts.review_sheet.apply_answers] Respaldo en %s", backup.name)
    return {"reviewed": reviewed, "changed": changed, "contacts_ok": contact_ok, "contacts_bad": contact_bad}


# --- línea de comandos -----------------------------------------------------------------

def run_export(args: argparse.Namespace) -> int:
    gold = extraction_eval.load_gold(args.gold)
    samples = extraction_eval.load_sample_videos(args.samples_dir)
    extractions = load_extractions(args.pilot_dir)
    selection = select_videos(gold, extractions=extractions, n_errors=args.errors, n_agree=args.agree,
                              n_contacts=args.contacts, seed=args.seed)
    if not selection:
        print("No hay videos por revisar (¿ya están todos revisados?).")
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_html(selection, gold, samples, extractions), encoding="utf-8")
    counts = {g: sum(1 for _, x in selection if x == g) for g in _GROUP_LABEL}
    print(f"Hoja de revisión: {args.out}")
    print(f"{len(selection)} videos: {counts['errores']} con desacuerdo, {counts['coinciden']} que coinciden, {counts['contactos']} con contactos.")
    print("Ábrela en el navegador, revisa, marca «Revisado» y descarga tus respuestas.")
    return 0


def run_apply(args: argparse.Namespace) -> int:
    extractions = load_extractions(args.pilot_dir)
    result = apply_answers(args.gold, args.answers, args.contacts_review, extractions)
    print(f"Videos revisados aplicados: {result['reviewed']} (con cambios: {result['changed']}).")
    if result["contacts_ok"] or result["contacts_bad"]:
        print(f"Contactos: {result['contacts_ok']} correctos, {result['contacts_bad']} incorrectos.")
    print("Respaldo de la referencia guardado junto al archivo. Vuelve a medir con scripts.eval_extraction.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Hoja de revisión de la referencia de invitados.")
    sub = p.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    common.add_argument("--pilot-dir", type=Path, default=DEFAULT_PILOT_DIR)
    export = sub.add_parser("export", parents=[common], help="Generar la hoja HTML")
    export.add_argument("--samples-dir", type=Path, default=DEFAULT_SAMPLES_DIR)
    export.add_argument("--out", type=Path, default=DEFAULT_OUT)
    export.add_argument("--errors", type=int, default=15, help="Videos con más desacuerdo")
    export.add_argument("--agree", type=int, default=15, help="Videos donde coinciden (al azar)")
    export.add_argument("--contacts", type=int, default=10, help="Videos con contactos de Claude")
    export.add_argument("--seed", type=int, default=7)
    apply = sub.add_parser("apply", parents=[common], help="Aplicar las respuestas a la referencia")
    apply.add_argument("answers", type=Path, help="Archivo respuestas_revision.json descargado")
    apply.add_argument("--contacts-review", type=Path, default=DEFAULT_CONTACTS_REVIEW)
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    args = build_parser().parse_args(argv)
    try:
        return run_export(args) if args.command == "export" else run_apply(args)
    except (ReviewError, EvalError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
