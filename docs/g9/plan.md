# G9 · `v0.10.0a1` Workspace Pro — plan

**Estado:** En curso (E0). **ADR-0016.** **Requisitos:** GD-WSP-001..012. **Contrato:**
`spec/specs/workspace-pro-spec.md`; maqueta aprobada `docs/g8/maqueta/1-tabla`, `2-consulta`, `3-panel`.

**Gate:** AT-WSP-001..012 en la matriz de CI (QGIS 3.34, 3.40, 3.44, 4.2 × DuckDB 1.5.0, 2.0.0); capturas de cada
pantalla aprobadas por el propietario; objetivos de rendimiento de §13; guía manual en Windows (incluye la de G8,
pendiente); regresiones G0–G8. Tag y release `v0.10.0a1` solo con autorización del propietario.

## 1. Decisiones del propietario (2026-11-05)

| | Decisión |
|---|---|
| Rumbo | Administrador de base de datos tipo TablePlus: pestañas de tabla y de consulta, Ctrl+K, recientes y favoritos; sin cuadernos; doble clic abre la tabla; editar celdas, después |
| Interfaz | **Nueva desde cero**, no corregir la actual; profesional, moderna, minimalista; «facilidad tremenda sin perder detalle» |
| Tecnología | Qt Widgets con sistema de diseño propio, sin motor web (ADR-0016), tras evaluar Svelte + Qt WebEngine |
| Cargar en QGIS | Una sola «Copia» (rápida por dentro; memoria como respaldo automático) y «Conectada»; prioridad al rendimiento |
| Enviar a DuckDB | «Reproyectar a…» global para todo el envío |
| G8 | La prueba manual de Windows de G8 se hace durante G9 |
| Estilo (E0b) | Aprobado el aspecto del spike (pestaña de tabla en Qt Widgets, claro y oscuro, Qt 5 y Qt 6) |
| «Copia» y proyecto (E0b) | Al guardar el proyecto, ofrecer «Guardar las copias junto al proyecto» (GeoPackage junto al `.qgz`); si no, «no disponible» con su motivo al reabrir |

## 2. Entregas (un PR cada una)

| Entrega | Trabajo | Pruebas |
|---|---|---|
| **E0** | SPEC (workspace-pro-spec), ADR-0016, roadmap, AT-WSP, este plan | `spec_sync --check` |
| **E0b** | Spike visual: pestaña de tabla en Widgets frente a la maqueta (capturas claro/oscuro, Qt 5/Qt 6), grilla de 1 millón de filas medida, y guardar/reabrir un proyecto con una «Copia» | Capturas aprobadas; medidas en `docs/evidence/g9/` |
| **E1** | Sistema de diseño: tokens, temas, estilos generados, componentes base, iconos | AT-WSP-001 (parcial); galería de componentes |
| **E2** | Estructura: ventana y panel, barra lateral (Recientes, ★, Bases), pestañas, barra superior, Ctrl+K (navegación) | AT-WSP-002, 006, 008 |
| **E3** | Pestaña de tabla: grilla por páginas, orden, chips, búsqueda, detalle, «Estructura», «Ver SQL» | AT-WSP-003, 004, 012 (parcial) |
| **E4a** | Pestaña de consulta: editor, ejecutar, resultado, mensajes, `.sql`, exportar; «Iniciar DuckDB» y todo en gris sin DuckDB | AT-WSP-005 |
| **E4b** | «Cargar en QGIS» (Copia / Conectada) en tabla y consulta, con «Copia» unificada y «Guardar las copias junto al proyecto» | AT-WSP-007 |
| **E5** | «Enviar a DuckDB» en el estilo nuevo; arrastrar en los dos sentidos (capas a una base; tablas al mapa con el mini menú Copia / Conectada); acciones de Ctrl+K | AT-WSP-009 |
| **E6** | Cambio a la interfaz nueva y retiro de la anterior (workspace, editor y cuadernos); idioma, teclado, accesibilidad, panel estrecho | AT-WSP-010, 011; regresión completa reescrita |
| **E7** | Aceptación: `docs/g9/acceptance.md`, rendimiento, guía de Windows (con la de G8), versión `0.10.0a1` | Gate |

