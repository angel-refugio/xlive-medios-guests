# Plan — Fase 4: Buscador y filtros

**Estado: fase activa desde 2026-10-12 (plan en borrador, sin codificar; hay un demo de la pantalla para que el Ing. Israel comente).** La fase 3 quedó completada
con la nota de la v6 pendiente (ver `docs/PHASE3_PLAN.md`). No se codifica hasta resolver las
preguntas abiertas de abajo. Este plan sale de `PROJECT_BRIEF.md` (Fase 4, FR-010), de lo hablado el
2026-10-12 y de lo que ya existe en el código. Lo que no está decidido está en "Preguntas abiertas".

## Objetivo

Que el administrador encuentre rápido a los invitados y sus apariciones sin buscar uno por uno:
por ejemplo "cantantes de cierta edad de cierta alcaldía" o "quiénes son actores". Cada resultado
muestra al invitado, sus participaciones (video, programa, tipo de video, fecha) y un indicador de
si tiene contactos.

Además, poder ver un resultado **sin haber revisado los ~3,500 videos**: la búsqueda puede
limitarse a lo revisado, a lo no revisado (candidatos de la IA) o a ambos.

## Alcance

**Dentro**
- Pantalla "Buscar" con filtros combinados y búsqueda libre (FR-010).
- Selector de alcance: **revisados** (valor por defecto) / **no revisados** / **ambos**.
- Endpoint de búsqueda de solo lectura, pensado para que la Fase 5 lo reutilice para exportar.
- Búsqueda por texto en los selectores de invitado y video que hoy cargan solo los primeros 200
  (cola de contactos de Staging Review y participaciones; ver `docs/PHASE2_PLAN.md`).

**Fuera (no se hace aquí)**
- Exportar a Excel/CSV (Fase 5). El resultado ya lleva la columna de estado para que exista.
- Mostrar los valores de los contactos: solo un indicador (ver "Contactos protegidos").
- Seguimiento de re-contacto (Fase 6), carga histórica masiva (Fase 7).
- Fusionar categorías (FR-004): sigue sin decidir.

## Qué hay hoy (punto de partida)

- `GET /guests` y `GET /videos` solo paginan; no filtran por texto, edad, alcaldía ni categoría
  (`videos` filtra por `source` y `guest_status`).
- `Guest` guarda `approx_age`, `borough_id` y categorías N↔N. El video guarda `video_type_id`,
  `program_id` y `event_borough_id`. `Participation` une invitado y video.
- Los invitados **no revisados** no están en `guests`: son filas de `staging_guest_candidates`
  (estado `pending`) con nombre, confianza, `category_match` (texto sugerido) y su video. No tienen
  edad ni alcaldía; esos datos se llenan al revisar.
- Los videos que son copia de un duplicado (📱) se ocultan con `_duplicate_copy_clause`
  (`app/services/staging_review.py`); la búsqueda debe respetar esa regla.
- Las pruebas del backend corren en SQLite; la app real, en PostgreSQL. La búsqueda no puede
  depender de funciones exclusivas de PostgreSQL.

## Diseño

### Qué devuelve la búsqueda
Un resultado por **invitado** (nombre normalizado), con:
`id` (null si no está revisado), nombre, `status` (`reviewed` / `unreviewed`), categorías,
edad aproximada, alcaldía, cantidad de contactos (solo el número) y la lista de participaciones
(video, programa, tipo, alcaldía del evento, fecha).

### Filtros (FR-010)
| Filtro | Se aplica a | Nota |
|---|---|---|
| Texto libre `q` | nombre del invitado, título del video | sin importar mayúsculas ni acentos |
| Tipo de talento (categorías) | solo revisados | varias a la vez = cualquiera. Medido el 2026-10-12: ningún candidato sin revisar trae `category_match` (0 de 138), así que en no revisados este filtro no encuentra nada hasta decidir la pregunta abierta de la v6 (ver `docs/PHASE3_PLAN.md`) |
| Rango de edad (`age_min`, `age_max`) | solo revisados | |
| Alcaldía del invitado | solo revisados | |
| Alcaldía del evento | video | |
| Tipo de video | video | |
| Programa | video | |
| Video | video (por id o título) | |
| Alcance | revisados / no revisados / ambos | por defecto, revisados |

