# X Live Medios - Planteamiento del proyecto

Este documento es el punto de partida limpio del proyecto. Contiene únicamente
el objetivo, el alcance y los requisitos ya confirmados o acordados con el
usuario/supervisor. El stack tecnológico ya está definido (ver sección 6);
los detalles de arquitectura se diseñan en la Fase 1.

## 1. Contexto

- **Proyecto**: X Live Medios
- **Organización**: SystemKW S.A. de C.V.
- **Supervisor del proyecto**: Ing. Israel Hernández García, Director Operativo
- **Marco**: residencia profesional

## 2. Objetivo del proyecto (confirmado por el supervisor)

X Live Medios tiene un canal/página de YouTube con contenido desde
aproximadamente 2022, organizado en múltiples programas.

**Objetivo principal**: crear una base de datos con todos los invitados que
han aparecido en el contenido de X Live Medios, organizados por:

- categoría del invitado (su tipo de talento, catálogo configurable)
- tipo de video (entrevista, evento, podcast, etc.)
- programa (cuando aplique; muchos videos son libres, sin programa)

El sistema debe permitir identificar y registrar, como mínimo:

- quién fue el invitado
- categoría (tipo de talento)
- tipo de video
- programa (si aplica)

El propósito es organizar información que ya existe dispersa en el contenido
de X Live Medios (no generar contenido nuevo).

**Necesidad de negocio (confirmada por el supervisor)**: hoy no existe ningún
sistema ni base de datos; es la primera vez que se recopila esta información.
X Live Medios trabaja con alcaldías, patrocinadores y eventos, y necesita
poder pedir al sistema, por ejemplo, "¿quiénes tenemos de cantantes de cierta
edad de cierta alcaldía?" o "¿quiénes son actores?" y obtener el resultado
directamente, en lugar de buscar invitado por invitado entre los años de
contenido acumulado. Por eso, además de lo anterior, el invitado se debe
poder filtrar por **edad**, **alcaldía** y **tipo de talento** (cantante,
actor, etc.).

Los invitados provienen de entrevistas (ej. entrevista con un famoso) y de
eventos (ej. evento X con un cantante). Al buscar, por ejemplo, "cantantes",
el resultado debe mostrar cada invitado con sus participaciones (entrevistas
y eventos en que ha estado) y sus datos de contacto (celular, páginas
oficiales, contacto del patrocinador, etc.).

## 3. Alcance y límites

### Dentro de alcance

- Sistema de información de invitados, videos, programas, tipos de video,
  categorías (talento), contactos y participaciones.
- Aplicación web para consulta y administración de esa información.
- YouTube como **fuente de datos** (metadatos vía API), no como plataforma a
  reproducir.
- Fuente principal: YouTube (canal oficial `https://www.youtube.com/@xlivemedios`).
  Facebook, Instagram y TikTok son fuentes complementarias posibles a futuro,
  no prioritarias.

### Explícitamente fuera de alcance (no agregar sin aprobación explícita)

- RTMP
- HLS
- infraestructura de streaming en vivo
- transcodificación de video
- infraestructura CDN
- hospedaje de video
- pipelines de procesamiento multimedia
- almacenamiento de objetos para alojar videos originales
- construir un reemplazo de YouTube

### Reglas de trabajo

- No inventar requisitos.
- No expandir el alcance sin aprobación explícita del usuario.
- Si un requisito falta o es ambiguo, se identifica como pregunta abierta en
  lugar de asumirse.
- Preferir cambios incrementales y verificables.
- Mantener secretos y credenciales fuera de Git; nunca exponer API keys,
  contraseñas, tokens ni credenciales privadas.
- Nunca hacer push a un repositorio remoto sin aprobación explícita del
  usuario.
- **No usar arquitectura multiagente** para el desarrollo de este proyecto.

## 4. Requisitos funcionales

### FR-001 Registro de invitados
El sistema debe permitir registrar invitados. Cada invitado debe tener un
identificador interno único. Un invitado no debe duplicarse por aparecer
varias veces.

### FR-002 Registro de videos
El sistema debe mantener información de los videos relevantes de X Live
Medios. Se debe usar el ID de video de YouTube para evitar ingesta
duplicada.

### FR-003 Participación de invitados
Relación muchos-a-muchos entre invitados y videos: un invitado puede
aparecer en múltiples videos; un video puede tener cero, uno o más invitados. Cada
participación se preserva como registro independiente.

