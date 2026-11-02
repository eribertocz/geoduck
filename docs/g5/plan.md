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
| Acciones existentes | «+» = Abrir/Crear; Desadjuntar en el menú de la base; «⋯» = Activar spatial…; Iniciar sesión y Revertir transacción en la barra de sesión cuando apliquen |
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
| E1 Workspace y dos shells | En revisión: `WorkspaceContent` (antes `GeoDuckDock`), `WindowShell` por defecto (hija de QGIS, la X oculta) y `DockShell` (mismo `objectName`), `WorkspaceController` con traslado del mismo contenido, modo guardado en `geoduck/workspace/` (esquema 1); AT-UX-002, 003, 011 en `tests/qgis/test_workspace.py` | — |
