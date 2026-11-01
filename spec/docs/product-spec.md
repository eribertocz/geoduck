# GeoDuck — Especificación funcional maestra (Product SPEC)

**Estado:** Draft aprobado para implementar mediante gates · **Versión del documento:** 0.1 · **Referencia:** `docs/roadmap.md`

## 1. Contrato y términos
- **Sesión:** contexto de ejecución DuckDB de GeoDuck, cuya raíz es `:memory:` y que puede tener catálogos adjuntos.
- **Base principal visible:** archivo seleccionado al iniciar; internamente se adjunta a la raíz. No confundir con la conexión física principal.
- **Resultado:** salida rastreable de una sentencia (estado o conjunto tabular).
- **Vista previa:** conjunto limitado de filas; nunca equivale por definición a la totalidad.
- **Entrega:** transferencia completa a una o más capas `memory` y registro en proyecto QGIS *después* de validar éxito.
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
| GD-SQL-001 | P0 | SQL nativo DuckDB completo, sujeto a privilegios reales | AT-SQL-001 |
| GD-SQL-002 | P0 | Script multi-sentencia, en orden, con estado por instrucción | AT-SQL-002 |
| GD-SQL-003 | P0 | Resultados tabulares independientes y vinculados a sentencia | AT-SQL-003 |
| GD-SQL-004 | P0 | Ejecutar actual, selección o todo | AT-SQL-004 |
| GD-SQL-005 | P0 | Preview limitado sin `fetchall()` de datasets grandes | AT-SQL-005 |
| GD-SQL-006 | P0 | No reejecutar DDL/DML al cargar capas; política de SELECT explícita | AT-SQL-006 |
| GD-SQL-007 | P1 | Autocompletado, historial, pestañas, formato y EXPLAIN | AT-SQL-007 |
| GD-BRD-001 | P0 | Cargar resultado tabular como capa de memoria QGIS | AT-BRD-001 |
| GD-BRD-002 | P0 | Transporte Arrow por lotes con conversión explícita | AT-BRD-002 |
| GD-BRD-003 | P0 | Progreso y cancelación sin manipular QGIS desde worker | AT-BRD-003 |
| GD-BRD-004 | P0 | Sin capas publicadas parcialmente ante error/cancelación | AT-BRD-004 |
| GD-BRD-005 | P0 | No gestionar ni vincular capas después de entrega | AT-BRD-005 |
| GD-SPA-001 | P0 | Detectar ausencia, una o varias columnas espaciales | AT-SPA-001 |
| GD-SPA-002 | P0 | Preguntar columnas cuando existan varias; opción capas separadas | AT-SPA-002 |
| GD-SPA-003 | P0 | Preservar/solicitar CRS; prohibido asignar CRS inventado | AT-SPA-003 |
| GD-SPA-004 | P0 | Gestionar nulos, incompatibilidad geométrica y errores WKB | AT-SPA-004 |
| GD-UX-001 | P0 | UI minimalista QGIS 3/4 con accesibilidad | AT-UX-001 |
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
