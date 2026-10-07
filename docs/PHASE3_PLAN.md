# Plan — Fase 3: Pipeline de ingesta (ETL con IA) + Staging Review

**Estado: completada (2026-09-28)**, los 8 pasos hechos y probados (294 pruebas de backend,
117 de frontend). Queda sin implementar, a propósito, el disparador de la ingesta (FR-011: un
botón en la app o una tarea programada) — se dejó para una fase final, según lo acordado; hoy
se corre por código (`app.services.pipeline.run_batch`). El aviso de privacidad (LFPDPPP) sigue
pendiente con el Ing. Israel, sin bloquear nada hasta la carga histórica masiva de la Fase 7.
Documentación general actualizada al cierre: `docs/ARCHITECTURE.md` (sección "Ingesta con IA"),
`docs/DATA_MODEL.md` (tablas de staging) y `README.md`. Detalle paso a paso abajo.

Preguntas abiertas repasadas con el usuario (2026-09-28): arranca a
codificar sin esperar el aviso de privacidad, que no bloquea el código (solo la carga masiva de
la fase 7). **Paso 1 (configuración y contrato de datos) hecho**: `get_ollama_base_url` y
`get_ollama_model` en `backend/app/core/config.py`; contrato del LLM en
`backend/app/schemas/ingestion.py` (`VideoAnalysis`, `GuestCandidate`, `ContactCandidate`), con
pruebas en `backend/tests/test_config.py` y `backend/tests/test_ingestion_schema.py`.
**Paso 2 (modelo de staging) hecho**: migración `0006` con `ingestion_runs` (historial de
corridas), `ingestion_run_errors` (errores por video, no detienen el lote),
`staging_guest_candidates` y `staging_contact_candidates` (candidatos con confianza
cruda/ajustada, estado pendiente/aceptado/rechazado y vínculo al registro final una vez
aceptados) en `backend/app/models/ingestion.py`; además `videos.possible_duplicate_of_video_id`
para la regla de casi duplicados. Pruebas en `backend/tests/test_ingestion_models.py`.
**Paso 3 (servicio YouTube → BD) hecho**: `backend/app/services/ingestion.py`
(`upsert_video`/`sync_videos`/`sync_channel`), idempotente por `youtube_video_id` y aplicando
la regla de "el real gana sobre el manual" ya acordada. Se completó `youtube_client.py` con los
metadatos que ya estaban modelados en `Video` pero sin usarse (`channel_id`, `channel_title`,
`thumbnail_url`, `duration_seconds` vía `parse_duration`). Pruebas en `backend/tests/test_ingestion.py`
y ampliadas en `backend/tests/test_sample_videos.py`.
**Paso 4 (reglas de regex previas al LLM) hecho**: `backend/app/services/regex_rules.py` con
`extract_contacts` (URLs, `ETIQUETA:` + usuario, correos, deduplicados), `extract_name_candidates`
(los 3 patrones de formato de "Reglas del pipeline": después de dos puntos, `con Nombre`,
MAYÚSCULAS entre paréntesis — confianza baja/media, la asigna el paso 6) e
`is_no_guests_candidate` (regla conservadora de 4 condiciones; distingue "nombre propio fuerte"
—los marcadores de alta señal `Invitado:`/`presenta a`/`nombre real:`/`es el seudónimo de`— de
los patrones de formato más amplios, usados solo en las condiciones 3 y 4). Pruebas en
`backend/tests/test_regex_rules.py`, incluidos los ejemplos textuales citados en este documento.
**Paso 5 (servicio Ollama) hecho**: `backend/app/services/ollama_client.py` —
`analyze_video()` arma el prompt (título + descripción + catálogos existentes de categoría,
tipo de video, alcaldía, conductor y programa, para que el modelo solo señale coincidencias
reales y nunca invente), pide salida conforme al esquema de `VideoAnalysis` (paso 1) vía
`format` de Ollama, valida con Pydantic y reintenta (por defecto 3 veces) si el JSON es
inválido o no cumple el contrato; error claro (`OllamaError`) si se agotan los intentos.
Pruebas con transporte HTTP simulado en `backend/tests/test_ollama_client.py` (sin red ni
Ollama real). **Paso 6 (orquestador idempotente) hecho**: `backend/app/services/pipeline.py` —
`process_video()` hace regex (paso 4) → LLM (paso 5) → filas en `staging_guest_candidates`/
`staging_contact_candidates` (paso 2) para un video, marca `guest_status='no_guests'` cuando la
regla de regex lo detecta automáticamente (CLAUDE.md: "reclasificable por un humano"), calcula
`possible_duplicate_of_video_id` (título+descripción normalizados iguales y `published_at` a
±14 días, según la evidencia real ya documentada) y es idempotente vía `Video.last_ingested_at`
(migración `0007`). `run_batch()` aplica esto a un lote de videos nuevos del canal usando el
sync del paso 3, sin detener el lote si un video falla (`IngestionRunError`) y llevando el
historial en `IngestionRun`. Dejé documentados en el código, como decisiones mías a validar con
resultados reales, los valores concretos de ajuste de confianza (+0.15 título+descripción,
+0.10 solo título, -0.20 posible grupo) y la confianza inicial de los patrones de regex (0.30-
0.40 para nombres por formato, 0.7 para contactos por regex) — el plan solo daba las reglas
cualitativas. Pruebas en `backend/tests/test_pipeline.py`. Con esto termina la lógica de
ingesta. **Paso 7 backend (Staging Review) hecho**: `backend/app/services/staging.py` +
`backend/app/schemas/staging.py` + `backend/app/api/staging.py` (rutas `/staging/*`,
protegidas). Cola principal = `GET /staging/guest-candidates` y `/contact-candidates`
(`?status=pending` por defecto), ordenada por confianza **ajustada**, no la cruda (regla del
pipeline). Aceptar invitado (`POST .../accept`): crea uno nuevo o vincula uno existente
(`existing_guest_id`) editando solo lo enviado, crea su `Participation` (sin duplicar si ya
existía), y sugiere existentes por nombre parecido en `GET .../suggestions` (FR-001,
reutilizando `normalize_name`, comparando en Python como `catalogs._ensure_unique` — la tabla
de invitados no justifica todavía una búsqueda por similitud en SQL). Aceptar contacto exige
`guest_id` explícito del revisor (nunca se infiere solo de `guest_candidate_id`); crea el
`Contact` con `source='video_description'` y `verified=False`. Rechazar cierra el candidato sin
crear nada. La "vista aparte" de videos "sin invitados" reutiliza el `GET /videos` de la fase 2
con un filtro `guest_status` nuevo (`?guest_status=no_guests`); reclasificar también reutiliza
el `PATCH /videos/{id}` ya existente (ya aceptaba `guest_status`) — no hizo falta ninguna ruta
nueva para eso. Pruebas en `backend/tests/test_staging.py` (servicio) y
`backend/tests/test_staging_api.py` (endpoints). Sin migración nueva (las tablas ya existían
desde el paso 2). **Paso 7 frontend hecho**: `frontend/src/pages/staging/` — `Staging.jsx` (pestañas, como
`Catalogs.jsx`), `GuestCandidateQueue.jsx`, `ContactCandidateQueue.jsx` y `NoGuestsVideos.jsx`,
en `/staging/guest-candidates`, `/staging/contact-candidates` y `/staging/no-guests` (enlace
"Staging Review" en la navegación). Cola de invitados: por cada candidato pendiente, "Revisar"
despliega las sugerencias de invitados parecidos (FR-001, un botón "Vincular con este" por
sugerencia) y un formulario para crear uno nuevo (nombre, organización, rol, edad, alcaldía,
categorías existentes/nuevas, notas) o rechazar. Cola de contactos: el revisor elige
explícitamente a qué invitado se atribuye (select) y el tipo de contacto, con el valor
precargado y editable. Videos "sin invitados": botón "Sí tiene invitados" que regresa el video
a `pending` y navega a su detalle para agregar la participación con los controles ya existentes
de la fase 2. Extendí `frontend/src/test/fakeBackend.js` con las rutas `/staging/*` y el filtro
`guest_status` de `/videos`. Pruebas en `frontend/src/pages/staging/Staging.test.jsx`. Encontré
y corregí 3 bugs propios durante la revisión antes de pedir que se corrieran las pruebas (ver
mensaje al usuario): un `data?.items.map` que no protegía bien contra respuesta nula, un
`aria-label` puesto en un `<div>` en vez del `<form>`, y una consulta de texto ambigua en mi
propia prueba. Con esto termina el paso 7.
**Paso 8 (cierre) hecho**: documentación general actualizada (`ARCHITECTURE.md`,
`DATA_MODEL.md`, `README.md`, este plan); 294 pruebas de backend y 117 de frontend pasando.
Commits propuestos al usuario, pendientes de su decisión (nunca se hace `git push`).

