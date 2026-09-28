# Arquitectura — X Live Medios

Documento vivo (actualizado al cierre de la Fase 3). Fuente de requisitos: `PROJECT_BRIEF.md`.

## Estilo
Monolito modular: un backend FastAPI, una base PostgreSQL y un frontend React.
Sin microservicios ni arquitectura multiagente.

## Estructura de carpetas
```
backend/
  app/
    core/       configuración (variables de entorno, .env) y seguridad (hash y JWT)
    db/         motor, sesión y base declarativa de SQLAlchemy
    models/     modelos ORM (tablas en inglés)
    schemas/    esquemas Pydantic (validación y respuestas)
    api/        routers y dependencias de autenticación (deps.py)
    services/   lógica de negocio, sin dependencia de HTTP; la ingesta de la Fase 3 vive en
                youtube_client.py, ingestion.py (sync a `videos`), regex_rules.py (paso 4),
                ollama_client.py (paso 5), pipeline.py (orquestador, paso 6) y staging.py
                (Staging Review, paso 7)
  alembic/      migraciones
  scripts/      utilidades de línea de comandos (create_admin, sample_videos)
  tests/        pruebas automatizadas
frontend/
  src/
    api/        cliente HTTP (token, errores legibles, manejo de 401)
    auth/       sesión (AuthProvider) y rutas protegidas
    components/ Layout, Pager, Participations (compartidos)
    hooks/      useCatalog (catálogos activos)
    pages/      Login, Home, Catalogs, guests/, videos/, staging/ (Staging Review, Fase 3)
    test/       API simulada y utilidades de pruebas
docs/           documentación
docker-compose.yml   PostgreSQL + pgAdmin
```

## Decisiones
- **Idioma**: docs y comentarios en español; código, tablas y endpoints en inglés.
- **Catálogos configurables** (no enums): `guest_categories`, `video_types`,
  `contact_types`, `boroughs`, `programs`. Se administran desde la app. Los nombres son únicos
  ignorando mayúsculas, acentos y espacios extra (la ñ cuenta como n, decisión vigente).
- **Campos opcionales**: casi todo dato del invitado admite `NULL` y se completa después.
- **Sin temporadas**: la relación "parte de otro video" es una autorreferencia
  opcional en `videos`.
- **Datos de IA**: todo dato extraído es candidato hasta validación humana (Staging Review,
  Fase 3). Ver la sección "Ingesta con IA" abajo.
- **Errores y logs**: cada módulo usa `logging.getLogger(__name__)` y los mensajes
  indican módulo y función donde ocurre el fallo.
- **Secretos**: solo por variables de entorno (`.env`, fuera de Git).

## Autenticación (Fase 2)
- Un usuario "administrador" con todos los permisos. `users.role` es texto, no enum de BD, y
  `require_roles(...)` en `api/deps.py` permite agregar roles sin tocar las rutas.
- Login con contraseña hasheada (argon2); el token es un JWT de corta duración
  (`JWT_EXPIRE_MINUTES`, 60 por defecto) enviado en `Authorization: Bearer`.
- Todas las rutas de datos exigen `require_admin`; solo `/health` y `/auth/login` son públicas.
- El frontend guarda el token en `localStorage` (si el navegador lo bloquea, la app funciona sin recordar la sesión)
  y ante un 401 cierra la sesión y vuelve al login.

## Convenciones de la API
- **PATCH parcial**: solo cambian los campos enviados; enviar `null` borra un dato opcional.
- **Borrados**: exigen `?confirm=true` (invitado, contacto, participación, video). Borrar un invitado
  elimina en cascada sus contactos y participaciones; borrar un video elimina sus participaciones y
  deja sueltas sus "partes". Los catálogos no se borran: se desactivan.
- **Paginación** (invitados, videos, candidatos de staging): `page` y `page_size` (50 por
  defecto, máximo 200); respuesta `{items, total, page, page_size}`.
- **Staging Review** (Fase 3): `/staging/guest-candidates` y `/staging/contact-candidates`,
  filtrables por `?status=pending|accepted|rejected` (`pending` por defecto). `POST .../accept`
  y `POST .../reject` cierran el candidato; un candidato ya revisado da 409 si se vuelve a
  aceptar o rechazar. Los candidatos nunca se borran, solo cambian de estado.
- **Errores**: 401 sin sesión, 403 sin permiso, 404 no existe, 409 duplicado, 422 dato inválido o
  referencia inexistente/desactivada; el `detail` es un mensaje legible en español.
- **Videos**: `source` distingue los cargados a mano (`manual`) de los de la ingesta (`youtube`).

## Ingesta con IA (Fase 3)
Pipeline por video, sin transcripción (solo título y descripción), disparado a demanda (`app.services.pipeline.run_batch`) desde la app o un script — todavía sin ninguno de los dos, la fase 3 dejó el orquestador listo pero no su disparador:
1. **YouTube → BD** (`youtube_client.py` + `ingestion.py`): trae videos del canal y los guarda en `videos` con `source='youtube'`, idempotente por `youtube_video_id`. Si el id ya existía como `manual` (video de prueba), el real gana prioridad total: se actualiza y pasa a `youtube`, conservando invitados/contactos/participaciones ya capturados a mano.
2. **Reglas de regex** (`regex_rules.py`): contactos explícitos (URLs, `ETIQUETA:` + usuario, correos), 3 patrones de nombre por formato (confianza baja/media) y la regla conservadora de "sin invitados" (FR-014, 4 condiciones simultáneas — si falta cualquiera, va a la cola normal).
3. **LLM local** (`ollama_client.py`, Ollama con `qwen2.5:3b`): analiza título+descripción contra el contrato de `app/schemas/ingestion.py` (`VideoAnalysis`), con los catálogos existentes en el prompt para que solo señale coincidencias reales (nunca inventa conductor, programa, tipo de video ni alcaldía). Reintenta si la salida no es JSON válido o no cumple el contrato.
4. **Orquestador** (`pipeline.py`): junta reglas + LLM en filas de `staging_guest_candidates`/`staging_contact_candidates`, marca `guest_status='no_guests'` cuando la regla de regex lo detecta (reclasificable), calcula `possible_duplicate_of_video_id` (título+descripción normalizados iguales y `published_at` a ±14 días) y es idempotente vía `Video.last_ingested_at`. Registra el historial en `IngestionRun`/`IngestionRunError`, sin detener el lote si un video falla.
5. **Staging Review** (`staging.py` + `/staging/*` + `pages/staging/`): la app humana acepta (crea o vincula invitado/contacto), edita antes de aceptar, o rechaza. Sugiere invitados existentes por nombre parecido (FR-001, reutilizando `normalize_name`). La cola ordena por confianza **ajustada**, no la cruda.

Detalle completo, evidencia real y decisiones de contenido: `docs/PHASE3_PLAN.md`.

## Preguntas abiertas que afectan al diseño (no asumidas)
- Lista de programas del canal.
- Qué datos del patrocinador se guardan (por ahora: contacto tipo "patrocinador" con valor y nota).
- Historial de cambios (quién modificó qué): fuera de alcance hasta aprobarse.
- Plataforma de despliegue y disparador/frecuencia de la ingesta automática (FR-011): el
  orquestador ya existe (`pipeline.run_batch`); construir quién lo llama y cuándo se deja para
  una fase final.
- Fusionar categorías (FR-004): sin decidir ni implementar.
- Aviso de privacidad (LFPDPPP): pendiente con el Ing. Israel antes de la carga histórica
  masiva de la Fase 7.
