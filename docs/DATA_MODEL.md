# Modelo de datos — X Live Medios

Deriva de la sección 5 de `PROJECT_BRIEF.md`. Tablas y columnas en inglés.
No existe `Season` (no hay temporadas). `users` (Fase 2) se agrega abajo, sin relaciones con
el resto. Las tablas de staging de la ingesta con IA (Fase 3: `ingestion_runs`,
`ingestion_run_errors`, `staging_guest_candidates`, `staging_contact_candidates`) se documentan
al final, aparte del diagrama principal para no saturarlo.

## Diagrama ER

```mermaid
erDiagram
    guest_categories ||--o{ guest_category_links : "clasifica"
    guests ||--o{ guest_category_links : "tiene"
    guests ||--o{ contacts : "tiene"
    contact_types ||--o{ contacts : "tipifica"
    boroughs |o--o{ guests : "vive en"
    boroughs |o--o{ videos : "alcaldía del evento"
    guests ||--o{ participations : "aparece"
    videos ||--o{ participations : "incluye"
    video_types ||--o{ videos : "tipifica"
    programs |o--o{ videos : "agrupa"
    programs ||--o{ program_host_links : "tiene"
    hosts ||--o{ program_host_links : "conduce"
    videos |o--o{ videos : "parte de"

    guests {
        int id PK
        string full_name
        string organization "opcional"
        string role "opcional"
        text notes "opcional"
        int approx_age "opcional"
        int borough_id FK "opcional"
    }
    guest_categories {
        int id PK
        string name UK
        bool is_active
    }
    guest_category_links {
        int guest_id PK,FK
        int category_id PK,FK
    }
    boroughs {
        int id PK
        string name UK
        bool is_active
    }
    contact_types {
        int id PK
        string name UK
        bool is_active
    }
    contacts {
        int id PK
        int guest_id FK
        int contact_type_id FK
        string value
        string note "opcional"
        string source "manual | video_description"
        bool verified
    }
    video_types {
        int id PK
        string name UK
        bool is_active
    }
    programs {
        int id PK
        string name UK
        bool is_active
    }
    hosts {
        int id PK
        string name UK
        bool is_active
    }
    program_host_links {
        int program_id PK,FK
        int host_id PK,FK
    }
    videos {
        int id PK
        string youtube_video_id UK
        string title
        text description "opcional"
        datetime published_at "opcional"
        string playlist "opcional"
        string channel_id "opcional"
        string channel_title "opcional"
        string thumbnail_url "opcional"
        int duration_seconds "opcional"
        int video_type_id FK "opcional"
        int event_borough_id FK "opcional"
        int program_id FK "opcional"
        int part_of_video_id FK "opcional"
        int possible_duplicate_of_video_id FK "opcional, Fase 3"
        datetime last_ingested_at "opcional, Fase 3"
        string guest_status "pending | has_guests | no_guests"
        string source "manual | youtube"
    }
    participations {
        int id PK
        int guest_id FK
        int video_id FK
        text notes "opcional"
    }
    users {
        int id PK
        string username UK
        string password_hash
        string role "administrador"
        bool is_active
    }
```

## Reglas por tabla

### Catálogos
`guest_categories`, `video_types`, `contact_types`, `boroughs`, `programs` y `hosts` comparten forma:
`id`, `name` único, `is_active` (desactivar en lugar de borrar, para no romper referencias).
Se administran desde la app (agregar, renombrar, desactivar). Fusionar categorías (FR-004) sigue pendiente.
La unicidad del nombre se valida en la aplicación ignorando mayúsculas, acentos y espacios extra;
la restricción `UNIQUE` de la BD solo cubre el nombre exacto.
- Solo `boroughs` se precarga (16 alcaldías de CDMX). Los demás empiezan vacíos: no se inventan datos.
- `guest_categories` = tipo de talento del invitado.
- `hosts` = conductores (quienes presentan un programa; no son invitados). Migración `0005`.

### program_host_links
Relación N↔N Program–Host, con clave primaria compuesta (`program_id`, `host_id`). Un programa puede tener
varios conductores y un conductor varios programas. La asignación es por programa (no por video). Se edita
desde Catálogos → Programas con `PUT /program-hosts/{program_id}` (reemplaza el conjunto completo).

### guests
- Un registro por persona; no se duplica por aparecer en varios videos.
- Solo `full_name` es obligatorio. Edad, alcaldía, organización, rol y notas son opcionales.
- `approx_age` guarda edad aproximada (búsqueda por rangos), `CHECK approx_age >= 0`.
- `borough_id` = alcaldía donde vive el invitado (opcional).

### guest_category_links
Relación N↔N Guest–GuestCategory. Clave primaria compuesta (`guest_id`, `category_id`), por lo que no se repite la misma categoría. Un invitado puede tener cero categorías.

### contacts
- Un invitado tiene 0..N contactos. Tipo por catálogo (`contact_types`), sin campos vacíos por tipo.
- `source`: `manual` o `video_description`. `verified` indica validación humana.
- El patrocinador es un contacto de tipo "patrocinador" con valor y `note` (ej. nombre de la empresa).
- Nunca se inventan valores.

