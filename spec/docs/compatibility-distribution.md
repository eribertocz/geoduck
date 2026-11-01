# GeoDuck — Compatibilidad y distribución Windows

**Estado:** plan de certificación. Compatibilidad declarada ≠ compatibilidad comprobada.

## 1. Horizonte y política
- Host: QGIS Desktop **3.x y 4.x**, sin QGIS 2.
- **Anclas de prueba iniciales al 2026-11-01**: QGIS 3.44.15 LTR (Qt5) y QGIS 4.2.3 (Qt6).
- QGIS 4.0.x: segunda prioridad de certificación. QGIS 3.x anteriores: best-effort hasta que existan pruebas efectivas.
- Windows 11 x64 primero. Otros SO en fases posteriores mediante decisiones registradas.
- DuckDB >= 1.5.0: verificar los wheels y las versiones Python soportadas por DuckDB 1.5.x y 2.x separadamente. Usar siempre el Python del QGIS instalado.
- PyArrow requiere coincidencia de ABI, arquitectura y wheels reales; verificar en `sys.executable` de QGIS.

## 2. Matriz de soporte
| Combinación | Política en Alpha | Estado al escribir docs |
|---|---|---|
| Windows x64 + QGIS 4.2.3 + DuckDB 1.5.x / 2.x | P0 certificación | **Pendiente prueba en QGIS real** |
| Windows x64 + QGIS 3.44.15 + DuckDB 1.5.x / 2.x | P0 certificación | **Pendiente prueba** |
| Windows x64 + QGIS 4.0.x | P1 | Pendiente |
| Windows x64 + QGIS 3.40 / 3.34 / 3.28 | P2 por viabilidad del Python del QGIS | Pendiente / podría no ser compatible |
| QGIS 2.x | excluido | no aplica |
| Linux / macOS con QGIS 3/4 | posterior | pendiente |

`qgisMaximumVersion=4.99` o metadatos equivalentes solo habilitan visibilidad del plugin en el repositorio; **no prueban** su funcionamiento. Empaquetar con imports vía `qgis.PyQt` y test Qt5/Qt6.

## 3. Diagnóstico de instalación
Al habilitar plugin: detectar QGIS y Qt exactos, Python/ABI/architecture, import de `duckdb`, versión `duckdb`, import de `pyarrow`, versión, carga `spatial` y derechos de instalación/lectura de extensiones.

Si algún requisito falla: presentar informe claro, no dejar excepción críptica ni intentar `pip install` silencioso. Proponer instrucciones específicas al entorno verificado de QGIS; nunca ejecutar un instalador externo sin consentimiento.

## 4. Estrategia de distribución
Fase 0: spike de instalación en Windows, comparando plugin ZIP con resolución guiada de dependencias, empaquetado de wheels compatibles y alternativa OSGeo4W. Elegir un solo método principal con evidencia.

Restricciones:
1. No incluir archivos de wheels sin revisar licencias y compatibilidad.
2. No mezclar DLL/Qt de Python independiente con QGIS, ni modificar un Python global.
3. No descargar paquetes automáticamente en cada apertura del plugin.
4. Prueba de instalación limpia y desinstalación limpia en cada versión ancla.
5. Mantener artefactos versionados reproducibles y notas de release con compatibilidad concreta.

## 5. Política hacia atrás
La compatibilidad con QGIS 3 es un objetivo **realista por matriz**, no promesa de soportar cualquier 3.x desde su primer release. No asumir compatibilidad con cualquier Python integrado en QGIS: determinar los wheels reales de DuckDB y PyArrow en cada matriz y notificar incompatibilidad cuando falten.

## 6. Condición para marcar «soportado»
Solo cuando pasen: instalación limpia, carga del panel, inicio/attach/detach, SQL multi-statement, streaming Arrow, geometría CRS y entrega de capa QGIS en el equipo de prueba correspondiente. El QGIS Plugin Checker complementa pero no sustituye pruebas.

## DuckDB mínimo 1.5.0
GeoDuck no debe exigir DuckDB 2.0. La rama 1.5.x es objetivo de soporte de primera clase junto a 2.x. Se requiere matriz independiente por QGIS, Python embebido, DuckDB, Spatial y PyArrow. La instalación no debe actualizar forzosamente una instalación compatible de DuckDB 1.5.x.
