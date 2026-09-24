# Arquitectura — X Live Medios

Documento vivo de la Fase 1. Fuente de requisitos: `PROJECT_BRIEF.md`.

## Estilo
Monolito modular: un backend FastAPI, una base PostgreSQL y un frontend React.
Sin microservicios ni arquitectura multiagente.

## Estructura de carpetas
```
backend/
  app/
    core/       configuración (variables de entorno) y logging
    db/         motor, sesión y base declarativa de SQLAlchemy
    models/     modelos ORM (tablas en inglés)
    schemas/    esquemas Pydantic (Fase 2 en adelante)
    api/        routers (health en Fase 1)
    services/   lógica de negocio (ingesta en Fase 3)
  alembic/      migraciones
  tests/        pruebas automatizadas
frontend/       React (Vite)
docs/           documentación
docker-compose.yml   PostgreSQL + pgAdmin
```

## Decisiones
- **Idioma**: docs y comentarios en español; código, tablas y endpoints en inglés.
- **Catálogos configurables** (no enums): `guest_categories`, `video_types`,
  `contact_types`, `boroughs`, `programs`. Se administran desde la app.
- **Campos opcionales**: casi todo dato del invitado admite `NULL` y se completa después.
- **Sin temporadas**: la relación "parte de otro video" es una autorreferencia
  opcional en `videos`.
- **Datos de IA**: todo dato extraído es candidato hasta validación humana. Las tablas
  de staging se diseñan y crean en la Fase 3, no antes.
- **Errores y logs**: cada módulo usa `logging.getLogger(__name__)` y los mensajes
  indican módulo y función donde ocurre el fallo.
- **Secretos**: solo por variables de entorno (`.env`, fuera de Git).

## Preguntas abiertas que afectan al diseño (no asumidas)
- Lista de programas del canal.
- Qué datos del patrocinador se guardan (por ahora: contacto tipo "patrocinador" con valor y nota).
- Historial de cambios (quién modificó qué): fuera de alcance hasta aprobarse.
- Plataforma de despliegue y frecuencia de la ingesta automática.
