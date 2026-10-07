# Propuesta: extracción de invitados con Claude

Oct 7, 2026 · @Angel

## Resumen ejecutivo

Se propone reemplazar el LLM local (Ollama, qwen2.5:3b) por Claude (Anthropic) como motor de extracción de invitados, conductores y programa, y rediseñar el Staging Review con base en el prototipo de 150 videos.

- **Por qué:** el prototipo analizado por Claude dio mejores resultados que la app actual. Claude ve muchos videos de una serie a la vez y puede inferir conductores y programas; el LLM local ve un solo video.
- **Costo:** \~190–400 MXN en total si el histórico (\~3,500 videos) y 3 años de videos nuevos se hacen con la API (Claude Sonnet 5.5); \~70–155 MXN si el histórico se hace con Claude Code (suscripción Pro, opcional) y solo los videos nuevos con la API.
- **Lo que no cambia:** toda propuesta de la IA sigue siendo candidata hasta validación humana (FR-009); YouTube sigue siendo solo fuente de metadatos.
- **Primer paso:** un piloto con los mismos 150 videos (menos de 20 MXN), medido contra las etiquetas manuales, antes de comprometer el cambio.

## Problema actual

El pipeline de la fase 3 alcanza \~90 % de recall y \~91 % de precisión en invitados, pero sus errores visibles impidieron mostrar la app real en la entrega semanal.

- **Modelo pequeño:** qwen2.5:3b corre en un equipo de 16 GB sin GPU; su capacidad de comprensión es limitada.
- **Un video a la vez:** el LLM no ve otros episodios de la misma serie, así que no puede deducir quién es conductor habitual ni corregir un nombre con base en otros videos.
- **Errores observados:** títulos de episodio tomados como invitados (por ejemplo, "Viaje a Marte").
- **Complejidad:** para compensar se agregaron reglas por serie, un clasificador y un modo de respaldo, que requieren mantenimiento.

## Evidencia: prototipo de 150 videos

El prototipo entregado como artifact demostró que Claude, al analizar los 150 videos juntos, propone programa, invitados y conductores con mejor calidad que la app actual.

- **Entrada:** los JSON crudos de la carpeta `samples` (título, descripción, fecha, duración, tags), obtenidos con YouTube Data API v3.
- **Salida:** por video, un programa, una lista de invitados, una lista de conductores, una lista de "dudosos" para que el humano decida y, en la propuesta, los contactos del invitado (ver "Un solo sistema para Claude Code y API").
- **Inferencia entre videos:** propuso conductores que no aparecen explícitamente en un video, porque los vio repetirse en otros episodios del mismo programa.
- **Interfaz:** filtros por programa, sin revisar, con nombres dudosos, sin invitados, sin conductor y sin programa; edición directa y botones Correcto / Corregir.

La mejora en calidad todavía no está medida con `eval_extraction`; el piloto (ver plan) debe confirmarla con números.

## Propuesta: arquitectura y flujo

El mismo flujo sirve para la carga histórica y para los videos nuevos; solo cambia el disparador (FR-011) y el tamaño del lote.

&#91;embedded content: flujo propuesto · histórico y videos nuevos\]

Lo validado por el humano (conductores y programas) se usa como contexto en las siguientes corridas, así un video nuevo se analiza con el conocimiento de su serie aunque llegue solo.

## Almacenamiento y despliegue

Los metadatos de \~3,500 videos (título y descripción) pesan pocos MB; el problema no es el tamaño sino dónde se guardan.

- **No van en el repositorio ni en el frontend:** ningún JSON masivo en Git ni cargado completo en el navegador.
- **Metadatos crudos en PostgreSQL:** tabla de videos crudos con columna `jsonb`, separada de las entidades validadas (regla de separación del proyecto).
- **Propuestas de Claude como candidatos:** se guardan en las tablas de staging, con estado pendiente hasta validación humana.
- **Interfaz:** la nueva revisión (tipo prototipo) es una página de React que consulta la API con paginación y filtros.
- **Credenciales:** la API key de Anthropic se carga desde `.env`, igual que la de YouTube; nunca se commitea.

## Un solo sistema para Claude Code y API

El histórico puede hacerse con Claude Code y los videos nuevos con la API sin duplicar lógica: pasar de uno a otro solo debe requerir configurar la API key.

- **Instrucciones únicas:** el prompt y las reglas de extracción viven en un solo archivo del repositorio; Claude Code y el módulo de la API usan el mismo.
- **Mismo formato de salida:** ambos producen el mismo JSON por video (programa, invitados, conductores, dudosos, confianza, contactos), validado con un esquema común.
- **Contactos en el mismo JSON:** cada contacto lleva tipo, valor, relación (propio / mánager / patrocinador), evidencia (fragmento de texto) y marca de dudoso con su motivo. Los que no se pueden atribuir a un invitado van en una lista de contactos sin asignar. No se incluyen contactos de conductores.
- **Misma llamada:** la regex saca los contactos del título y la descripción, y Claude, en la misma llamada que extrae los invitados, asocia cada contacto a su invitado y decide si es dudoso (por ejemplo, "varios invitados posibles" o "tipo no registrado"). Las reglas de revisión y los casos ambiguos están en `docs/PHASE3_PLAN.md`.
- **Mismo importador:** un solo proceso carga ese JSON como candidatos en staging; la base de datos, el Staging Review y la validación humana no distinguen de dónde vino el resultado.
- **Dos formas de ejecutar:** Claude Code escribe archivos que el importador carga; el extractor por API llama a Claude y entrega el JSON directo al importador.
- **Cambio a API:** agregar `ANTHROPIC_API_KEY` en `.env` y activar la ingesta programada. No se modifican tablas, interfaz ni importador.
- **Registro de origen:** cada candidato guarda si vino de Claude Code o de la API y la versión de las instrucciones usadas.