### FR-004 Categoría del invitado (tipo de talento) y tipo de video
- **Categoría del invitado = tipo de talento**: catálogo configurable
  (`guest_categories`), opcional y con relación N↔N con el invitado: un
  invitado puede tener varias (ej. cantante y escultor) y las personas
  comunes pueden no tener ninguna. Se administra desde la app (agregar,
  renombrar, fusionar, desactivar). Al capturar un invitado se busca en el
  catálogo o se crea una categoría nueva sin salir de la pantalla, para no
  bloquear la captura. No hay lista inicial inventada: el catálogo se llena
  con las categorías que aparezcan durante la revisión. La IA solo propone
  categorías del catálogo o una "categoría nueva sugerida" para revisión
  humana.
- **Tipo de video** (entrevista, evento, podcast, etc.): el contenido es muy
  amplio y no hay lista definida, por lo que es un catálogo configurable
  desde la app, al que se pueden agregar tipos nuevos.

### FR-005 Programas
Cuando aplique, el video puede asociarse a un programa. Muchos videos son
"libres": no pertenecen a ningún programa ni tienen relación con otros
videos. Un programa no debe inferirse sin evidencia suficiente.

### FR-006 Partes de un video (sustituye a "temporadas")
No existen temporadas como tal. Algunos videos son continuación de otro
(ej. "video X parte 2"); esa relación es opcional. La gran mayoría de videos
son independientes y no deben requerir programa, parte ni relación alguna.

### FR-007 Ingesta de metadatos de YouTube
El proyecto debe poder obtener metadatos de video usando YouTube Data API
v3. El proceso de ingesta debe soportar paginación, prevención de
duplicados, manejo de errores de API, uso consciente de cuota y ejecución
repetible.

### FR-008 Información adicional del invitado
El sistema debe soportar el almacenamiento de información útil adicional
del invitado cuando exista información confiable: nombre, datos de
contacto, organización, rol, notas, edad aproximada, alcaldía y tipo de
talento. No se debe fabricar ninguna información.

- **Edad**: no se puede obtener de YouTube, por lo que se guarda una edad
  aproximada y la búsqueda se hace por rangos (ej. 20 a 30 años).
- **Alcaldía**: catálogo (`boroughs`) con las alcaldías de la CDMX,
  editable a futuro. Se guarda la alcaldía del invitado (donde vive) y, por
  separado, la del evento o entrevista (a nivel de video). Ambas son
  referencias opcionales al catálogo y filtrables.

### FR-009 Validación manual
Toda información extraída o inferida automáticamente debe ser revisable por
un humano antes de considerarse definitiva.

### FR-010 Búsqueda y consulta
El sistema debe ofrecer una aplicación web que permita consultar invitados y
sus apariciones, filtrando al menos por invitado, tipo de talento, rango de
edad, alcaldía (del invitado y del evento), tipo de video, programa y video.

### FR-011 Modos de ingesta
El sistema debe soportar ingesta manual bajo demanda e ingesta automática
programada, reutilizando la misma lógica de ingesta (solo cambia el
disparador).

### FR-012 Contactos del invitado
Un invitado puede tener varios contactos (Guest 1→N Contact). Los tipos de
contacto son un catálogo (`contact_types`: celular, correo, página web,
Instagram, Facebook, TikTok, representante/manager, patrocinador, etc.) al
que se pueden agregar tipos nuevos sin modificar la estructura de la base de
datos. Cada contacto (`contacts`) relaciona un invitado con un tipo y
guarda su valor, una nota opcional (ej. nombre de la empresa patrocinadora),
la fuente (manual / descripción de video) y una bandera "verificado". Así un
invitado puede tener solo Instagram y correo, y otro celular, página web y
representante, sin campos vacíos innecesarios. El contacto de patrocinador
pertenece al invitado (su patrocinador personal). Ningún dato de contacto se
inventa.

Todos los contactos son opcionales: un invitado puede tener solo un celular,
varios medios (celular, correo, patrocinador…) o ninguno, y se pueden
agregar o editar después. Lo mismo aplica a los demás campos opcionales del
invitado (edad, alcaldía, tipo de talento, etc.): pueden quedar vacíos y
completarse luego.

### FR-013 Estrategia de obtención de contactos
YouTube Data API no entrega celulares ni correos de terceros; no se hace
scraping. Los contactos se obtienen así:
- **Automático (candidatos)**: enlaces a páginas/redes oficiales y correos
  que aparezcan en título o descripción del video, extraídos
  con Ollama y validados en Staging Review (FR-009).
- **Llenado progresivo bajo demanda**: teléfono, correo y contacto de
  patrocinador se capturan manualmente solo cuando se necesitan; la búsqueda
  indica qué invitados están "sin contacto".
- **No** se importan contactos personales del teléfono/Google Contacts (por
  privacidad).

### FR-014 Videos sin invitados
Algunos videos (ej. eventos) no tienen invitados. El LLM puede clasificarlos
como "sin invitados"; se guardan con ese estado, sin crear participaciones
vacías. En Staging Review aparecen en una vista/filtro aparte, fuera de la
cola principal, para no perder tiempo en ellos. Es una propuesta de la IA:
un humano puede reclasificar el video si sí hay invitado (FR-009).

