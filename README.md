# X Live Medios

Base de datos de invitados/talento del canal de YouTube `@xlivemedios`, con una app web
para consultarla y administrarla. Requisitos completos en `PROJECT_BRIEF.md`;
reglas de trabajo en `CLAUDE.md`.

## Estado
- Fase 1 (Diseño y fundación): completada.
- Fase 2 (Autenticación y CRUD base): completada. La app permite iniciar sesión como
  administrador y administrar catálogos, invitados (con categorías y contactos), videos
  cargados a mano y participaciones (invitado ↔ video), todo desde la interfaz.
- Fase 3 (pipeline de ingesta con IA + Staging Review): activa; plan propuesto en `docs/PHASE3_PLAN.md`, pendiente de aprobación.

## Estructura
```
backend/    FastAPI + SQLAlchemy + Alembic (ver docs/ARCHITECTURE.md)
frontend/   React (Vite) + Vitest
docs/       ARCHITECTURE.md, DATA_MODEL.md, PHASE2_PLAN.md, PHASE3_PLAN.md
docker-compose.yml   PostgreSQL + pgAdmin
```

## Configuración
1. Copiar `.env.example` a `.env` y completar los valores. Nunca subir `.env` a Git.
   Para la app: `JWT_SECRET` (cadena aleatoria de al menos 32 caracteres; se genera con
   `python -c "import secrets; print(secrets.token_urlsafe(48))"`), `ADMIN_USERNAME` y
   `ADMIN_PASSWORD`. El backend lee el `.env` de la raíz automáticamente.
2. Base de datos (raíz del proyecto): `docker compose --env-file .env up -d`
3. Backend (desde `backend/`):
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python -m alembic upgrade head
   python -m scripts.create_admin      # crea el administrador con ADMIN_USERNAME / ADMIN_PASSWORD
   python -m uvicorn app.main:app --reload
   ```
   La documentación interactiva de la API queda en `http://localhost:8000/docs`.
4. Frontend (desde `frontend/`):
   ```powershell
   npm install
   npm run dev                         # http://localhost:5173 (el proxy /api apunta al backend)
   ```

## Pruebas
- Backend (`backend/`): `python -m pytest` (usa SQLite en memoria; no necesita Docker).
- Frontend (`frontend/`): `npm test` (Vitest + Testing Library; simula la API, no necesita el backend).

## Uso rápido de la app
1. Iniciar sesión con el usuario de `ADMIN_USERNAME`.
2. **Catálogos**: crear al menos los tipos de contacto (celular, correo, Instagram, patrocinador…),
   y los tipos de video, programas y categorías que se necesiten. Las alcaldías de la CDMX ya vienen cargadas.
3. **Invitados**: alta con solo el nombre; el resto se completa después. Las categorías nuevas se pueden
   crear al vuelo. Los contactos y las participaciones se agregan desde el detalle del invitado.
4. **Videos**: por ahora se cargan a mano (quedan con origen «Manual»). Al llegar la ingesta real (Fase 3)
   los de prueba se localizan con el filtro «Origen → Manuales» y se borran desde su detalle.

Reglas de la API que la interfaz respeta: los borrados exigen `?confirm=true` (la app pide confirmación
antes), los listados grandes se paginan (50 por defecto, máximo 200) y los catálogos se desactivan en
lugar de borrarse.

## Limitaciones conocidas (se resuelven en fases posteriores)
- Sin búsqueda por texto ni filtros avanzados (Fase 4). Las listas para elegir invitado o video en
  participaciones muestran los primeros 200 registros.
- Fusionar categorías (FR-004) quedó sin hacer.
- Sin exportación (Fase 5) ni seguimiento de re-contacto (Fase 6).

## Documentación
- `docs/ARCHITECTURE.md`: arquitectura y decisiones.
- `docs/DATA_MODEL.md`: modelo de datos y diagrama ER.
- `docs/PHASE2_PLAN.md`: plan y decisiones de la Fase 2.
- `docs/PHASE3_PLAN.md`: plan propuesto de la Fase 3.