**Adenda tras el cierre**: el usuario pidió un botón de ingesta con lote fijo en 5 videos, para
una demostración rápida (no la ingesta programada, esa sigue sin construirse a propósito).
`app.services.pipeline.trigger_manual_run` arma los clientes HTTP y la configuración desde
variables de entorno y llama a `run_batch`; `POST /ingestion/runs` (`app/api/ingestion.py`) lo
expone, corriendo de forma síncrona (la petición no responde hasta terminar el lote — puede
tardar varios minutos con el LLM en CPU). El botón vive en `Staging.jsx`
(`IngestionRunner.jsx`), arriba de las pestañas. Sigue sin haber ingesta periódica.

**Segunda adenda**: la primera corrida real (5 videos, canal real) mostró un hueco en las
reglas — una descripción con "Arween Tarot **es el nombre artístico de** Wendolyn Arellano
Hernández..." no producía ningún candidato, porque el patrón de alta señal solo reconocía "es
el **seudónimo** artístico de" (no "nombre"), y esas frases de alta señal nunca generaban un
candidato por regex de todas formas — solo se usaban para la regla de "sin invitados". Se
corrigió: `regex_rules._STRONG_MARKER_PHRASE` ahora acepta "nombre" o "seudónimo", y se agregó
un 4° patrón a `extract_name_candidates` (`high_signal`) que si captura el nombre después de
la frase, con confianza 0.65 (más alta que los otros 3, que son 0.30-0.40). El prompt del LLM
(`ollama_client.py`) se actualizó igual. Pendiente, identificado pero no corregido a propósito
(necesita más evidencia real antes de diseñarlo bien): nombres completos en MAYÚSCULAS fuera de
paréntesis (ej. "HUMBERTO ESTRADA GIGO") siguen sin detectarse por regex.

**Tercera adenda (2026-09-30) — mejora de la extracción de invitados y conductores**: el
usuario reportó que el LLM (`qwen2.5:3b`, un video a la vez) es muy débil y casi todos los
videos caen a revisión manual; pidió **no ajustar los umbrales de confianza** sino mejorar la
extracción, y acercarla a lo que se obtuvo cuando Claude analizó 90 videos juntos (razonamiento
con contexto de la serie), pero a escala de ~3,500 videos. Enfoque elegido: **opción 1, "dos
etapas" local** (sin cambiar el stack), midiendo antes de decidir si hace falta la API de
Claude por lotes (estimada en ~15-20 USD con Sonnet 5.5; cambiaría el stack y enviaría datos
públicos de YouTube a un servicio externo, así que requiere aprobación explícita).
- *Etapa 1 (determinista, sobre todo el corpus)*: agrupar videos por programa/plantilla de
  título y detectar por frecuencia los conductores recurrentes (hashtags repetidos dentro de
  una serie = conductor o producción; hashtags únicos = invitados), más parser de hashtags
  (`#KarimmKury` → Karimm Kury) y de títulos (`Programa: A, B y C`).
- *Etapa 2 (LLM)*: recibe esos candidatos ya extraídos más el perfil de la serie y solo los
  clasifica (invitado / conductor / banda / tema); ya no descubre nombres desde cero.