### FR-015 Administración desde la aplicación
Desde la aplicación web, los usuarios con permiso pueden consultar, hacer
las revisiones manuales que la IA no pudo completar, y crear, editar o
eliminar registros (ej. cambiar el celular de un invitado) sin usar
comandos SQL.

### FR-016 Autenticación
La aplicación tiene un único usuario, "administrador", con todos los
permisos. Lo usa el supervisor (y el desarrollador para pruebas y
demostraciones). No hay registro de otros usuarios por ahora.

### FR-017 Exportación
El sistema debe permitir exportar a Excel/CSV los resultados filtrados
(invitado, participaciones y contactos).

### FR-018 Seguimiento de re-contacto
El sistema calcula automáticamente la última participación/contacto de cada
invitado y muestra un indicador visual de "tiempo sin contactar".

## 5. Requisitos de datos

Entidades conceptuales mínimas esperadas (no agregar entidades adicionales
sin que un requisito real lo justifique):

- **Guest** (invitado): identificador único; campos adicionales solo si hay
  información confiable (nombre, organización, rol, notas, edad aproximada,
  alcaldía); no se duplica por múltiples apariciones.
- **GuestCategory** (categoría del invitado = tipo de talento): catálogo
  configurable; un invitado puede tener varias (FR-004).
- **Borough** (alcaldía): catálogo de alcaldías de la CDMX, editable.
- **Video**: identificado por el ID de YouTube; metadatos posibles: ID,
  título, descripción, fecha de publicación, playlist, información del
  canal, miniatura, duración; además: tipo de video, alcaldía del evento
  (opcional), programa (opcional) y relación opcional con otro video
  (partes).
- **VideoType** (tipo de video): catálogo configurable (entrevista, evento,
  podcast…).
- **Participation** (participación): la aparición de un invitado en un
  video; relación N:N entre Guest y Video.
- **Program** (programa): opcional; nunca inferido sin evidencia.
- **ContactType** (tipo de contacto): catálogo configurable (FR-012).
- **Contact** (contacto): pertenece a un Guest; tipo, valor, nota, fuente,
  verificado (FR-012).

Relaciones:

- Guest (1) → (N) Contact; Contact (N) → (1) ContactType.
- Guest (N) ↔ (N) GuestCategory.
- Guest (N) → (0..1) Borough; Video (N) → (0..1) Borough (alcaldía del
  evento).
- Guest (N) ↔ (N) Video, a través de Participation.
- Video (N) → (1) VideoType.
- Video (N) → (0..1) Program.
- Video (N) → (0..1) Video (parte de otro video).

No existe la entidad Season (no hay temporadas).

Regla de separación: los metadatos crudos de YouTube deben mantenerse
separados de las entidades de dominio validadas. Todo dato extraído o
inferido automáticamente es un candidato hasta su validación humana.

## 6. Requisitos técnicos generales (no ligados a stack específico)

- Las credenciales se cargan desde variables de entorno; nunca se
  commitean `.env`, API keys, tokens, contraseñas ni archivos de
  credenciales.
- Uso de Git, con mensajes de commit claros (preferir Conventional Commits
  cuando sea práctico).
- La lógica de ingesta, base de datos y negocio importante debe tener
  pruebas automatizadas.
- Arquitectura, configuración y decisiones importantes deben documentarse
  en el repositorio.

### Stack definido

- Backend: Python + FastAPI
- Base de datos: PostgreSQL en contenedor Docker; pgAdmin como servicio en
  `docker-compose.yml` para demostración (DBeaver solo si se solicita)
- Frontend: React
- Extracción de candidatos: LLM local vía Ollama (modelos ~3B)
- Fuente de datos: YouTube Data API v3

### Pipeline ligero de IA

Hardware de referencia: 16 GB de RAM, sin GPU dedicada (Intel UHD). Por eso
el pipeline debe pedirle poco al LLM:

- El LLM recibe solo título y descripción del video (no se usan
  transcripciones: alto costo, poco beneficio).
- Antes del LLM se aplican reglas simples: detectar videos sin invitados
  (FR-014) y extraer enlaces/correos con expresiones regulares.
- Se procesa un video a la vez, de forma idempotente por `video_id`.
- La salida del LLM es estructurada e incluye nivel de confianza.
- Todo resultado es candidato hasta validación humana (FR-009).

## 7. Roadmap (por fases)

Roadmap de referencia, organizado por fases con entregables tipo viernes.
El orden y el contenido de cada fase pueden ajustarse sobre la marcha, pero
debe quedar reflejado aquí y en la bitácora de contexto si cambia.

### Fase 1 — Diseño y fundación

- Modelado de base de datos (entidades, relaciones) a partir de la sección
  5 de este documento.
