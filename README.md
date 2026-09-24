# X Live Medios

Base de datos de invitados/talento del canal de YouTube `@xlivemedios`, con una app web
para consultarla y administrarla. Requisitos completos en `PROJECT_BRIEF.md`;
reglas de trabajo en `CLAUDE.md`.

## Estado
Fase 1 (Diseño y fundación) en curso.

## Estructura
```
backend/    FastAPI + SQLAlchemy + Alembic (ver docs/ARCHITECTURE.md)
frontend/   React (Vite)
docs/       ARCHITECTURE.md, DATA_MODEL.md
docker-compose.yml   PostgreSQL + pgAdmin (paso 4)
```

## Configuración
1. Copiar `.env.example` a `.env` y completar los valores. Nunca subir `.env` a Git.
2. Backend (desde `backend/`):
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python -m pytest
   ```

## Documentación
- `docs/ARCHITECTURE.md`: arquitectura y decisiones.
- `docs/DATA_MODEL.md`: modelo de datos y diagrama ER.