## Costos estimados

Con Claude Sonnet 5.5, el costo total por la carga histórica más 3 años de operación es de \~190–400 MXN.

| Modelo | Histórico 3,500 videos (USD) | 3 años de videos nuevos (USD) | Total (USD) | Total (MXN) |
| --- | --- | --- | --- | --- |
| Claude Haiku 4.5 | 3–7 | 2–4 | 5–11 | 85–190 |
| **Claude Sonnet 5.5 (recomendado)** | **7–14** | **4–9** | **11–23** | **190–400** |
| Claude Opus 5.5 | 14–28 | 9–18 | 23–46 | 400–790 |

Supuestos: \~400 tokens de entrada y \~100 de salida por video, más contexto por lote; \~10 videos nuevos al mes (360 en 3 años); tipo de cambio \~17.15 MXN/USD ([UnoTV, sept. 2026](https://www.unotv.com/dolar-hoy/tipo-de-cambio-hoy-17-de-septiembre-dolar-cotiza-en-17-15-pesos/)); precios por millón de tokens según [Anthropic](https://platform.claude.com/docs/en/about-claude/pricing). Los rangos incluyen margen por reintentos y pruebas. Procesar el histórico con la Batch API reduce esa parte a la mitad.

**Nota sobre contactos:** extraer y asociar contactos agrega pocos tokens por video (el texto ya se envía y la salida crece unas líneas), así que el estimado prácticamente no cambia; las cifras de la tabla no se modifican.

**Opción para el histórico: Claude Code (suscripción Pro).** El histórico puede procesarse con Claude Code, incluido en la suscripción Pro que ya se tiene, sin costo adicional. En ese caso solo se paga la API para los videos nuevos: \~4–9 USD (\~70–155 MXN) en 3 años con Sonnet 5.5. La ingesta automática de videos nuevos sí requiere la API: la suscripción no incluye créditos de API ni puede conectarse al backend.

## Plan de implementación

El cambio se hace en cuatro etapas; cada una termina con algo verificable y la siguiente solo empieza si la anterior cumple.

1. **Cierre de lo actual.** Correr las pruebas y migraciones pendientes y hacer los commits de la fase 3, para tener una base estable con la cual comparar.
2. **Piloto (150 videos).** Módulo de extracción con la API de Claude, mismos 150 videos de `samples`, medido con `eval_extraction`.
   - Criterio para seguir: recall y precisión de invitados mayores que el pipeline actual (\~90 % / \~91 %).
   - Costo: menos de 20 MXN.
   - También se miden los contactos contra etiquetas manuales; es una medición informativa, no un criterio para seguir.
3. **Integración.** Reemplazar el extractor en la ingesta (manual y programada), guardar resultados como candidatos y rediseñar el Staging Review con base en el prototipo. Pruebas automatizadas del módulo nuevo, con la API simulada.
4. **Carga histórica (fase 7).** Procesar los \~3,500 videos por lotes agrupados por serie, con Claude Code (opcional, sin costo adicional) o con la Batch API, y validarlos en el Staging Review. El método se decide en la implementación; los videos nuevos siempre van por la API. Requiere antes el aviso de privacidad (LFPDPPP).

Las fases 4 a 6 (buscador, exportación, re-contacto) no cambian.

## Riesgos y lo que no cambia

| Riesgo | Mitigación |
| --- | --- |
| Dependencia de un servicio externo de pago | Costo bajo y predecible; el extractor queda detrás de una interfaz para poder cambiar de proveedor |
| La API falla o no responde | Reintentos con registro de errores; el video queda pendiente y se reprocesa en la siguiente corrida |
| Claude también se equivoca o inventa | Todo resultado es candidato; nada pasa a la BD validada sin revisión humana |
| Envío de datos a un tercero | Solo se envían metadatos públicos de YouTube, que también pueden incluir teléfonos o correos cuando aparecen en descripciones públicas; todo esto entra en la revisión del aviso de privacidad (LFPDPPP) |
| Costo mayor al estimado | Límite de gasto en la cuenta de API y medición real en el piloto |

**Lo que no cambia:** el modelo de datos (salvo la tabla de contactos, ver `docs/PHASE3_PLAN.md`), el stack FastAPI + PostgreSQL + React, YouTube como única fuente de metadatos, la regla de candidatos con validación humana y el alcance del proyecto.

## Decisiones solicitadas al supervisor

- [ ] Aprobar el cambio de Ollama a Claude como motor de extracción (cambio de stack).
- [ ] Aprobar el piloto de 150 videos (menos de 20 MXN).
- [ ] Elegir el método del histórico: Claude Code con la suscripción Pro (sin costo adicional) o la Batch API.
- [ ] Definir quién abre y paga la cuenta de la API de Anthropic para los videos nuevos (SystemKW o el residente) y el límite mensual de gasto.
- [ ] Confirmar el modelo: Sonnet 5.5 (recomendado) o Haiku 4.5 si el piloto muestra que basta.
- [ ] Revisar con el aviso de privacidad (LFPDPPP) el envío de metadatos públicos a un proveedor externo.
