# G5 · `v0.6.0a1` Workspace UX — plan

**Estado:** En curso (SPEC aprobada por el propietario con ajustes, 2026-11-02; E0 fusionado). **ADR-0013.** **Issue:** #49.
**Requisitos:** GD-UX-001..008. **Contrato:** `spec/specs/ui-ux-spec.md` §8; session-spec §2 (`CloseSession`);
qgis-bridge-spec §1 (interfaz); maqueta aprobada en issue #49, copiada en `docs/g5/maqueta/`.

**Gate:** ambos modos funcionales con un único estado; AT-UX-001..015 en la matriz de CI (QGIS 3.34, 3.40,
3.44, 4.2 × DuckDB 1.5.0, 2.0.0); las tres cargas de G3/G4 en ambos modos; revisión visual conforme a la
maqueta; regresiones G0–G4 completas. Tag y release `v0.6.0a1` solo con autorización del propietario.

## 1. Decisiones del propietario (2026-11-02)

| | Decisión |
|---|---|
| Fase | G5 Workspace UX antes de SQL Professional: G5 `v0.6.0a1`, G6 `v0.7.0a1`; las fases siguientes se desplazan; #68 a `v0.7.0a1` sin cambiar su alcance |
| IDs | GD-UX-002..008 y AT-UX-002..015 (equivalen a AT-UI-001..014 de la propuesta, en el mismo orden); ADR-0013 |
| Atajos | Sin F5 (QGIS lo usa); Ctrl+Enter sentencia, Ctrl+Shift+Enter todo; solo con foco en GeoDuck |
| Cargar en QGIS ▾ | La modalidad elegida abre el diálogo de G4 con ella marcada |
| Acciones existentes | «+» = Abrir/Crear; Desadjuntar en el menú de la base; Iniciar sesión y Revertir transacción en la barra de sesión cuando apliquen. **Actualizado (2026-11-02, E4b):** «Iniciar sesión» / «Cerrar sesión» al pie de «Bases de datos»; sin «Activar spatial…» ni «⋯» |
| Ventana propia | Hija de la ventana principal de QGIS; la X oculta, no cierra la sesión |
| Ver en el mapa | QGIS al frente, capa seleccionada y zoom si la extensión es válida; si no, sin zoom y con aviso |

## 2. Entregas (un PR cada una)

| Entrega | Trabajo | Pruebas |
|---|---|---|
| **E0** | SPEC, roadmap, ADR-0013, este plan | `spec_sync --check` |
| **E1** | `WorkspaceController`/`WorkspaceContent` a partir del dock actual; `WindowShell` por defecto y `DockShell`; cierre de shell ≠ cierre de sesión | AT-UX-002, 003, 011 |
| **E2** | Alternancia con traslado reversible, tareas en curso, señales idempotentes, preferencias versionadas | AT-UX-004, 005, 010, 012, 014 |
| **E3** | Explorador (búsqueda, grupos, acceso), editor y resultados adaptativos | AT-UX-006, 007, 013 |
| **E4** | «Cargar en QGIS ▾», registro con filtros, barra de estado, «Ver en el mapa», ubicación de acciones | AT-UX-008, 009 |
| **E5** | Aceptación: CI, pruebas manuales (Windows, monitores, DPI), `docs/g5/acceptance.md` | AT-UX-001..015 |

## 3. Avance

| Entrega | Estado | PR |
|---|---|---|
| E0 SPEC, roadmap, ADR y plan | Fusionado (maqueta en `docs/g5/maqueta/`, #76) | #75 |
| E1 Workspace y dos shells | Fusionado: `WorkspaceContent` (antes `GeoDuckDock`), `WindowShell` por defecto (hija de QGIS, la X oculta) y `DockShell` (mismo `objectName`), `WorkspaceController` con traslado del mismo contenido, modo guardado en `geoduck/workspace/` (esquema 1); AT-UX-002, 003, 011 en `tests/qgis/test_workspace.py` | #78 |
| E2 Alternancia y preferencias | Fusionado: traslado reversible (si falla, el contenido vuelve al shell de origen, que sigue visible, y se informa); tareas en curso intactas; conexiones una sola vez; preferencias del esquema 1 validadas al leer: modo, geometría de la ventana (nunca fuera de pantalla), zona del panel, divisor por modo, pestaña y límite de vista previa. El ancho del explorador y el filtro del registro se guardan cuando existan esos controles (E3, E4). AT-UX-004, 005, 010, 012, 014 | #79 |
| E3 Explorador, editor y resultados | Fusionado: búsqueda sobre la instantánea del catálogo, grupos «Tablas (n)»/«Vistas (n)»/«Tablas temporales (n)», acceso por base; ventana con explorador lateral (ancho recordado) y panel con pestañas Explorador/SQL; tipo por columna («#», «Aa», tipo exacto en la ayuda), `NULL` ≠ cadena vacía ≠ texto 'NULL'; atajos solo con el foco en el panel SQL; botones del editor solo con icono si no caben. AT-UX-006, 007, 013 | #80 |
| E4 Acciones, registro, estado y mapa | En revisión: «Cargar en QGIS ▾» (clic = diálogo de G4; flecha = las tres modalidades con descripción, no disponibles desactivadas con el motivo; elegir una abre el diálogo con ella marcada); registro con filtros Todo/OK/Error (ocultan, no borran; mensaje completo en la ayuda y el nombre accesible), pestaña «Registro (n)» en el panel y debajo del SQL en la ventana, filtro recordado; «Ver en el mapa» (selecciona y hace zoom si la extensión es válida; si no, lo dice; se desactiva si la capa ya no está); barra de sesión con «Iniciar sesión» solo sin sesión, «Revertir transacción» solo abortada y «⋯» = «Activar spatial…»; «+» = Abrir existente/Crear nueva, botón de actualizar, «Desadjuntar» en el menú de la base; etiquetas cortas en panel estrecho. AT-UX-008, 009 | — |
| E4b Pulido visual | En revisión: identidad visual (paleta corporativa medida en la maqueta, tema claro y oscuro, solo en GeoDuck), tarjetas y barras como en `docs/g5/maqueta/inventario.md`; decisiones R1–R5 (sin «Activar spatial…»; sesión al pie de «Bases de datos»; diálogo de bases rediseñado); corrección de la carga de sentencias con `;` (G3) | — |
