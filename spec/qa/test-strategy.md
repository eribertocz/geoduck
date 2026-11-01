# GeoDuck — Estrategia de pruebas y CI

**Estado:** baseline QA · **Política:** un feature sin test de aceptación no se considera completo.

## 1. Pirámide de pruebas
- **Unitarias** (rápidas, cada PR): parseo y planificación SQL, estados de sesión, quoting de rutas/alias, clasificación de resultados, mapeo de campos, CRS y políticas de retry/safe replay. Dobles para interfaces QGIS; no suplantan integración.
- **DuckDB real** (cada PR): `:memory:`, `ATTACH/DETACH`, scripts, `CREATE`, temporales, `SELECT`, DML y reader Arrow en v1.5.x y v2.x; no mocks del motor para aceptación.
- **PyQGIS real** (PR/release en runners Windows provisionados): creación de memory layer, campos, WKB, mezcla geométrica, entrega múltiple y descarte en cancelación.
- **E2E QGIS GUI** (gates/release): abrir dock, escribir SQL, cargar capa y comprobar que persiste tras `DETACH`; UI QGIS3 y QGIS4.
- **Seguridad, resiliencia y compatibilidad**: extensiones, bloqueos, interrupción, OOM simulado, errores tipo/CRS, instalación limpia.
- **Performance**: harness determinista con inventario hardware y datos generados repetibles.

## 2. CI por niveles
**PR requerido:** formato/lint, tests unitarios, tests DuckDB, build del plugin, validación metadata/documentación, verificación de dependencias y licencia, detección de APIs obsoletas.

**Integración de QGIS:** matrix Windows x64 QGIS 3.44 LTR y 4.2 latest, cada combinación en un entorno certificado. Si los runners GitHub estándar no tienen QGIS real, usar runners dedicados/VM provisionadas, y **reportar no ejecutado**, no declarar éxito verde ficticio.

**Release Alpha:** toda la matriz P0 real + E2E + benchmarks respecto baseline y auditoría de seguridad.

## 3. Casos de aceptación prioritarios
| ID | Escenario | Resultado esperado |
|---|---|---|
| AT-BOOT-001 | Abrir dock en QGIS 3/4 | sin errores de import/UI |
| AT-BOOT-002 | falta `pyarrow` | diagnóstico accionable, sin crash |
| AT-SES-001 | sesión :memory: | tablas temporales y SQL funcional |
| AT-SES-002 | archivo RO/RW | modos respetados, archivo no corrupto |
| AT-SES-003 | ATTACH por SQL y DETACH UI (y viceversa) | catálogo/UI iguales |
| AT-SES-004 | cargar capa → DETACH → inspeccionar capa | capa intacta; archivo liberado por GeoDuck |
| AT-SES-005 | BEGIN → INSERT → fallo → rollback | semántica DuckDB 1.5.x/2.x respetada |
| AT-CAT-001 | múltiples catálogos/esquemas y vistas | explorador completo y refrescado |
| AT-SQL-001 | CREATE/INSERT/COPY/EXPLAIN/SELECT | ejecución según DuckDB |
| AT-SQL-002 | script 2 SELECT + CREATE | estados ordenados, 2 resultados |
| AT-SQL-003 | pestañas de distintos resultados | cada preview corresponde al SQL correcto |
| AT-SQL-004 | ejecutar selección/actual/todo | solo lo elegido se ejecuta |
| AT-SQL-005 | SELECT un millón | preview acotada, no fetchall |
| AT-SQL-006 | DML RETURNING → cargar | no repetir DML; carga completa no disponible por replay |
| AT-SQL-007 | autocompletado en catálogos adjuntos | contexto correcto |
| AT-BRD-001 | SELECT sin geometría → QGIS | tabla memory íntegra |
| AT-BRD-002 | lector Arrow multi-lote | conteos/valores coinciden |
| AT-BRD-003 | cancelar carga prolongada | GUI responde, lector cerrado |
| AT-BRD-004 | fallo fila 30 001 | ninguna capa parcial publicada |
| AT-BRD-005 | capa entregada → cerrar GeoDuck | QGIS controla capa y atributos |
| AT-SPA-001 | 0/1/2 campos GEOMETRY | decisión adecuada, no geometría arbitraria |
| AT-SPA-002 | centroide + polígono → ambas capas | dos capas completas con geometría correcta |
| AT-SPA-003 | GEOMETRY con CRS y sin CRS | conservar/preguntar, nunca CRS inventado |
| AT-SPA-004 | geometría corrupta o mixta | error o separación explícita, no pérdidas |
| AT-UX-001 | pruebas teclado/tema/dock/Qt | acciones visibles y accesibles |
| AT-SEC-001 | extensiones externas y RO | restricciones y advertencias funcionan |
| AT-CFG-001 | reiniciar plugin | configuración sí, datos/capas no persistidos por GeoDuck |
| AT-COMP-001 | matriz QGIS/Python/Qt/PyArrow | reportes reproducibles por celda |
| AT-QA-001 | CI y perf baseline | informes vinculados a commit |

## 4. Tests adversariales obligatorios
- Alias con espacios/comillas y ruta Windows con acentos/Unicode.
- SQL con `;` dentro de strings, comentarios y macros.
- Reader Arrow abierto + tentativa de `DETACH`: no provocar `ResourceInUseException` sin manejo.
- SQL que referencia vista creada en `:memory:`; consultas posteriores usan mismo estado de sesión.
- SELECT antiguo tras `DROP` o `DETACH`: falla claramente, **sin** reconectar silenciosamente.
- `SELECT` volátil: no prometer coincidencia preview y carga completa.
- Queries sin `ORDER BY`: paginación no garantiza orden estable.
- `INSERT RETURNING`: no duplicar escrituras al hacer preview/cargar.
- CRS tipado vs CRS desconocido; EPSG confundible y ejes XY.
- `DECIMAL` de alta precisión y enteros grandes: sin corrupción silenciosa.
- Cancelación a mitad de 2 capas simultáneas: ninguna publicada.
- Reabrir archivo RW desde un proceso independiente tras `DETACH` exitoso.
- Ejecutar sin QGIS UI (headless) donde aplica; GUI real donde el caso lo exige.

## 5. Pruebas de compatibilidad
A cada plataforma/versión declarar: `certificado`, `conocido con limitaciones`, `no probado` o `incompatible`. Ninguna combinación sin prueba figura como certificada. Test de ejecución con `sys.executable` de QGIS, no un venv independiente.

## 6. Política de merges/releases
- Bloqueantes: 100% tests P0 de integridad/sesión, sin crash reproducible, sin corrupción de datos/capas, sin bypass de RO, sin incompatibilidad silenciosa.
- Lint/tests básicos verdes son necesarios pero **insuficientes** para gates de integración.
- Cada PR debe adjuntar test ID, evidencia y release target. Regresiones verificadas bloquean release. Los benchmarks no justifican reducir corrección.

## Matriz obligatoria de regresión DuckDB
- Ejecutar pruebas con **1.5.x y 2.x** (comenzando con 1.5.0 y 2.0.0 si sus wheels son compatibles con el runtime).
- Verificar por cada versión DuckDB + Spatial + PyArrow: SELECT lazy, lector por lotes, SQL mixto, ATTACH/DETACH, geometría y CRS, cancelación, archivo persistente y casos de error.
- Mantener artefactos de resultado y versión exacta; no declarar soporte para una combinación no probada.
