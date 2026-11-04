# GeoDuck — Especificación funcional maestra (Product SPEC)

**Estado:** Draft aprobado para implementar mediante gates · **Versión del documento:** 0.1 · **Referencia:** `docs/roadmap.md`

## 1. Contrato y términos
- **Sesión:** contexto de ejecución DuckDB de GeoDuck, cuya raíz es `:memory:` y que puede tener catálogos adjuntos.
- **Base principal visible:** archivo seleccionado al iniciar; internamente se adjunta a la raíz. No confundir con la conexión física principal.
- **Resultado:** salida rastreable de una sentencia (estado o conjunto tabular).
- **Vista previa:** conjunto limitado de filas; nunca equivale por definición a la totalidad.
- **Entrega:** transferencia completa a una o más capas QGIS y registro en el proyecto *después* de validar el éxito. Modalidades (ADR-0012): **Memoria** (capa `memory`), **Instantánea** (GeoPackage en `/vsimem`) y **Conectada** (proveedor `geoduck`, lectura bajo demanda sin copia).
- **Geometría primaria:** columna espacial usada para generar una capa QGIS determinada.
- **Estado Alpha:** producto en desarrollo, aunque determinadas versiones ya sean útiles.

## 2. Requisitos funcionales y aceptación

| ID | Prioridad | Requisito | Aceptación esencial |
|---|---|---|---|
| GD-BOOT-001 | P0 | Plugin Python aparece en QGIS y abre panel | AT-BOOT-001 |
| GD-BOOT-002 | P0 | Diagnóstico de dependencias con mensajes accionables | AT-BOOT-002 |
| GD-SES-001 | P0 | Iniciar sesión raíz `:memory:` | AT-SES-001 |
| GD-SES-002 | P0 | Adjuntar archivo de inicio RO/RW | AT-SES-002 |
| GD-SES-003 | P0 | `ATTACH`/`DETACH` por UI y SQL, sincronizados | AT-SES-003 |
| GD-SES-004 | P0 | `DETACH` real libera uso propio y no afecta capas QGIS ya entregadas | AT-SES-004 |
| GD-SES-005 | P0 | `USE`, temporales, parámetros de sesión y transacciones coherentes | AT-SES-005 |
| GD-CAT-001 | P0 | Explorar catálogos, esquemas, vistas y tablas | AT-CAT-001 |
| GD-CAT-002 | P1 | Columnas de cada tabla y vista en el explorador (nombre, tipo, geometría, nulos), leídas al expandir; insertar su nombre en el editor | AT-CAT-002 |
| GD-SQL-001 | P0 | SQL nativo DuckDB completo, sujeto a privilegios reales | AT-SQL-001 |
| GD-SQL-002 | P0 | Script multi-sentencia, en orden, con estado por instrucción | AT-SQL-002 |
| GD-SQL-003 | P0 | Resultados tabulares independientes y vinculados a sentencia | AT-SQL-003 |
| GD-SQL-004 | P0 | Ejecutar actual, selección o todo (G7: celda, selección de la celda o todo el cuaderno) | AT-SQL-004 |
| GD-SQL-005 | P0 | Preview limitado sin `fetchall()` de datasets grandes | AT-SQL-005 |
| GD-SQL-006 | P0 | No reejecutar DDL/DML al cargar capas; política de SELECT explícita | AT-SQL-006 |
| GD-SQL-007 | P1 | Autocompletado, varias pestañas de editor, historial de la sesión y «Explicar» (G6; en G7 el plan se pide escribiendo `EXPLAIN`) | AT-SQL-007..010 |
| GD-SQL-008 | P1 | Formato SQL, historial guardado en disco, búsqueda y reemplazo, snippets, `EXPLAIN ANALYZE` (sin fase asignada) | — |
| GD-BRD-001 | P0 | Cargar resultado tabular como capa de memoria QGIS (modalidad Memoria) | AT-BRD-001 |
| GD-BRD-002 | P0 | Transporte Arrow por lotes con conversión explícita | AT-BRD-002 |
| GD-BRD-003 | P0 | Progreso y cancelación sin manipular QGIS desde worker | AT-BRD-003 |
| GD-BRD-004 | P0 | Sin capas publicadas parcialmente ante error/cancelación | AT-BRD-004 |
| GD-BRD-005 | P0 | Memoria e Instantánea: no gestionar ni vincular capas después de la entrega (salvo liberar `/vsimem` cuando QGIS quita la capa) | AT-BRD-005 |
| GD-BRD-006 | P0 | Instantánea: copia por GDAL a GeoPackage en `/vsimem`, editable, con CRS e integridad; desactivada con motivo si GDAL < 3.8 | AT-BRD-006 |
| GD-BRD-007 | P0 | Normalización de tipos según qgis-bridge-spec §7, común a las tres modalidades; ninguna conversión silenciosa | AT-BRD-007 |
| GD-BRD-008 | P0 | Conectada: capa de tabla, vista o resultado SQL leída bajo demanda, con pushdown de extensión, atributos, FID y columnas | AT-BRD-008 |
| GD-BRD-009 | P0 | Conectada: control de contención entre el SQL del usuario y el dibujado (prioridad, páginas acotadas, cancelación) | AT-BRD-009 |
| GD-BRD-010 | P0 | Conectada: edición atómica con detección de conflictos y escritura por lotes; QGIS nunca informa éxito si DuckDB no confirmó | AT-BRD-010 |
| GD-BRD-011 | P0 | Conectada: ATTACH/DETACH, cierre y reapertura sin errores ni bloqueos; capas no disponibles y reconectables | AT-BRD-011 |
| GD-BRD-012 | P0 | Interfaz sencilla para elegir la modalidad, con progreso y cancelación | AT-BRD-012 |
| GD-SPA-001 | P0 | Detectar ausencia, una o varias columnas espaciales | AT-SPA-001 |
| GD-SPA-002 | P0 | Preguntar columnas cuando existan varias; opción capas separadas | AT-SPA-002 |
| GD-SPA-003 | P0 | Preservar/solicitar CRS; prohibido asignar CRS inventado | AT-SPA-003 |
| GD-SPA-004 | P0 | Gestionar nulos, incompatibilidad geométrica y errores WKB | AT-SPA-004 |
| GD-UX-001 | P0 | UI minimalista QGIS 3/4 con accesibilidad | AT-UX-001, AT-UX-013 |
| GD-UX-002 | P0 | Un solo workspace con dos presentaciones: ventana propia (por defecto) y panel acoplado a QGIS (ADR-0013) | AT-UX-002, AT-UX-003 |
| GD-UX-003 | P0 | Alternar ventana ↔ panel sin perder estado, sin repetir SQL ni cargas y sin señales duplicadas | AT-UX-004, AT-UX-005, AT-UX-012, AT-UX-014 |
| GD-UX-004 | P1 | Preferencias de presentación versionadas (modo, geometría, divisores, pestañas, filtros); nunca datos ni estado de DuckDB | AT-UX-010 |
| GD-UX-005 | P0 | Explorador con búsqueda local, grupos Tablas/Vistas/Tablas temporales y acceso por base | AT-UX-006 |
| GD-UX-006 | P0 | Resultados con tipo por columna, `NULL` distinguible y «hay más»; registro filtrable Todo/OK/Error | AT-UX-007, AT-UX-009 |
| GD-UX-007 | P0 | «Cargar en QGIS ▾», barra de estado y «Ver en el mapa» en ambos modos, sin cambiar G3/G4 | AT-UX-008 |
| GD-UX-008 | P0 | Cerrar u ocultar la superficie no cierra la sesión ni invalida capas | AT-UX-011 |
| GD-NB-001 | P1 | Cuadernos de celdas SQL en el workspace (sustituyen a las pestañas de editor): añadir, mover, borrar y plegar celdas; ejecutar una o todas en orden | AT-NB-001, AT-NB-002 |
| GD-NB-002 | P1 | Base por celda: `USE` de la base de la celda antes de ejecutarla, en la misma operación; nombres calificados de otras bases siempre válidos | AT-NB-003, AT-NB-004 |
| GD-NB-003 | P1 | Resultado debajo de cada celda (tipos, `NULL`, «hay más», filas y tiempo) con «Cargar en QGIS ▾» de G3–G5 | AT-NB-005 |
| GD-NB-004 | P1 | Resumen del resultado seleccionado: filas, columnas y tipo de cada columna, sin consultas nuevas (ayuda ⓘ del rótulo del resultado) | AT-NB-006 |
| GD-NB-005 | P1 | Lista de cuadernos de la sesión | AT-NB-007 |
| GD-NB-008 | P1 | Guardar y abrir cuadernos como `.sql` con marcas de celda, autoguardado en su archivo, volver a abrirlos al iniciar QGIS y copia de recuperación tras un cierre inesperado (ADR-0014) | AT-NB-012 |
| GD-NB-007 | P1 | «Exportar ▾» del resultado de una celda a CSV o Parquet con la consulta **completa** (`COPY (<consulta>) TO … (FORMAT …)`), nunca la vista previa; solo consultas de lectura | AT-NB-011 |
| GD-NB-006 | P0 | Sin regresión: autocompletado, historial, atajos, ventana ↔ panel e idioma (G5–G6) en cada celda | AT-NB-008..010 |
| GD-I18N-001 | P1 | Interfaz con textos en inglés y traducción al español (catálogo `.ts` de Qt Linguist) según el idioma de QGIS (issue #68) | AT-I18N-001 |
| GD-SEC-001 | P0 | Configuración de extensiones seguras y acceso explícito | AT-SEC-001 |
| GD-CFG-001 | P1 | Persistir preferencias, SQL guardado y conexiones recientes; no capas/datos | AT-CFG-001 |
| GD-COMP-001 | P0 | Probar pares QGIS/Python/Qt/DUCKDB/PyArrow | AT-COMP-001 |
| GD-QA-001 | P0 | CI, integración QGIS y benchmarks sin métricas fabricadas | AT-QA-001 |

## 3. Reglas de proceso
### 3.1 Inicio
1. Al abrir GeoDuck se ve un formulario compacto de sesión.
2. Modo en memoria: se inicia sesión editable en `:memory:`.
3. Modo archivo: la sesión física sigue siendo en memoria y el archivo se `ATTACH` como catálogo principal visible, con RO/RW explícito.
4. Una vez iniciada la sesión, habilitar explorador y editor.
5. Si falla abrir el archivo o cargar dependencias, explicar error y permitir corregirlo sin perder el estado útil previo.

### 3.2 Consultas, scripts y resultados
- Una o varias sentencias; el parser de DuckDB define los límites; no `split(';')` ingenuo.
- Ejecución ordenada, con un registro por sentencia: ID, SQL saneado, tipo, inicio/fin, estado, error y, si corresponde, preview.
- Cuando una sentencia falla: parar el script, explicar efectos ya aplicados; no rollback implícito.
- `CREATE`, `ATTACH`, `DETACH`, DML no producen capas automáticamente.
- Una instrucción con filas (`SELECT`, `RETURNING`, etc.) puede mostrar preview; un `RETURNING` no se reejecuta al cargar.
- «Cargar resultado activo» y «Cargar seleccionados» son acciones explícitas; cada resultado, si corresponde, puede crear 0/1/N capas por geometría.
- El soporte de cargar SELECT por reejecución es consciente del estado mutable; consultar `specs/sql-editor-spec.md`.

### 3.3 Capas QGIS
- Si no hay geometría, crear una tabla sin geometría.
- Si hay una geometría, elegirla automáticamente cuando el tipo y CRS son inequívocos.
- Si hay varias, preguntar y permitir una o varias capas; no inferir que el primer campo es el correcto.
- Transformación/corrección CRS solo con consentimiento, no automática oculta.
- Solo añadir al proyecto las capas ya completas; capas temporales privadas se descartan en error.

## 4. Reglas no funcionales
- **NF-01 Integridad:** 0 filas silenciosamente perdidas, duplicadas o truncadas por la transferencia.
- **NF-02 Memoria:** procesar resultados Arrow por lotes, sin `fetchall` no acotado; QGIS memory consume RAM real.
- **NF-03 Responsividad:** no ejecutar SQL pesado ni acceder al almacenamiento durante largo tiempo desde hilo principal.
- **NF-04 Compatibilidad:** soportar matrices certificadas; no atribuir compatibilidad solo por metadatos del plugin.
- **NF-05 Seguridad:** las extensiones ejecutan código nativo y las operaciones de archivos tienen efectos reales.
- **NF-06 Observabilidad:** log técnico opt-in, sin datos sensibles ni SQL completo por defecto.
- **NF-07 Simplicidad:** sin servicio externo ni dependencia obligatoria de servidor.
- **NF-08 Recuperabilidad:** fallos de conversión/cancelación no publican capas inválidas.

## 5. Estructura de trazabilidad
Los criterios `AT-*` aparecen en `qa/test-strategy.md`. Los detalles de diseño son normativos en `specs/*` y ADR. En caso de contradicción, una decisión explícita posterior del propietario resuelve el conflicto; Claude Code solicita la aclaración mediante issue/ADR y no improvisa el contrato.

## 6. No objetivos v0.x y entrada al backlog
Dashboards, mapa por URL, servidor GeoDuck, capas dinámicas, live refresh, reverse sync QGIS→DuckDB, múltiples motores de consulta, editor visual drag-and-drop y conectores no DuckDB propios. Registrar ideas, no implementarlas por iniciativa del implementador.
