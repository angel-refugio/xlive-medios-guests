# Plan — Fase 2: Autenticación y CRUD base

**Estado: completada** (pasos 1 a 7 hechos; pendiente solo el commit de cierre). Detalle de lo entregado en `README.md`, `ARCHITECTURE.md` y `DATA_MODEL.md`.

Alcance según `PROJECT_BRIEF.md` (sección 7) y FR-015/FR-016. Estado de partida: Fase 1
cerrada (commit `5ddc6af`): modelo de datos, migraciones, `/health`, Docker y frontend mínimo.

## Alcance
- Login del usuario único "administrador" (todos los permisos); el diseño debe permitir agregar roles después.
- CRUD manual de invitados, contactos, programas y participaciones, para cargar/editar datos aunque el pipeline de IA aún no exista.
- Administración de catálogos desde la app (categorías de invitado, tipos de video, tipos de contacto, alcaldías, programas): agregar, renombrar, desactivar.
- Todo desde la app, sin SQL (FR-015).

Fuera de esta fase: búsqueda/filtros avanzados (Fase 4), exportación (5), re-contacto (6), ingesta y Staging Review (3).

## Pasos (todos hechos, cada uno con pruebas)
1. ✔ **Usuarios y autenticación (backend)**
   - Tabla `users` (username único, `password_hash`, `role` con valor "administrador", `is_active`) + migración `0003`.
   - Contraseña con hash (argon2 o bcrypt); el usuario inicial se crea con un script que lee `ADMIN_USERNAME`/`ADMIN_PASSWORD` del `.env` (nunca en Git; agregar a `.env.example` sin valores).
   - `POST /auth/login`, `GET /auth/me`; dependencia `require_admin` que protege todas las rutas de CRUD (deja `/health` público). Estructura de roles lista para crecer.
   - Pruebas: login correcto/incorrecto, ruta protegida sin token, token inválido/expirado.
2. ✔ **Catálogos (backend)**: CRUD genérico reutilizable para los 5 catálogos (listar, crear, renombrar, activar/desactivar); nombre único con mensaje claro en duplicado.
3. ✔ **Invitados (backend)**: CRUD con categorías N↔N (crear categoría al vuelo), alcaldía, edad aproximada; todos los campos opcionales salvo el nombre.
4. ✔ **Contactos (backend)**: CRUD anidado bajo el invitado; tipo del catálogo, nota, fuente, verificado.
5. ✔ **Programas y participaciones (backend)**: CRUD de programas; participaciones que vinculan invitado y video (unicidad por par).
6. ✔ **Frontend**: pantalla de login, layout con navegación, listados y formularios para catálogos, invitados (con contactos y categorías) y participaciones; manejo de errores visible al usuario.
7. ✔ **Cierre**: actualizar README/docs, revisar pruebas y proponer commit.

## Preguntas abiertas para el usuario (decidir antes o durante el paso correspondiente)
- **Sesión** — *decidido*: JWT de corta duración en el encabezado `Authorization`.
- **Videos manuales** — *decidido*: se permite crear/editar videos a mano en esta fase (mínimo: `youtube_video_id`, título) para poder cargar participaciones antes de la Fase 3. Cada video tiene `source` (`manual` | `youtube`; la ingesta usará `youtube`), así los de prueba se listan con `GET /videos?source=manual` y se borran con `DELETE /videos/{id}?confirm=true` al llegar los reales. Borrar un video elimina sus participaciones (no los invitados).
- **Borrado vs. desactivación** de invitados — *decidido*: se borra en cascada (contactos y participaciones) y el API exige `?confirm=true`; lo mismo para contactos, participaciones y videos.
- **Fusionar categorías** (FR-004): *sin decidir ni implementar*; se propone tratarla en una fase posterior (p. ej. Fase 4 o 8).
- **Paginación** de listados — *decidido*: 50 por defecto, máximo 200 (invitados y videos).

## Reglas que siguen aplicando
Pruebas escritas por Claude y ejecutadas por el usuario; no ejecutar instalaciones/pytest/docker desde Claude; commits locales propuestos por Claude, nunca `git push`; código en inglés, docs y comentarios en español; nada de secretos en Git.

## Pendientes heredados (Fase 8)
- Aviso de Starlette: `httpx` en `TestClient` obsoleto (sugiere `httpx2`); verificar antes de cambiar.
- Vulnerabilidades de npm (7 tras instalar Vitest y Testing Library: 5 moderadas, 1 alta, 1 crítica), a revisar con `npm audit` para ver si son solo de herramientas de desarrollo; no usar `npm audit fix --force`.
- Fusión de categorías (FR-004), ver arriba.
- Buscar por texto al elegir invitado/video en participaciones (hoy solo los primeros 200): se resuelve con la Fase 4.
- Confirmaciones de borrado con `window.confirm`; se puede cambiar por un diálogo propio en el pulido.

## Comandos de entorno (Windows/PowerShell)
- Raíz: `docker compose --env-file .env up -d`
- `backend/` (venv activo; el backend lee el `.env` de la raíz): `python -m alembic upgrade head`, `python -m uvicorn app.main:app --reload`, `python -m pytest`
- `frontend/`: `npm run dev`, `npm test`
- Administrador inicial: `python -m scripts.create_admin` (desde `backend/`; lee `ADMIN_USERNAME`/`ADMIN_PASSWORD` del `.env`)