- *Evidencia que motiva el diseño* (leídos los 150 videos de muestra completos): el rol
  depende de la serie, no del video (Dj Rayas e Imperial Lion son conductores en "Raíz y
  Cultura" aunque aparezcan tras los dos puntos; Arcángel Negro es conductor en "Música
  Expansiva" pero invitado en "Entrevista Arcángel Negro en Taco Shock"); ~28% de los videos no
  nombra a nadie (lo correcto es no inventar).
- *Referencia para medir*: `backend/data/gold/guests_gold.json` (150 videos, con programa,
  invitados, conductores y dudosos), etiquetada por Claude y **pendiente de revisión del
  usuario** (página de revisión con campos editables, publicada como artifact privado:
  https://claude.ai/artifact/8rr4HdjPPMvF3Dn8AMzAAn; su código y generador están en
  `backend/data/gold/review_page/`). Sigue **parcialmente revisada**: 10 videos corregidos por
  el usuario (`reviewed: true`) y 2 marcados "correcto" sin ID; el resto es etiqueta de Claude.
  Campos extra de la referencia: `program`, `outside_metadata` (nombres que el usuario vio
  fuera del título/descripción guardados; no se penalizan), `host_aliases`.
- **Hecho (2026-10-01, sin commitear ni ejecutar)**: evaluación del extractor contra la
  referencia — `app/services/extraction_eval.py` (puntuación), `scripts/eval_extraction.py`
  (corre regex + LLM actual con caché reanudable, `--limit`, `--only-reviewed`,
  `--rescore-only`, `--no-catalog`) y `tests/test_extraction_eval.py`.
- **Línea base medida (2026-10-02, `qwen2.5:3b`, 10 videos, sin commitear)**: invitados
  precisión 44 % / recall 50 %; conductores recall 0 % (faltan los 7); programa 4 de 10; 3 roles
  cambiados; los 3 videos sin invitados de la referencia recibieron invitados inventados.
  `pytest tests/test_extraction_eval.py`: 47 pasan.
- **Hecho (2026-10-02, sin commitear ni ejecutar)**: módulo determinista de perfil por serie,
  `app/services/series_profile.py` (+ `tests/test_series_profile.py` y el extractor
  `--extractor profile` en `scripts/eval_extraction.py`, instantáneo, sin LLM). Decisiones del
  usuario: conductor = aparece en al menos 3 videos de la serie y en al menos 50 % de ellos
  (con el conductor en el catálogo bastan 2 videos); el programa solo se asigna contra el
  catálogo. Siguiente: que el usuario corra los tests nuevos y
  `python -m scripts.eval_extraction --extractor profile`, luego `VideoAnalysis` con lista de
  conductores y el prompt de la etapa 2.
- **Medición del perfil sin LLM (2026-10-02, 150 videos; catálogos simulados con la propia
  referencia, así que es optimista)**: invitados 87 % precisión / 79 % recall; conductores
  94 % / 78 %; programa 97 %; 0 roles cambiados. Solo los 10 revisados por el usuario: invitados
  70 % / 64 %, conductores recall 29 %. Ajustes posteriores: un hashtag contenido en el nombre de
  la serie (`#MagX`) no cuenta como conductor; `names_match` iguala nombres con y sin espacios
  (`7SinsTattoStudio` = `7 Sins Tatto Studio`).
- **Hecho (2026-10-02, sin commitear ni ejecutar)**: etapa 2, `app/services/candidate_classifier.py`
  (+ `tests/test_candidate_classifier.py`): el LLM solo da un veredicto (guest / group / host /
  topic) a los candidatos dudosos (tras los dos puntos, descripción, hashtags sin rol); no agrega
  nombres y no se llama si no hay dudosos. `ollama_client._call_ollama` acepta un `schema`
  opcional. Medible con `--extractor profile_llm`; **aún no está conectado a `pipeline.py`** ni
  a `VideoAnalysis` (conductores como lista): se conecta después de la medición.
- **Medición de la etapa 2 (2026-10-02, 150 videos)**: con el LLM promoviendo hashtags a
  invitado y moviendo roles, **empeoró** respecto al perfil solo: invitados 78.8 % / 80.4 %
  (perfil: 89.3 % / 81.7 %), conductores 91.6 % / 80.6 % (perfil: 98.8 % / 78.7 %), 13 roles
  cambiados (perfil: 0); lo único que mejoró fue "videos sin invitados con invitados
  inventados" (9 -> 5). Decisión: por defecto el LLM **solo descarta** lo que no es persona
  (`apply_verdicts`; no puede descartar un nombre tras los dos puntos que la descripción repite);
  promover hashtags y mover roles quedan como interruptores (`--promote-hashtags`,
  `--llm-host-verdict`) para medirlos por separado. La caché de `profile_llm` guarda los
  veredictos crudos, así que cambiar la política se re-puntúa con `--rescore-only` sin LLM.
- **Política del LLM medida (2026-10-02, 150 videos)**: solo descartar -> invitados 94.5 % /
  79.1 %, conductores 98.8 % / 78.7 %, 0 roles cambiados (se queda como política por defecto);
  + promover hashtags -> 78.9 % / 83.0 % y 9 roles cambiados; + veredicto de conductor -> conductores
  94.6 % / 80.6 %, invitados 94.4 % / 77.1 %, 3 roles cambiados. Los hashtags sin rol podrían
  mostrarse en Staging Review como "posibles" de confianza baja (decidir al rediseñarla).
- **Hecho (2026-10-02, sin ejecutar)**: `series_profile` también lee "Conduce: X" / "Conducen X y Y"
  en la descripción (fuente `description_conduce`; cuenta para la recurrencia de la serie).
- **Medición con "Conduce X" en la descripción (2026-10-02, 150 videos)**: perfil + LLM que solo
  descarta: invitados 94.5 % / 79.1 %, conductores 97.8 % / 81.5 %, programa 96.7 %, 0 roles
  cambiados. Conocido: "Mayuel" (errata en la descripción) no se corrige a "Mayahuel" (parecido 0.857
  < 0.9); "Raiz & Cultura" no se reconoce como "Raíz y Cultura" (`&` vs `y`).
- **Hecho (2026-10-02, sin commitear ni ejecutar) — conectado a `pipeline.py`, solo invitados**:
  `process_video` arma los invitados con `series_profile` (perfiles calculados una vez por lote con
  todos los videos de la BD, `_build_series`) + `candidate_classifier` (el LLM solo descarta; si
  falla se conservan los candidatos); se guardan con `extraction_method='regex'` (no hay migración)
  y las confianzas que ya existían (`high_signal` / `after_colon`). `analyze_video` se conserva para
  contactos, categoría (se copia al invitado si es el mismo nombre), tipo de video y alcaldía; sus
  invitados ya no se usan. **Pendiente**: guardar conductor y programa (hoy no hay dónde en staging;
  `Video.program_id` existe y los conductores son del programa, `Program.hosts` N↔N) — decidir junto
  con el rediseño de Staging Review.
- **Hecho (2026-10-02, sin commitear; pruebas escritas, sin ejecutar) — rediseño de Staging Review
  por video**: pestaña "Revisión por video" (reemplaza las colas "Invitados candidatos" y "Videos
  sin invitados"; "Contactos candidatos" se conserva). Una tarjeta por video: texto original a la
  izquierda; a la derecha programa, conductores e invitados editables, y los botones "Correcto" /
  "Sin invitados" / "Descartar candidatos". Barra de filtros con contadores (Pendientes, Con
  contactos, Sin candidatos, Sin invitados, Posibles duplicados) y búsqueda por título.
  Backend: `GET /staging/review/videos`, `GET /staging/review/counts` y `POST
  /staging/review/videos/{id}/resolve` (`app/services/staging_review.py`; valida todo antes de
  escribir; vincula solo con el invitado de nombre idéntico, nunca por parecido).
  **Etapa B**: migración `0008_staging_video_suggestions` (tabla `staging_video_suggestions`, una
  fila por video con el programa del catálogo y los conductores propuestos); el pipeline la llena
  y `python -m scripts.backfill_suggestions` la crea para los videos ya ingeridos. Al resolver, el
  programa se asigna a `videos.program_id` y los conductores a `program_host_links` (se crean en
  el catálogo si no existían; no se quitan los que el programa ya tenía); la sugerencia se cierra
  (aceptada si se envió programa o conductores, rechazada si no). Los conductores son del programa:
  sin programa no se pueden guardar.
- **Hecho (2026-10-02, sin commitear; pruebas escritas, sin ejecutar) — "Dudosos" y conductores
  habituales en Staging Review**: (1) los nombres que la ingesta no puede clasificar (hashtags sin
  rol) ya no se descartan: se guardan en `staging_video_suggestions.doubtful_names` con la pista del
  LLM (`guest`/`host`/`unknown`; lo que el LLM llama `topic` es ruido y sí se descarta) y la tarjeta
  los muestra con "→ invitado", "→ conductor" y "Descartar" (un clic; es la sección "Dudosos" de la
  página de revisión del artifact). (2) Los conductores que se repiten en la serie pero el texto del
  video no menciona se guardan en `usual_host_names` y se unen a los del catálogo del programa
  (asignado o sugerido): botones "+ nombre" de un clic; nunca se asignan solos. Migración
  `0009_suggestion_doubtful_and_usual_hosts`. Para que los 23 videos ya ingeridos aprovechen las
  reglas nuevas: `python -m scripts.backfill_suggestions` (completa lo pendiente, solo reglas) o,
  mejor, `python -m scripts.reprocess_videos --yes` (los vuelve a analizar con el LLM; solo toca lo
  que nadie ha revisado, sin programa asignado y no marcado "sin invitados").
- **Reglas nuevas de la descripción (2026-10-02)**: "con nosotros X y Y" (invitados) y los nombres ya
  no cruzan líneas (`MC PELA` ya no sale como `MC PELA Hoy`); un tratamiento suelto ("Ing") no es
  nombre.
- **Experimento: el LLM como segunda opinión de invitados** (`--extractor profile_llm_guests`,
  `candidate_classifier.second_opinion_guests`): suma los invitados que `analyze_video` encuentra y
  las reglas no, aceptándolos solo si el nombre aparece literal en el título o la descripción y no es
  conductor ni programa; modos `union` y `fallback`. **Resultado (2026-10-02, primeros 58 de los 150
  videos; la corrida con Ollama se trabó y se detuvo en 58)**: **cero aciertos nuevos** (53 aciertos
  con y sin segunda opinión); `union` agrega 1 falso positivo (precisión 94.6 % -> 93.0 %) y
  `fallback` no cambia nada. `qwen2.5:3b` devolvió invitados en solo 13 de 58 videos y, en los 5
  donde las reglas se quedaron cortas, devolvió lista vacía. **Decisión: no se activa en el
  pipeline** (la función queda por si se prueba un modelo mayor). Mejor camino para esos casos:
  reglas más completas y los "Dudosos" de un clic.
- **Reglas nuevas tras ese diagnóstico (2026-10-02, 150 videos)**: `;` separa programa e invitados
  como `:` ("Revoweed; A, B y C"); una lista entera entre comillas (`"A & B".`) ya no se descarta
  (era un efecto no deseado de la guarda de comillas); "presenta live set de X". Perfil + LLM que
  solo descarta: invitados 94.2 % precisión / **84.3 % recall** (antes 94.5 % / 79.1 %), conductores
  97.8 % / 81.5 %, programa 96.7 %, 0 roles cambiados; solo el perfil: 89.3 % / 86.9 %. Pendiente
  conocido: "Adictos Hip - Hop" se parte en dos por el guion con espacios.
- **Segunda opinión del LLM con un prompt simple (2026-10-02, 150 videos)**: el experimento anterior
  midió un prompt malo, no al modelo: `analyze_video` pide 8 cosas a la vez y además dice "bandas no
  como invitado", y `qwen2.5:3b` devolvía listas vacías incluso en "VINCENT VAN TRIO". Con **una sola
  pregunta** ("¿quiénes son los invitados?", `candidate_classifier.simple_guest_names`, extractor
  `--extractor profile_llm_simple`) y exigiendo que el nombre aparezca literal en el texto:
  base 94.2 % precisión / 84.3 % recall (123 listas exactas); **modo `fallback` (solo si las reglas no
  encontraron a nadie) 91.4 % / 90.2 % (130 exactas, +9 aciertos, +5 falsos)**; modo `union`
  87.5 % / 91.5 % (126 exactas, +11 aciertos, +12 falsos). En los 10 videos revisados por el usuario:
  recall 63.6 % -> 72.7 % con ambos. Falsos positivos típicos del modo `fallback`: nombres de pila que
  solo están en hashtags (`#VERO`, `#Lisa`, `#Jordi`) y videos con varios artistas mencionados en la
  descripción (5 de los 9 falsos vienen de un solo video, "V2H T.V."). **Recomendado, aún sin
  conectar a `pipeline.py`: modo `fallback`.** **Aprobado y conectado (2026-10-02)**:
  `pipeline._second_opinion_names` pide la segunda opinión solo cuando las reglas no hallaron
  invitados; acepta nombres literales en el texto que no sean conductores ni programas; se guardan
  como `StagingGuestCandidate` con `extraction_method='llm'` y confianza 0.30 (el valor más bajo que
  ya existía, aprobado por el usuario); si el LLM falla el video se procesa igual; lo que el LLM propone
  deja de salir como "dudoso". Los videos ya ingeridos y sin revisar se rehacen con
  `python -m scripts.reprocess_videos --yes`.
- **Lo que enseñaron las 10 correcciones del usuario**: (1) el texto tras los dos puntos del
  título es invitado aunque parezca banda o tema ("Viaje a Marte", "Último Respiro"); (2) un
  hashtag con nombre de persona no es conductor por serlo: lo es el que se repite en la serie
  (Charli Valerio y Charly Villalobos eran invitados de "Rodando en el Rock"); (3) hay nombres en
  minúsculas pegados en hashtags (`#juancid`, `#Danielpsicologo`); (4) un evento puede contar como
  programa ("Expomoto 2023"); (5) `VideoAnalysis.host_match` admite un solo conductor y los
  videos tienen hasta tres: pasar a lista; (6) dos nombres solo se ven fuera de los datos
  guardados (pregunta abierta: ¿dónde los vio el usuario? ¿la API recorta la descripción?).
- **Siguientes pasos, en orden**: (1) el usuario corre `pytest tests/test_extraction_eval.py` y
  `python -m scripts.eval_extraction --limit 10` (luego completo) y pasa la salida = línea base;
  (2) módulo determinista de perfil por serie (agrupar por programa/plantilla, conductores por
  frecuencia, parser de hashtags con camelCase y minúsculas, parser de `Programa: A, B y C`);
  (3) `VideoAnalysis` con lista de conductores; (4) nuevo prompt: el LLM clasifica candidatos con
  el perfil de la serie (invitado / conductor / banda / tema); (5) segunda medición contra la
  línea base; (6) pedir al usuario revisar ~15 videos al azar que no eran dudosos para calibrar
  el resto de la referencia; (7) con los números, decidir si hace falta la API de Claude por
  lotes; (8) recién entonces, ajustar Staging Review.
- **Decisión pendiente**: `backend/data/` completo está en `.gitignore`, así que la referencia
  y las muestras no se versionan (contienen nombres de personas y el aviso de privacidad sigue
  pendiente). Se dejó solo local; el usuario puede cambiarlo.
- **Pendiente acordado — ajustar Staging Review *después* de esta mejora** (no antes): al
  usuario le resultó más sencilla la página de revisión que la pantalla actual de Staging
  Review. Ideas a considerar entonces: vista centrada en el video (su texto junto a las
  etiquetas), campos editables separados (programa, invitados, conductores), filtros con
  contadores y un botón rápido de "Correcto". No se toca Staging Review hasta cerrar la mejora
  de extracción.

Alcance según `PROJECT_BRIEF.md`
(sección 7, FR-007, FR-009, FR-011, FR-013, FR-014 y "Pipeline ligero de IA"). Estado de partida:
Fase 2 completada (auth, catálogos, invitados, contactos, videos manuales con `source`, participaciones).

## Alcance
- Traer de YouTube Data API v3 los videos del canal `@xlivemedios`: solo título y descripción (sin transcripciones) más los metadatos ya modelados en `videos`, con `source = 'youtube'`.
- Extraer con Ollama (modelo local ~3B) **candidatos** a invitado y a contacto por video, con nivel de confianza. Todo es candidato hasta validación humana.
- Staging Review en la app: validar, editar o rechazar candidatos antes de convertirlos en invitados, contactos y participaciones.
- Idempotente por `youtube_video_id`: reprocesar no duplica.

Fuera de esta fase: buscador y filtros (4), exportación (5), re-contacto (6), carga histórica masiva (7; aquí se prueba con lotes pequeños), streaming/transcodificación (fuera de alcance del proyecto).

## Pasos propuestos (cada uno con pruebas y commit propuesto)
1. **Configuración y contrato de datos**: variables `YOUTUBE_API_KEY`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL` (ya están en `.env.example`); definir el JSON de salida del LLM (invitados, categorías sugeridas, contactos, confianza, "sin invitados").
2. **Modelo de staging** (migración `0006`; la `0005` ya la usan los conductores): tablas de candidatos de invitado y de contacto (video, valores propuestos, confianza, estado pendiente/aceptado/rechazado, vínculo al registro final una vez aceptado) y registro de corridas de ingesta (fecha, videos, errores). Se diseñan aquí, no antes (ver `ARCHITECTURE.md`).
3. **Servicio YouTube**: listar los videos del canal con paginación, manejo de errores y cuota; guardarlos en `videos` sin duplicar (`youtube_video_id`). Las pruebas usan respuestas simuladas, sin red.
4. **Reglas previas al LLM**: extraer enlaces y correos con expresiones regulares; detectar videos "sin invitados" (FR-014) con reglas simples (detalle en "Reglas del pipeline" abajo).
5. **Servicio Ollama**: prompt con título y descripción, salida estructurada validada con Pydantic, tiempo límite, reintentos y manejo de JSON inválido; un video a la vez. Pruebas con el cliente simulado.
6. **Orquestador idempotente**: procesa un video (reglas → LLM → candidatos), omite los ya procesados, registra errores por video sin detener el lote; se dispara a demanda desde la app o por script.
7. **Staging Review (backend y frontend)**: cola principal de candidatos pendientes; vista aparte para videos "sin invitados" (reclasificables); aceptar (crea o vincula invitado, participación y contactos con `source = video_description` y `verified = false`), editar antes de aceptar, o rechazar. Sugerir invitados existentes por nombre parecido para no duplicar (FR-001), reutilizando `normalize_name`.
8. **Cierre**: documentación, revisión de pruebas y commit propuesto.

## Reglas del pipeline (evidencia real: 150 de 3366 videos del canal, dos muestras independientes)
Propuesta acordada con el usuario para lo que hacen el paso 4 (reglas previas) y el paso 5
(qué decide el LLM). Ejemplos citados son textuales, de `backend/data/samples/`.

**Reglas previas al LLM (regex, antes del modelo):**
- Contactos: URLs completas y patrones `ETIQUETA:` + usuario (`FACEBOOK:`, `IG:`, `YOUTUBE:`,
  `INSTAGRAM:`, `TIKTOK:`) y correos en `description` → candidatos `source='video_description'`.
- "Sin invitados" (FR-014), candidato automático **solo si se cumplen todas**: (1) ningún
  nombre propio fuerte en título ni descripción, (2) ninguna palabra clave de invitado/conducción
  (`invitado`, `presenta a`, `conduce`, `entrevista`, `platicamos con`), (3) descripción vacía y
  título sin nombre reconocible, (4) vocabulario de evento genérico (`foro`, `torneo`) sin
  nombre de persona. Si falta cualquiera, el video va a la cola normal — nunca "sin invitados"
  por default.

**Qué propone el LLM (título + descripción, sin transcripción):**
- **Invitado**: prioriza patrones de alta señal (`Invitado:`, `presenta a`, `nombre real:`,
  `es el seudónimo artístico de`). Nombre en título y descripción = confianza alta; solo en
  descripción = media/baja. Bandas/colectivos se marcan "posible grupo, no persona", no se
  proponen como invitado individual.
- **Categoría**: solo con texto biográfico que la sustente, o "categoría nueva sugerida".
- **Contactos**: complementa los de regex solo si hay dato en prosa, siempre baja confianza.
- **Tipo de video**: solo con palabra clave explícita. "Podcast" no apareció en 150 videos de
  muestra — el catálogo lo admite igual, la señal de texto rara vez lo va a disparar.
- **Alcaldía del evento**: solo si el texto nombra una alcaldía oficial de CDMX literalmente
  (0 casos en 150 videos). Colonias/zonas (Zona Rosa, Ajusco) o fuera de CDMX (Ecatepec) no
  cuentan — evita falsos positivos.
- **Conductor y programa**: solo por coincidencia contra el catálogo existente (reutilizando
  `normalize_name`), nunca se crea uno nuevo desde el LLM. Casos con conductor e invitado
  pegados en el mismo título van a revisión humana sin asignar rol.
- **Confianza**: se guarda la cruda del LLM más un ajuste por señales objetivas (título+
  descripción = a favor, solo descripción = neutro, ambigüedad persona/banda = en contra);
  Staging Review ordena por el ajuste, no por la confianza cruda (el modelo de 3B calibra mal).
- **Casi duplicados**: si título normalizado + descripción coinciden fuerte contra otro video
  **y además `published_at` está cerca** (ver evidencia abajo — condición obligatoria, no
  opcional), se marca "posible duplicado de `youtube_video_id X`" en staging — nunca se
  fusiona ni descarta solo.

**"Expandete TV" es un programa del catálogo, no el nombre prohibido del canal** (aclarado en
`CLAUDE.md`): sus videos se analizan igual que cualquier otro y se asocian al programa
"Expandete TV" por el mismo matching de catálogo — sin regla especial. Señal validada en dos
muestras independientes (~23-25% de los videos revisados).

**Patrones regex adicionales (candidatos de nombre por formato, confianza baja/media):**
Se suman a las reglas de alta señal de arriba, para cubrir nombres sin palabra clave
explícita. Encontrados al comparar contra spaCy NER (ver "Métodos evaluados" abajo):
- Después de dos puntos, un nombre en Título Caso de hasta 4 palabras — ej. `Deportes y
  Politica: Patricia Muñiz, Luis Rodolfo Najera`.
- `con [Nombre Apellido]` en Título Caso — ej. `Revista Penthouse Television con Karimm Kury`.
- Texto en MAYÚSCULAS dentro de paréntesis — ej. `MC LUKA Presenta: El Mechero Del Abuelo
  (NEDMAN GUERRERO)`.
Estos tres, a diferencia de los de alta señal, también pueden matchear nombres de programa o
frases genéricas, así que entran como candidato de confianza más baja, nunca como "sin
invitados" automático por su sola ausencia.

**Métodos evaluados y descartados para esta etapa:**
- **spaCy NER (`es_core_news_md`)**, probado contra los 150 videos reales de la muestra: falla
  justo en el tipo de nombre que más importa aquí — apodos/nombres artísticos en mayúsculas
  (`MC INDIGENTE`, `LESLY ZOMBIE`, `DANTE`, `BENCK`, `ACHEPE` los etiquetó como MISC/LOC o no
  los detectó), porque el modelo está entrenado con texto de noticias formales, no con el
  estilo informal de estas descripciones. Además, en descripciones biográficas largas generó
  mucho ruido (19 entidades "persona" distintas en una sola descripción, mezclando al invitado
  real con otros artistas solo mencionados de paso). Los pocos aciertos que spaCy sí encontró y
  el regex original no (`Karimm Kury`, `Patricia Muñiz`, `NEDMAN GUERRERO`) quedaron cubiertos
  por los 3 patrones nuevos de arriba, sin necesidad de sumar la librería ni el modelo.
- **NER "zero-shot" tipo GLiNER** (etiquetas custom como "nombre artístico de invitado" en vez
  de la categoría fija PER/ORG): en teoría más flexible que spaCy, pero sigue siendo un modelo
  general no afinado con el estilo de este canal — mismo riesgo de fallar con apodos y jerga.
  No se probó (dependencia nueva sin evidencia de que resuelva el problema real de spaCy);
  se dejaría solo para reconsiderar si en la práctica el regex + LLM se quedan cortos.
- **Embeddings (`nomic-embed-text`, vía Ollama local) para detectar casi duplicados**: probado
  contra los 150 videos. Los 2 duplicados reales confirmados sí dan similitud altísima
  (0.9989 y 1.0000), pero también encontró un **falso positivo real**: el programa recurrente
  "Revista Penthouse Television con Karimm Kury" tiene 8 episodios en la muestra, 7 de ellos
  con la descripción idéntica carácter por carácter (`#RevistaPenthouseTelevision |
  #KarimmKury | #XLiveMedios`, sin texto propio del episodio) pero publicados entre febrero y
  diciembre de 2024 — episodios reales y distintos, no reposts. Con similitud de texto (literal
  o semántica, da igual) salen indistinguibles de un duplicado real (similitud 1.0000). Mismo
  patrón en "INZZANIA T.V." (similitud 0.9777, ~2 meses de diferencia) y "V2H TV" (0.8356, ~6
  meses). La señal que sí distingue un caso del otro es **la fecha, no el texto**: los
  duplicados reales están a minutos/una semana de diferencia; los episodios distintos, a
  meses. Por eso la regla de "casi duplicados" de arriba exige `published_at` cercano además
  de la similitud de texto — el embedding no resuelve nada que el texto literal no tuviera ya,
  así que no se suma como dependencia nueva.

## Antes de empezar la Fase 3: recorrido completo de la app (lo hace el usuario)
Con el backend, el frontend y Docker corriendo, y datos reales, recorrer la app en el navegador:
1. Iniciar sesión con el administrador.
2. Crear un registro de catálogo (p. ej. un tipo de contacto y una categoría de invitado); probar el duplicado con otras mayúsculas/acentos.
3. Crear un invitado con contacto (y una categoría nueva al vuelo).
4. Crear un video manual y una participación (desde el video y desde el invitado).
5. Borrar lo creado con su confirmación (participación, contacto, video, invitado) y comprobar que los catálogos siguen.
Cualquier fallo se corrige antes de construir la Fase 3 encima. Opcional: ver los datos en pgAdmin (`http://localhost:5050`).

## Preguntas abiertas para el usuario (decidir antes del paso correspondiente)
(✔ = resuelta)

- ✔ **Clave de YouTube API** (paso 3): puesta en `.env` por el usuario.
- ✔ **Modelo de Ollama** (paso 5): `qwen2.5:3b`, ya instalado en el equipo. `OLLAMA_MODEL` fijado en `.env`/`.env.example`. Se prefirió sobre `llama3.2:3b` (mismo tamaño, sin ventaja clara aquí) y sobre `qwen2.5:7b` (mejor calidad esperada, pero ~2.5x más pesado en CPU sin GPU — se deja como opción de respaldo si `qwen2.5:3b` se queda corto en la validación con ejemplos reales).
- ✔ **Qué propone la IA**: invitados, categorías (del catálogo o "categoría nueva sugerida"), contactos, tipo de video, alcaldía del evento, conductor y programa — ver "Reglas del pipeline" arriba. El programa y el conductor solo se proponen contra catálogo existente, nunca inventados; el programa sigue sin inferirse sin evidencia (FR-005).
- ✔ **Videos manuales de prueba**: si la ingesta trae un `youtube_video_id` que ya existe como manual, se ignora el registro manual y **gana total prioridad el real**: el video pasa a `source='youtube'` y se actualizan sus metadatos (invitados/contactos/participaciones ya capturados a mano se conservan, solo se actualiza el video en sí). Aparte: los videos manuales de prueba creados en el recorrido previo a la Fase 3 no tienen ningún valor real y no deben verse en la app — se recomienda borrarlos desde la app (acción manual del usuario, no de código), no dejarlos "ignorados" con un flag nuevo.
- ✔ **Reglas de "sin invitados"** (paso 4): ver "Reglas del pipeline" arriba — regla conservadora con 4 condiciones simultáneas.
- ✔ **Tamaño de lote** para pruebas: 30 por corrida; ya usado en 5 corridas = 150 videos reales muestreados en dos rondas independientes (90 + 60).
- ✔ **Ingesta programada** (FR-011): semanal + disparador manual, pero **desactivada en esta fase** (se sigue trabajando con lotes manuales mientras el sistema no está terminado); construir el disparador programado se deja para una fase final.
- ✔ **Registro de corridas** (paso 2): sí, se guarda historial de corridas (fecha, videos, errores), no solo el estado por video.
- **Aviso de privacidad (LFPDPPP)**: se deja para después, pendiente de platicarlo con el Ing. Israel (dueño del canal y quien solicitó este sistema); conviene resolverlo antes de la carga masiva (Fase 7). Contexto ya aportado por el usuario: solo el Ing. Israel tendría acceso a estos datos (que de por sí ya posee), y los datos de redes sociales que se extraen son los que el propio invitado ya publicó públicamente en YouTube.

Nuevas decisiones de contenido surgidas al validar con datos reales, ya incorporadas arriba:
cómo combinar la confianza cruda del LLM con señales objetivas (título+descripción, ambigüedad
persona/banda); cómo marcar videos casi duplicados sin fusionarlos solos; "Expandete TV" es un
programa del catálogo, no el nombre prohibido del canal (aclarado también en `CLAUDE.md`).

## Adenda: contactos del invitado (decisiones de 2026-10-07; documentadas, aún sin implementar)
Solo documentación: no hay código, migración ni pruebas de esto todavía. Resumen en
`PROJECT_BRIEF.md` (FR-008 y secciones 8-9) y reglas breves en `CLAUDE.md`.

**Fuentes**
- Automática: links, @handles, correos y teléfonos escritos en título o descripción del video.
  Sin scraping, búsquedas externas ni importación de contactos del teléfono. Nunca se inventan.
- Manual: captura progresiva desde la app (Staging Review y ficha del invitado). Entra con origen
  `manual` y ya validada.

**Extracción**
- Misma pasada que la de invitados: la regex saca los contactos y Claude (API de Anthropic, ver
  `docs/Propuesta_extracción_invitados_Claude.md`) los asocia al invitado en la misma llamada, y
  los devuelve en el JSON por video con tipo, relación, evidencia y marca de dudoso, más una
  lista de contactos sin asignar. Hasta que el piloto y la integración de esa Propuesta se
  hagan, el código sigue con Ollama y `staging_contact_candidates`.
- Lista configurable de cuentas propias (canal, programas y conductores ya validados): sus
  contactos se descartan.
  La lista también cubre enlaces fijos del canal que no son contactos de un invitado (herramientas de
  transmisión, enlaces de afiliado o descuento; p. ej. `streamyard.com`, que aparece en muchas
  descripciones). Se aplica en código sobre lo que devuelve Claude (`app/services/contact_filters.py`,
  lista en `app/config/ignored_contacts.json`) y también se le pasa al modelo (instrucciones v4). Un
  patrocinador del invitado sigue siendo contacto del invitado. Cuando exista la tabla de contactos,
  la lista se editará desde la app.
- Cada contacto guarda evidencia: `video_id` y fragmento de texto.

**Tabla de contactos del invitado (1 invitado → N contactos)**
- Campos: invitado (nullable mientras está "sin asignar"), tipo, valor, valor normalizado (para
  deduplicar), relación, nota, origen (`youtube_description` / `manual`), video de origen,
  evidencia y estado (`candidate` / `validated` / `rejected`).
- Tipo: la tabla `contact_types` que ya existe. Se acepta cualquier tipo. Si la extracción halla
  uno no registrado, lo propone como dudoso con el motivo "tipo no registrado" y el admin lo crea
  desde la app.
- Relación: catálogo pequeño y editable (propio, mánager, patrocinador). Patrocinador y mánager
  son contactos DEL invitado, no entidades ni registros nuevos.
- Restricción única por invitado + tipo + valor normalizado.
- Cambios contra el modelo actual (`contacts`, `staging_contact_candidates`), definidos aquí y por
  implementar: `contacts.guest_id` pasa a admitir NULL (sin asignar) y, al rechazar un invitado,
  sus contactos no se borran en cascada sino que quedan sin asignar; se agregan valor normalizado,
  relación, video de origen y evidencia; `source` pasa a `manual` / `youtube_description` (hoy
  `manual` / `video_description`); la bandera `verified` se reemplaza por `status`
  (`candidate` / `validated` / `rejected`); el patrocinador y el mánager dejan de ser tipos de
  contacto y pasan a ser relación. Los contactos manuales entran validados; los aceptados desde
  la ingesta pasan a `validated` (ya no `verified = false`). Los candidatos de contacto de
  staging se alinean con esta tabla (evidencia, dudoso con motivo, rechazados recordados); el
  detalle de si una sola tabla los reemplaza se decide al diseñar la migración. Sin migración ni
  código todavía.

**Revisión humana**
- Invitado y contacto se aprueban, editan o rechazan por separado.
- Si se rechaza un invitado, sus contactos pasan a "sin asignar" (no se borran) y pueden
  reasignarse.
- Se pueden agregar contactos extra a mano.
- Los contactos pueden marcarse como dudosos con motivo visible; habrá un filtro "con contactos
  dudosos".
- Los rechazados se recuerdan para no volver a proponerse al reprocesar.

**Casos ambiguos**
- Varios invitados y un contacto: se asigna solo con evidencia clara (handle parecido al nombre,
  cercanía en el texto, el mismo contacto ligado en otro video); si no, queda sin asignar y
  dudoso ("varios invitados posibles").
- Un invitado y varios contactos: cada uno se evalúa por separado; los que no coinciden quedan
  dudosos y pueden indicar un "posible invitado no detectado", que se puede crear desde ahí.
- Contactos de conductores: se identifican y NO se guardan. Si un conductor aparece como
  invitado, se trata como invitado.

**Pendiente de decidir fase: protección por contraseña (no se planea aquí)**
Por defecto, búsquedas, fichas y Staging Review muestran invitados sin contactos (solo un
indicador, p. ej. "3 contactos 🔒"). Ver, buscar por contacto, modificar, aprobar o exportar
contactos requeriría reingresar la contraseña del admin, con un permiso temporal (propuesta: 10
minutos, sin confirmar), aplicado en el backend. Los contactos no se escriben en los logs y sí
entran en las exportaciones, con la misma contraseña. Toca la autenticación de la Fase 2 y la
exportación de la Fase 5, así que falta decidir en qué fase se implementa.

## Reglas que siguen aplicando
Pruebas escritas por Claude y ejecutadas por el usuario; no ejecutar instalaciones/pytest/docker/npm desde Claude; commits locales, nunca `git push`; código en inglés, docs y comentarios en español; nada de secretos en Git; nunca mencionar el nombre anterior del canal; no inventar datos: todo dato de IA es candidato.
