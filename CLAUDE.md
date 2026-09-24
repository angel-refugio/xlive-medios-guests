# X Live Medios — CLAUDE.md

Detalle completo y preguntas abiertas: `PROJECT_BRIEF.md`.

## Objetivo
Hoy no existe ningún sistema, base de datos ni registro previo de invitados; es la primera vez que se recopila esta información (canal YouTube `@xlivemedios`, contenido desde 2022).
Meta: base de datos de talento/invitados que permita buscar rápido, por ejemplo "cantantes de cierta edad de cierta alcaldía" o "quiénes son actores", porque se trabaja con alcaldías, patrocinadores y eventos y buscar uno por uno es inviable.
Resultado esperado: al buscar "cantantes", cada invitado con sus participaciones (entrevistas/eventos) y datos de contacto (celular, páginas oficiales, patrocinador). Contactos: páginas oficiales extraídas como candidatos + captura manual progresiva; no se importan contactos personales del teléfono ni se inventan.
Organización: categoría, tipo de talento, edad, alcaldía, programa y temporada.

## Alcance
- **Dentro**: sistema de invitados, videos, programas, temporadas, categorías y participaciones + app web de consulta y administración. YouTube solo como fuente de metadatos.
- **Fuera** (sin aprobación explícita): streaming/RTMP/HLS, transcodificación, CDN, hospedaje de video, reemplazo de YouTube.

## Reglas de trabajo
- No inventar requisitos ni datos. No ampliar alcance. Lo ambiguo es pregunta abierta, no se asume.
- Cambios incrementales y verificables. Sin arquitectura multiagente.
- Los campos son opcionales: un video puede no tener invitados (la IA lo marca "sin invitados", reclasificable por un humano) y un invitado puede tener contactos parciales, editables después.
- Categoría del invitado (talento) = catálogo configurable N↔N, opcional, creable desde la app; alcaldías = catálogo de CDMX editable; tipo de video (entrevista/evento/podcast…) es catálogo configurable. No hay temporadas; programa y "parte de otro video" son opcionales. Edad aproximada (búsqueda por rangos); alcaldía del invitado y del evento.
- Todos los videos van bajo el nombre "X Live Medios": nunca mencionar el nombre anterior del canal en el sistema, UI ni datos.
- Todo (consultar, revisar, editar) se hace desde la app, sin SQL, según permisos.
- Todo dato extraído por IA es candidato hasta validación humana.
- Trabajar siempre en la fase activa del roadmap; no adelantar fases sin acuerdo.
- **Pruebas**: todo código nuevo lleva pruebas automatizadas (ingesta, BD, lógica de negocio, endpoints) y manejo de errores con mensajes/logs claros que indiquen en qué módulo y función ocurrió el fallo. Las escribo yo; las ejecuta el usuario.
- **Git**: commits locales (Conventional Commits). Yo propongo el commit tras un cambio significativo; el usuario decide. **Nunca `git push`.** Secretos (`.env`, keys) fuera de Git.
- **Terminal**: no ejecutar instalaciones ni pruebas (`pip install`, `npm install`, `pytest`, `docker`…). Indicar el comando al usuario y pedir la salida, resumida si es larga.
- **Idioma**: docs y comentarios en español; código, tablas y endpoints en inglés.
- **Graphify**: si existe `graphify-out/`, usarlo como mapa de contexto antes de explorar archivo por archivo; regenerar con `/graphify .` tras cambios estructurales grandes.

## Stack
- Backend: Python + FastAPI
- BD: PostgreSQL en contenedor Docker; pgAdmin como servicio en `docker-compose.yml` para demo al cliente (DBeaver solo si el usuario lo pide)
- Frontend: React
- Extracción de candidatos: LLM local vía Ollama (modelos ~3B; equipo 16 GB RAM sin GPU). Pipeline ligero: solo título y descripción (sin transcripciones), reglas/regex antes del LLM, un video a la vez
- Usuario único de la app: "administrador" con todos los permisos (por ahora)
- Fuente de datos: YouTube Data API v3

## Roadmap (fase activa: 1)
1. Diseño y fundación (modelo de datos, arquitectura, entorno)
2. Autenticación y CRUD base
3. Pipeline de ingesta (ETL con IA) + Staging Review
4. Buscador y filtros
5. Exportación a Excel/CSV
6. Seguimiento de re-contacto
7. Carga histórica masiva
8. Pulido, pruebas y entrega
