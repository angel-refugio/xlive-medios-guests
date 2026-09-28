# Plan — Fase 3: Pipeline de ingesta (ETL con IA) + Staging Review

**Estado: propuesta, pendiente de aprobación** (nada implementado; las reglas de contenido del pipeline ya se acordaron con el usuario y están validadas con datos reales, ver "Reglas del pipeline" abajo). El usuario decidió detenerse al cerrar la Fase 2; cuando pida arrancar la Fase 3, primero se repasan con él las "Preguntas abiertas" de abajo y se ajusta este plan. Alcance según `PROJECT_BRIEF.md`
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
2. **Modelo de staging** (migración `0006`; la `0005` ya la usan los conductores): tablas de candidatos de invitado y de contacto (video, valores propuestos, confianza, estado pendiente/aceptado/rechazado, vínculo al registro final una vez aceptado) y, si se aprueba, registro de corridas de ingesta. Se diseñan aquí, no antes (ver `ARCHITECTURE.md`).
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
- **Modelo de Ollama** (paso 5): ¿cuál (~3B) y está instalado en el equipo? `OLLAMA_MODEL` sigue vacío.
- ✔ **Qué propone la IA**: invitados, categorías (del catálogo o "categoría nueva sugerida"), contactos, tipo de video, alcaldía del evento, conductor y programa — ver "Reglas del pipeline" arriba. El programa y el conductor solo se proponen contra catálogo existente, nunca inventados; el programa sigue sin inferirse sin evidencia (FR-005).
- **Videos manuales de prueba**: si la ingesta trae un `youtube_video_id` que ya existe como manual, ¿se actualiza ese registro (y pasa a `youtube`) o se deja intacto y se avisa? (sigue abierta)
- ✔ **Reglas de "sin invitados"** (paso 4): ver "Reglas del pipeline" arriba — regla conservadora con 4 condiciones simultáneas.
- ✔ **Tamaño de lote** para pruebas: 30 por corrida; ya usado en 5 corridas = 150 videos reales muestreados en dos rondas independientes (90 + 60).
- **Ingesta programada** (FR-011): ¿se incluye en esta fase o solo el disparo manual? La frecuencia sigue abierta (brief, sección 8). (sigue abierta)
- **Registro de corridas** (paso 2): ¿se guarda historial de corridas de ingesta (fecha, videos, errores) o basta con el estado por video? (sigue abierta)
- **Aviso de privacidad (LFPDPPP)**: sigue abierto con el supervisor; conviene resolverlo antes de la carga masiva.

Nuevas decisiones de contenido surgidas al validar con datos reales, ya incorporadas arriba:
cómo combinar la confianza cruda del LLM con señales objetivas (título+descripción, ambigüedad
persona/banda); cómo marcar videos casi duplicados sin fusionarlos solos; "Expandete TV" es un
programa del catálogo, no el nombre prohibido del canal (aclarado también en `CLAUDE.md`).

## Reglas que siguen aplicando
Pruebas escritas por Claude y ejecutadas por el usuario; no ejecutar instalaciones/pytest/docker/npm desde Claude; commits locales, nunca `git push`; código en inglés, docs y comentarios en español; nada de secretos en Git; nunca mencionar el nombre anterior del canal; no inventar datos: todo dato de IA es candidato.