- Definición de arquitectura (monolito modular, stack, estructura de
  carpetas).
- Setup de entorno (FastAPI + PostgreSQL + React) y repositorio.

### Fase 2 — Autenticación y CRUD base

- Login para el usuario "administrador" (único usuario por ahora, con todos
  los permisos); el diseño debe permitir agregar roles después.
- CRUD manual de invitados, contactos, programas y participaciones, para
  poder cargar/editar información aunque el pipeline de IA todavía no
  exista.

### Fase 3 — Pipeline de ingesta (ETL con IA)

- Conexión a YouTube API: listar videos y extraer título y descripción
  (sin transcripciones).
- Integración con Ollama (LLM local) para proponer candidatos a invitados
  con nivel de confianza.
- Staging Review: interfaz para validar, editar o rechazar candidatos antes
  de guardarlos como entidades de dominio (cumple FR-009).
- Lógica idempotente por `video_id` (no duplicar al reprocesar).

### Fase 4 — Buscador y filtros

- Filtros combinados: tipo de talento, rango de edad, alcaldía, tipo de
  video, programa, nombre.
- Búsqueda libre.

### Fase 5 — Exportación

- Exportar resultados filtrados a Excel/CSV.

### Fase 6 — Seguimiento de re-contacto

- Cálculo automático de "última participación/contacto".
- Alertas o indicadores visuales de "tiempo sin contactar".

### Fase 7 — Carga histórica masiva

- Correr el pipeline sobre todo el histórico de videos (2022 en adelante,
  incluyendo los de la etapa anterior del canal, todos bajo el nombre
  X Live Medios).
- Validación humana masiva vía Staging Review.

### Fase 8 — Pulido, pruebas y entrega

- Pruebas de usuario con Israel.
- Ajustes de UX, documentación y despliegue final.

## 8. Preguntas abiertas heredadas (aún sin resolver)

Estas preguntas ya se plantearon en la etapa anterior y siguen sin
respuesta. No se deben perder al reiniciar el proyecto.

- **Fechas definitivas de inicio y fin del proyecto.** Responsable:
  usuario/supervisor.
- **Lista de programas** del canal. Responsable: supervisor.
- **Qué datos del patrocinador** se guardan (empresa, persona, teléfono,
  correo); por ahora se guarda como contacto tipo "patrocinador" con valor y
  nota. Responsable: supervisor.
- **Aviso de privacidad/consentimiento** para almacenar datos personales de
  invitados (LFPDPPP). Responsable: supervisor.
- **Formato y columnas de la exportación**, y **plazo** desde el cual un
  invitado cuenta como "sin contactar" (FR-017, FR-018). Responsable:
  supervisor.
- **Acceso a YouTube**: quién crea la clave de la API desde una cuenta de la
  empresa. Responsable: supervisor/usuario.
- **Historial de cambios** (quién modificó qué): recomendado, no incluido en
  el alcance hasta aprobarse. Los roles adicionales quedan para el futuro
  (por ahora solo "administrador", FR-016).
- **Plataforma exacta de despliegue en producción.** Responsable: usuario.
- **Frecuencia de la ingesta automática periódica.** Responsable: usuario.

## 9. Información ya confirmada que no debe volver a preguntarse

- Canal oficial de YouTube: `https://www.youtube.com/@xlivemedios`.
- La aplicación web es parte del alcance del producto final (no es una
  fase futura opcional).
- Tipo de talento = categoría del invitado: catálogo configurable (como los
  tipos de contacto), varias por invitado, opcional (incluye personas
  comunes), creable desde la app.
- Alcaldías: las de la CDMX, como catálogo editable a futuro.
- Tipo de video (entrevista, evento, podcast…): catálogo configurable y
  amplio, sin lista definida.
- No existen temporadas. Algunos videos son "parte 2" de otro; la mayoría
  son libres, sin programa ni relación con otros videos.
- Edad aproximada, búsqueda por rangos. Alcaldía del invitado y del evento.
- Los videos de la etapa anterior del canal se incluyen, pero todo se maneja
  bajo el nombre X Live Medios; el nombre anterior no se menciona en el
  sistema.
- Contactos: catálogo de tipos + contactos por invitado; el patrocinador es
  del invitado; un invitado puede quedar "sin contacto".
- No se usan transcripciones de video: el LLM analiza solo título y
  descripción.
- Único usuario de la app: "administrador" con todos los permisos.
- Hardware de referencia: 16 GB de RAM, sin GPU dedicada; Ollama local con
  modelos ~3B.
- No se importan contactos personales del teléfono del supervisor (privacidad).
- No existe actualmente ningún Excel, base de datos o registro
  estructurado previo de invitados: la recolección inicial debe hacerse
  desde el contenido existente.