### videos
- `youtube_video_id` único: evita ingesta duplicada. Los metadatos de YouTube viven en columnas propias del video, separados de las entidades de dominio (invitados, participaciones).
- `video_type_id`, `program_id`, `event_borough_id`, `part_of_video_id`: todos opcionales.
- `part_of_video_id` autorreferencia ("parte 2 de otro video"), `CHECK part_of_video_id <> id`.
- `guest_status`: `pending` (aún sin revisar), `has_guests`, `no_guests` (propuesta de la IA, reclasificable por un humano; FR-014).
- `source`: `manual` (cargado desde la app, migración `0004`) o `youtube` (lo trae la ingesta de la Fase 3). Permite localizar y borrar los videos de prueba cuando lleguen los reales. Los videos existentes al migrar quedan como `manual`.
- `possible_duplicate_of_video_id` (Fase 3, migración `0006`): autorreferencia que el orquestador llena cuando título+descripción normalizados coinciden con otro video y `published_at` está a ±14 días (evidencia real de 150 videos, ver `PHASE3_PLAN.md`); nunca se fusiona ni descarta solo, un humano lo confirma o limpia el campo desde la app.
- `last_ingested_at` (Fase 3, migración `0007`): cuándo lo procesó por última vez el orquestador (reglas + LLM); `NULL` = todavía no. Permite que una corrida no reprocese lo ya hecho.

### users
Usuarios de la app (migración `0003`). `username` único, contraseña solo como hash (argon2), `role` en texto
(hoy solo `administrador`) e `is_active`. Sin relación con las demás tablas: aún no se registra quién hizo cada cambio.

### participations
- Aparición de un invitado en un video (N↔N). `UNIQUE (guest_id, video_id)`.
- Un video puede tener cero participaciones. No se crean participaciones vacías para videos sin invitados.

## Tablas de staging (Fase 3, migración `0006`)
Todo lo que produce la ingesta (reglas de regex + LLM) es candidato: vive aparte de `guests`/
`contacts` hasta que un humano lo acepta, edita o rechaza en Staging Review. No están en el
diagrama principal porque no se relacionan con el resto del modelo de dominio, solo con
`videos` y, una vez aceptadas, con `guests`/`contacts`.

```mermaid
erDiagram
    videos ||--o{ staging_guest_candidates : "candidatos de"
    videos ||--o{ staging_contact_candidates : "candidatos de"
    ingestion_runs ||--o{ ingestion_run_errors : "errores de"
    ingestion_runs |o--o{ staging_guest_candidates : "produjo"
    ingestion_runs |o--o{ staging_contact_candidates : "produjo"
    staging_guest_candidates |o--o{ staging_contact_candidates : "contacto de"
    guests |o--o{ staging_guest_candidates : "vinculado a, si se aceptó"
    contacts |o--o{ staging_contact_candidates : "vinculado a, si se aceptó"

    ingestion_runs {
        int id PK
        datetime started_at
        datetime finished_at "opcional"
        string status "running | completed | failed"
        string trigger "manual | scheduled"
        int requested_batch_size "opcional"
        int processed_count
        int success_count
        int error_count
    }
    ingestion_run_errors {
        int id PK
        int ingestion_run_id FK
        string youtube_video_id "no siempre hay Video creado"
        text error_message
        datetime created_at
    }
    staging_guest_candidates {
        int id PK
        int video_id FK
        int ingestion_run_id FK "opcional"
        string extracted_name
        bool found_in_title
        bool found_in_description
        bool is_possible_group
        string category_match "opcional"
        bool category_is_new_suggestion
        float raw_confidence
        float adjusted_confidence
        text evidence
        string extraction_method "regex | llm"
        string status "pending | accepted | rejected"
        int linked_guest_id FK "opcional"
        datetime reviewed_at "opcional"
        datetime created_at
    }
    staging_contact_candidates {
        int id PK
        int video_id FK
        int ingestion_run_id FK "opcional"
        int guest_candidate_id FK "opcional"
        string type_hint
        string value
        float raw_confidence
        string extraction_method "regex | llm"
        string status "pending | accepted | rejected"
        int linked_contact_id FK "opcional"
        datetime reviewed_at "opcional"
        datetime created_at
    }
```

- **`ingestion_runs`**: historial de corridas del orquestador (fecha, estado, disparador,
  conteos). **`ingestion_run_errors`**: un error puntual dentro de una corrida; no detiene el
  resto del lote, se borra en cascada si se borra la corrida.
- **`staging_guest_candidates`**: `raw_confidence` es la cruda (del LLM o un valor fijo por
  patrón de regex); `adjusted_confidence` le suma el ajuste por señales objetivas (+0.15 si el
  nombre aparece en título y descripción, +0.10 solo en título, −0.20 si es posible grupo;
  valores iniciales de `app/services/pipeline.py`, ajustables tras validar con resultados
  reales). Staging Review ordena por el ajuste, no por la cruda. `extraction_method` distingue
  si lo encontró un patrón de regex o el LLM. `linked_guest_id` se llena al aceptar.
- **`staging_contact_candidates`**: `guest_candidate_id` es opcional — si es `NULL`, el
  contacto es a nivel video/evento (p. ej. un patrocinador), no de un invitado en concreto. El
  invitado al que se atribuye al aceptar (`ContactCandidateAccept.guest_id`) siempre lo elige
  quien revisa, nunca se infiere solo de este campo.
- `ingestion_run_id` en ambas tablas de candidatos usa `ON DELETE SET NULL` (no `CASCADE`): un
  candidato pendiente de revisión no debe perderse aunque se borre el historial de su corrida.

## Decisiones a confirmar
1. `playlist` como texto simple en `videos`. Si luego se necesita jerarquía de playlists, se convierte en tabla.
2. `ON DELETE`: catálogos → `RESTRICT` (se desactivan, no se borran con uso); `contacts`,
   `guest_category_links`, `participations` y las tablas de staging que cuelgan de un video →
   `CASCADE` al borrar el invitado o el video.

## Preguntas abiertas (no asumidas)
Lista de programas, datos del patrocinador, historial de cambios, plazo de "sin contactar",
aviso de privacidad (LFPDPPP, pendiente con el Ing. Israel antes de la carga histórica masiva
de la Fase 7 — ver `PHASE3_PLAN.md`).