Si se usa un filtro que solo existe en los revisados (edad, alcaldía del invitado), los no
revisados quedan fuera del resultado y la pantalla lo avisa ("estos filtros solo aplican a
invitados revisados").

### Búsqueda sin acentos, portable
Se agrega una columna con el nombre normalizado (`normalize_name`, la misma función que usan los
catálogos) en `guests` y en `staging_guest_candidates`, llenada por el servicio y rellenada por
la migración. Así "Lopez" encuentra "López" en SQLite y en PostgreSQL, sin la extensión `unaccent`.
Para los títulos de video se hace lo mismo (columna normalizada) solo si la prueba con datos reales
lo pide.

### Contactos protegidos
Los contactos están ocultos por defecto: verlos, buscarlos o exportarlos pide la contraseña del
admin (`CLAUDE.md`). Esa protección aún no existe y su diseño es pregunta abierta. En esta fase la
búsqueda **no** muestra ni busca valores de contactos: solo "tiene N contactos".

### Pantalla (demo del 2026-10-12)

Hay un demo navegable con los videos reales (copia fija, solo lectura; contactos sin valores) que se
comparte con el Ing. Israel para que proponga qué agregar o quitar. La pantalla real adapta ese diseño; los
cambios que pida el Ing. se anotan aquí antes de codificar.

- **Aviso inicial** para quien revisa: casi no hay contactos, los "sin revisar" son propuestas de la
  IA, edad y alcaldía están casi vacías. En la app real queda como aviso breve, no como bloque fijo.
- **Disposición:** filtros a la izquierda (se apilan arriba en celular) y resultados a la derecha.
  Tema oscuro, mismos colores de la app.
- **Alcance** como selector de tres botones (Revisados / Sin revisar / Ambos), arriba de los filtros.
- **Dos vistas:** "Por invitado" y "Por video" (cierra la pregunta 4 como propuesta: se incluyen las dos).
- **Tarjeta de invitado:** nombre, etiqueta Revisado / Sin revisar, talento, edad, alcaldía, línea de
  contactos y sus participaciones (con enlace "Ver en YouTube"). Las apariciones sin revisar de un
  invitado revisado se marcan una por una. Borde punteado en los sin revisar.
- **Tarjeta de video:** título, fecha, tipo, programa, alcaldía del evento, enlace a YouTube e
  invitados (con la misma etiqueta de estado).
- **Detalle al hacer clic** (ventana encima de la lista, se cierra con Esc): del invitado, con
  contactos y todas sus participaciones; del video, con duración, descripción e invitados. Se navega
  de uno a otro.
- **Contactos (protegidos):** con contactos, la tarjeta dice "Contactos: Instagram, Facebook (ocultos
  por seguridad)"; en el detalle, solo los tipos y la nota de seguridad. El demo mostraba además un
  valor tapado (`55********`) solo para ilustrar; **la app real no devuelve los valores**: solo los
  tipos. Sin contactos: "El invitado no tiene contacto".
- Valores vacíos se muestran como "sin dato" / "sin asignar"; los filtros que no aplican a sin revisar
  avisan en pantalla.

### Ordenamiento y paginación
Orden alfabético por nombre; páginas de 20 (máximo 100), igual que el resto de la API.

## Pasos

Cada paso es entregable por separado, con pruebas y sin cambiar el modelo salvo donde se indica.

1. **Búsqueda de invitados revisados (backend).** Migración con `normalized_name` en `guests`
   (con relleno) y servicio `app/services/search.py` con todos los filtros. Pruebas: cada filtro
   solo y combinados, acentos, varias categorías, rangos de edad abiertos, invitado sin
   participaciones, copias ocultas.
2. **Alcance "no revisados" y "ambos" (backend).** `normalized_name` en
   `staging_guest_candidates`; los candidatos pendientes se agrupan por nombre y se excluyen los de
   videos que son copia. Pruebas: candidatos rechazados o aceptados no aparecen, filtros que no
   aplican, mezcla en "ambos" sin repetir al mismo invitado.
3. **Endpoint `GET /search/guests`** (autenticado) con el contrato de arriba y manejo de errores
   con módulo y función en el mensaje. Pruebas de API: autenticación, validación de parámetros
   (rango de edad al revés, alcance inválido), paginación.
4. **Pantalla "Buscar" (React).** Sigue el diseño del demo (sección "Pantalla"): filtros con los
   catálogos existentes, selector de alcance, vistas por invitado y por video, etiqueta "sin
   revisar", enlace a YouTube y ventana de detalle de invitado y de video. Pruebas con el
   `fakeBackend`.
5. **Búsqueda por texto en los selectores de 200.** Endpoint ligero de autocompletado para
   invitados y videos, usado en la cola de contactos y en participaciones. Pruebas de backend y
   frontend.
6. **Cierre.** Verificación con los datos reales de la BD (consulta solo de lectura), docs
   (`ARCHITECTURE.md`, `README.md`, este plan en "completada") y revisión de rendimiento con
   ~3,500 videos.

Reglas de trabajo de siempre: sin tocar la fase 5, pruebas con cada código nuevo (las ejecuta el
usuario), commits locales y nunca `git push`.

## Preguntas abiertas

1. **Contactos en la primera versión:** ¿solo el indicador (propuesto) o también sus valores con
   la contraseña del admin? Esto depende de la pregunta abierta de reautenticación del brief.
2. **Un candidato que coincide con un invitado ya registrado** (mismo nombre exacto): ¿se muestra
   dentro de ese invitado como "participación sin revisar" (propuesto) o como un resultado aparte?
3. **Alcance por defecto:** ¿solo revisados (propuesto) o ambos?
4. **Búsqueda por video:** ¿basta el filtro por título/programa/tipo dentro de la búsqueda de
   invitados, o se quiere además una vista "por video"?
5. **Edad y alcaldía del invitado** están casi vacías hasta que se revise: ¿se acepta que esos
   filtros solo funcionen en revisados hasta la carga masiva (Fase 7)?

## Dependencias y riesgos

- La utilidad real depende de cuántos videos estén revisados; con ~24 revisados, los filtros de
  edad, alcaldía y talento devuelven pocos resultados. Por eso existe el alcance "no revisados".
- Mostrar datos de la IA sin confirmar exige que **siempre** estén marcados como "sin revisar", en
  pantalla y, en la Fase 5, en el archivo exportado.
- El aviso de privacidad (LFPDPPP) sigue pendiente con el Ing. Israel y bloquea la carga masiva,
  no esta fase.