## 3. Respuestas del propietario a las preguntas del E0 (2026-11-05)

Las tres, «sí»:
1. **100 filas por página** en la pestaña de tabla, sin selector.
2. **Recientes y favoritos se recuerdan entre reinicios** de QGIS (solo nombres en las opciones).
3. **Copia de recuperación** de consultas sin guardar, **activada** por defecto (como ADR-0014).

## 4. Avance

| Entrega | Estado | PR |
|---|---|---|
| E0 SPEC, ADR-0016, roadmap, AT-WSP y plan | Fusionado | #114 |
| E0b Spike visual y «Copia» | Fusionado (#115): pestaña de tabla en Qt Widgets frente a la maqueta (claro/oscuro, Qt 5/Qt 6), 1 millón de filas (primera página < 25 ms), F-123 (fuente con hojas de estilo); la «Copia» no sobrevive a reabrir el proyecto → propuesta «Guardar las copias junto al proyecto». `docs/evidence/g9/spike/` | #115 |
| E1 Sistema de diseño | Fusionado (#116): `geoduck/ui/pro/` — `tokens` (colores claro/oscuro con contraste AA verificado, familias, tamaños, espacios, radios, movimiento ≤ 150 ms), `style` (hoja generada y aplicada solo a la raíz de GeoDuck; sigue el tema de QGIS; F-123), `icons` (28 iconos SVG propios de trazo, de cualquier color), `widgets` (botones primario/secundario/fantasma/peligro y de icono, chips con Supr, «+ Filtro», segmentado, búsqueda con atajo, punto de estado, aviso con acciones y fundido). Galería `tools/pro_gallery.py` → `docs/evidence/g9/diseno/` | #116 |
| E2 Estructura | Fusionado (#117): `geoduck/ui/pro/` — `workspace` (barra lateral, cabecera con pestañas, «Buscar» y «Acoplar a QGIS», estados: sin sesión, iniciando, sin pestañas; pie con el último aviso), `sidebar` (sesión, filtro con letras en orden, «+», Recientes, ★ Favoritos, Bases con esquemas, vistas plegadas y temporales; menú contextual), `tabs` (abrir sin duplicar, reordenar, ×, clic central, Ctrl+W, «Consulta N»), `palette` (Ctrl+K: pestañas, recientes, acciones y todas las tablas; < 50 ms por tecla con 1 000), `places` (recientes y favoritos entre reinicios, solo nombres; atenuados con su motivo), `fuzzy`, `shell` (ventana ↔ panel con el mismo contenido; cabecera propia del panel; Ctrl+B recordado). Aún no se usa en el complemento (E6). Capturas `tools/pro_shots.py` → `docs/evidence/g9/estructura/` | — |
| E3 Pestaña de tabla | Fusionado (#118): `domain/browse` (SQL de solo lectura: página de 100, total aparte, filtros =, ≠, >, ≥, <, ≤, contiene, empieza por, es nulo, no es nulo; búsqueda en columnas de texto; orden con desempate estable; «Ver SQL»; estructura y tamaño en disco), `SessionCoordinator.read_rows` (sin `BUSY`), `ui/pro/table_page` (grilla con tipo bajo el nombre, número de fila, flecha de orden; chips; detalle de fila con valor completo y geometría resumida; «Estructura»; Ctrl+C; estados cargando, ocupada, error, sin filas; se relee si el SQL del usuario cambia datos). Capturas `tools/pro_table_shots.py` → `docs/evidence/g9/tabla/` | — |
| E4a Pestaña de consulta | Fusionado (#120): `ui/pro/query_page` (una barra: Ejecutar, Todo, Cancelar, base, «⋯»; editor SQL de QGIS con los colores del tema y el autocompletado de G6; resultado por sentencia con la grilla de E3; mensajes con línea, columna e «Ir»; «Exportar ▾» CSV y Parquet), `ui/pro/recovery` (abrir y guardar `.sql`, un cuaderno de G7 como una consulta, autoguardado, copia de recuperación por consulta), `ui/pro/editor`; «Iniciar DuckDB» / «Cerrar DuckDB» y todo en gris sin DuckDB; SPEC con las decisiones del 2026-11-06 (estado de DuckDB, nombres, arrastrar en los dos sentidos). Capturas `tools/pro_query_shots.py` → `docs/evidence/g9/consulta/` | — |
| E4b Cargar en QGIS | Fusionado (#121): `ui/pro/load` («Cargar en QGIS ▾» Copia / Conectada en tabla y consulta; «Copia» = la rápida o, si GDAL no la permite, la de memoria; todas las geometrías; el SRC solo se pregunta si falta, una vez para todas; «Exportar ▾» también en la tabla), `qgis_bridge/copies` (marca de las copias, GeoPackage junto al proyecto), `ui/pro/project_copies` (al guardar el proyecto: «Guardar las copias junto al proyecto»; al abrirlo, avisa de las copias perdidas). Capturas `tools/pro_load_shots.py` → `docs/evidence/g9/cargar/` | — |
| E5 Enviar y arrastrar | Fusionado (#122): `ui/pro/send` (capas soltadas: sin diálogo si todo es nuevo; si no, el diálogo de G8 con el estilo nuevo, sin «Qué pasará» si todo es nuevo y con «Más opciones»; progreso y «Cancelar» en el pie; aviso «N capas enviadas · Abrir · Deshacer»), `ui/pro/drag` (formato del panel de capas; tablas arrastradas desde la barra lateral; `PlacesDropHandler` con el mini menú Copia / Conectada, que registra el complemento en E6), barra lateral con la base resaltada al soltar, `QuickLoad.start_many` (un solo SRC para todas, cargas en cola). Capturas `tools/pro_send_shots.py` → `docs/evidence/g9/enviar/` | — |
| E6 Cambio y retiro | Fusionado (#123): el complemento usa Workspace Pro (`plugin.py`: `ProWorkspace` + `ProController`, menú de capa como soltar, «+»/Ctrl+K con diálogo, `PlacesDropHandler` registrado); se retiran `ui/workspace`, `workspace_controller`, `shells`, `sql_panel`, `explorer`, `notebook_list`, `notebook_view`, `result_summary`, `send_flow`, `load_dialog`, `load_flow` y `tools/screenshot_dock.py` (la CI captura con `tools/pro_shots.py`); nuevo `ui/pro/history` («Historial»), «Revertir» de la transacción abortada, «Ver en el mapa», entorno incompleto, preferencias y cuadernos abiertos de 0.9.0a1 (`migrate_settings`); el autocompletado se refresca al llegar columnas; pruebas de interfaz reescritas (`test_pro_switch` y las de G1–G8 que usaban la interfaz anterior) | — |
| E6b Más opciones al cargar | Fusionado (#124): «Cargar en QGIS ▾» › «Más opciones…» (`ui/pro/load_options`): qué geometrías, columna WKB/WKT como geometría, «Reproyectar a…» (Copia), «Separar por tipo» (Conectada), resumen de lo que se cargará; `QuickLoad` con `OPTIONS`. Capturas en `docs/evidence/g9/cargar/` | — |
| E7 Aceptación | Prueba de Windows hecha (propietario, 2026-11-12); cierre en revisión: [`docs/g9/acceptance.md`](acceptance.md) (AT-WSP-001..012, gate, revisión de la interfaz con el principio del balance, decisiones, hallazgos F-124..F-129), rendimiento con la interfaz real (`tools/pro_bench.py` → `docs/evidence/g9/rendimiento/`: todo dentro de §13), guía de Windows [`docs/certification/workspace-pro.md`](../certification/workspace-pro.md) (incluye G8; las de G5–G7 quedan como registro), versión `0.10.0a1` | — |
