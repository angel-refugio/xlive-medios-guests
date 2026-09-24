# Arquitectura — X Live Medios

Documento vivo (actualizado al cierre de la Fase 2). Fuente de requisitos: `PROJECT_BRIEF.md`.

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
    services/   lógica de negocio, sin dependencia de HTTP (ingesta en Fase 3)
  alembic/      migraciones
  scripts/      utilidades de línea de comandos (create_admin)
  tests/        pruebas automatizadas
frontend/
  src/
    api/        cliente HTTP (token, errores legibles, manejo de 401)
    auth/       sesión (AuthProvider) y rutas protegidas
    components/ Layout, Pager, Participations (compartidos)
    hooks/      useCatalog (catálogos activos)
    pages/      Login, Home, Catalogs, guests/, videos/
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
- **Datos de IA**: todo dato extraído es candidato hasta validación humana. Las tablas
  de staging se diseñan y crean en la Fase 3, no antes.
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
- **Paginación** (invitados, videos): `page` y `page_size` (50 por defecto, máximo 200); respuesta
  `{items, total, page, page_size}`.
- **Errores**: 401 sin sesión, 403 sin permiso, 404 no existe, 409 duplicado, 422 dato inválido o
  referencia inexistente/desactivada; el `detail` es un mensaje legible en español.
- **Videos**: `source` distingue los cargados a mano (`manual`) de los de la ingesta (`youtube`).

## Preguntas abiertas que afectan al diseño (no asumidas)
- Lista de programas del canal.
- Qué datos del patrocinador se guardan (por ahora: contacto tipo "patrocinador" con valor y nota).
- Historial de cambios (quién modificó qué): fuera de alcance hasta aprobarse.
- Plataforma de despliegue y frecuencia de la ingesta automática.
- Fusionar categorías (FR-004): sin decidir ni implementar.
