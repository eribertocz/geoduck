# GeoDuck — Modelo de seguridad y efectos de SQL

**Estado:** baseline Alpha. GeoDuck ejecuta código SQL **local elegido por el usuario**, no un servicio de SQL remoto.

## 1. Modelo de confianza
- El usuario puede introducir SQL con efectos de lectura/escritura, red o filesystem dependiendo de permisos de DuckDB y del proceso QGIS.
- GeoDuck no se presenta como *sandbox* de SQL no confiable. **No** ejecutar automáticamente scripts externos, repositorios o SQL generado por agentes sin revisión.
- El control RO de un catálogo `ATTACH` es específico de esa base y no impide `COPY` a un archivo distinto o cambios en otras bases.

## 2. Extensiones DuckDB
- Extensión `spatial` oficial: soportada, con carga explícita y estado visible; cualquier instalación de componentes que necesite red se comunica al usuario.
- No permitir extensiones sin firma por defecto.
- Preferir permitir extensiones oficiales y restringir comunitarias por configuración, sin bloquear arbitrariamente el editor como si fuera un SQL distinto.
- Instalación/carga de extensiones externas no controladas: mostrar advertencia/permiso explícito y registrar la decisión local.
- Nunca hacer `INSTALL`/`LOAD` desde un archivo remoto de manera silenciosa.

## 3. Operaciones destructivas
- Advertencia contextual para `DROP`, `TRUNCATE`, `DELETE` sin filtro, sobrescrituras, attach RW u operaciones que se identifiquen claramente como riesgo.
- Advertencias son **UX** y no garantía de bloqueo: UDF, macros y subconsultas complejas pueden tener efectos inesperados.
- Mantener acciones de confirmación legibles y no usar reglas por regex como supuesta política de seguridad.

## 4. Protección de datos
- Por defecto, no persistir previews ni contenido de capas ni historiales completos que puedan contener datos sensibles.
- Guardar SQL/historial solo mediante preferencia explícita o política configurable; sanitizar logging de rutas y literales sensibles.
- Configuración local con catálogo/alias, paths recientes y preferencias, con opción «borrar recientes». No almacenar passwords ni tokens en texto claro.
- Los datos pueden estar en RAM de QGIS después de entrega; esto es parte del contrato de capas de memoria y depende de QGIS.
- Cuando se considera un buffer temporal en disco, requiere ADR y controles de borrado/cifrado; no incluirlo en Alpha inicial.

## 5. Concurrencia y bloqueo
- Una sola sesión, worker serial: evita `DETACH` concurrente a una lectura activa de GeoDuck.
- Conflicto de RW con otro proceso: error claro; nunca forzar liberación de bloqueos de terceros.
- No usar un segundo canal oculto que siga manteniendo abierta la base después de un `DETACH`.

## 6. Modelo de amenazas resumido
| Amenaza | Mitigación | Riesgo residual |
|---|---|---|
| SQL destructivo accidental | confirmación y feedback | una consulta puede ocultar efectos |
| Extensión maliciosa | solo firma/categorías permitidas y confirmación | firmas no sustituyen auditoría |
| Datos en log | redacción y opt-in | previews voluntarias en UI |
| SQL o ruta inyectados desde diálogo | citas/parametrización estrictas | SQL escrito por usuario se ejecuta como tal |
| Bloqueos de archivo | `DETACH` real, cleanup y test externo | terceros pueden bloquear |
| Agotamiento de RAM | lotes, backpressure, advertencias | QgsVectorLayer(memory) mantiene copia completa |
| QGIS crash por threads | PyQGIS main-thread only | bindings/plugins externos |

## 7. QA y criterios de salida
No publicar Alpha externa si carga extensiones no firmadas por defecto, si ignora read-only, si conserva referencias DuckDB tras `DETACH`, si registra SQL sensible por defecto, o si manipula QGIS desde worker causando crashes.
