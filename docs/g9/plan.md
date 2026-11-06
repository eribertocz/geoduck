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

## 2. Entregas (un PR cada una)

| Entrega | Trabajo | Pruebas |
|---|---|---|
| **E0** | SPEC (workspace-pro-spec), ADR-0016, roadmap, AT-WSP, este plan | `spec_sync --check` |
| **E0b** | Spike visual: pestaña de tabla en Widgets frente a la maqueta (capturas claro/oscuro, Qt 5/Qt 6), grilla de 1 millón de filas medida, y guardar/reabrir un proyecto con una «Copia» | Capturas aprobadas; medidas en `docs/evidence/g9/` |
| **E1** | Sistema de diseño: tokens, temas, estilos generados, componentes base, iconos | AT-WSP-001 (parcial); galería de componentes |
| **E2** | Estructura: ventana y panel, barra lateral (Recientes, ★, Bases), pestañas, barra superior, Ctrl+K (navegación) | AT-WSP-002, 006, 008 |
| **E3** | Pestaña de tabla: grilla por páginas, orden, chips, búsqueda, detalle, «Estructura», «Ver SQL» | AT-WSP-003, 004, 012 (parcial) |
| **E4** | Pestaña de consulta: editor, ejecutar, resultado, mensajes, `.sql`, exportar; «Cargar en QGIS» con «Copia» unificada | AT-WSP-005, 007 |
| **E5** | «Enviar a DuckDB» en el estilo nuevo; arrastrar capas a una base; acciones de Ctrl+K | AT-WSP-009 |
| **E6** | Cambio a la interfaz nueva y retiro de la anterior (workspace, editor y cuadernos); idioma, teclado, accesibilidad, panel estrecho | AT-WSP-010, 011; regresión completa reescrita |
| **E7** | Aceptación: `docs/g9/acceptance.md`, rendimiento, guía de Windows (con la de G8), versión `0.10.0a1` | Gate |

## 3. Preguntas para el propietario (E0)

1. **Filas por página** en la pestaña de tabla: propuesta, **100** (como la maqueta), sin selector.
2. **Recientes y favoritos entre reinicios de QGIS:** propuesta, **sí** (solo nombres en las opciones).
3. **Copia de recuperación** de consultas sin guardar (como los cuadernos, ADR-0014): propuesta, **sí, activada**.

## 4. Avance

| Entrega | Estado | PR |
|---|---|---|
| E0 SPEC, ADR-0016, roadmap, AT-WSP y plan | En revisión | — |
