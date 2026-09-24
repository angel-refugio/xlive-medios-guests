# Plan — Fase 3: Pipeline de ingesta (ETL con IA) + Staging Review

**Estado: propuesta, pendiente de aprobación** (nada implementado). El usuario decidió detenerse al cerrar la Fase 2; cuando pida arrancar la Fase 3, primero se repasan con él las "Preguntas abiertas" de abajo y se ajusta este plan. Alcance según `PROJECT_BRIEF.md`
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
2. **Modelo de staging** (migración `0005`): tablas de candidatos de invitado y de contacto (video, valores propuestos, confianza, estado pendiente/aceptado/rechazado, vínculo al registro final una vez aceptado) y, si se aprueba, registro de corridas de ingesta. Se diseñan aquí, no antes (ver `ARCHITECTURE.md`).
3. **Servicio YouTube**: listar los videos del canal con paginación, manejo de errores y cuota; guardarlos en `videos` sin duplicar (`youtube_video_id`). Las pruebas usan respuestas simuladas, sin red.
4. **Reglas previas al LLM**: extraer enlaces y correos con expresiones regulares; detectar videos "sin invitados" (FR-014) con reglas simples.
5. **Servicio Ollama**: prompt con título y descripción, salida estructurada validada con Pydantic, tiempo límite, reintentos y manejo de JSON inválido; un video a la vez. Pruebas con el cliente simulado.
6. **Orquestador idempotente**: procesa un video (reglas → LLM → candidatos), omite los ya procesados, registra errores por video sin detener el lote; se dispara a demanda desde la app o por script.
7. **Staging Review (backend y frontend)**: cola principal de candidatos pendientes; vista aparte para videos "sin invitados" (reclasificables); aceptar (crea o vincula invitado, participación y contactos con `source = video_description` y `verified = false`), editar antes de aceptar, o rechazar. Sugerir invitados existentes por nombre parecido para no duplicar (FR-001), reutilizando `normalize_name`.
8. **Cierre**: documentación, revisión de pruebas y commit propuesto.

## Preguntas abiertas para el usuario (decidir antes del paso correspondiente)
- **Clave de YouTube API** (paso 3): ¿quién la crea desde la cuenta de la empresa? Sin ella no se puede hacer una corrida real; el desarrollo y las pruebas usan respuestas simuladas.
- **Modelo de Ollama** (paso 5): ¿cuál (~3B) y está instalado en el equipo? `OLLAMA_MODEL` sigue vacío.
- **Qué propone la IA**: según el brief, invitados, categorías (del catálogo o "categoría nueva sugerida") y contactos. ¿También tipo de video y alcaldía del evento? El programa no se infiere sin evidencia (FR-005).
- **Videos manuales de prueba**: si la ingesta trae un `youtube_video_id` que ya existe como manual, ¿se actualiza ese registro (y pasa a `youtube`) o se deja intacto y se avisa?
- **Reglas de "sin invitados"** (paso 4): ¿qué señales cuentan (p. ej. palabras del título o tipo de video)? Se propone empezar conservador y ajustar con ejemplos reales.
- **Tamaño de lote** para pruebas (p. ej. los N videos más recientes) antes de la carga histórica de la Fase 7.
- **Ingesta programada** (FR-011): ¿se incluye en esta fase o solo el disparo manual? La frecuencia sigue abierta (brief, sección 8).
- **Registro de corridas** (paso 2): ¿se guarda historial de corridas de ingesta (fecha, videos, errores) o basta con el estado por video?
- **Aviso de privacidad (LFPDPPP)**: sigue abierto con el supervisor; conviene resolverlo antes de la carga masiva.

## Reglas que siguen aplicando
Pruebas escritas por Claude y ejecutadas por el usuario; no ejecutar instalaciones/pytest/docker/npm desde Claude; commits locales, nunca `git push`; código en inglés, docs y comentarios en español; nada de secretos en Git; nunca mencionar el nombre anterior del canal; no inventar datos: todo dato de IA es candidato.
