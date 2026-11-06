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
| **E4** | Pestaña de consulta: editor, ejecutar, resultado, mensajes, `.sql`, exportar; «Cargar en QGIS» con «Copia» unificada | AT-WSP-005, 007 |
| **E5** | «Enviar a DuckDB» en el estilo nuevo; arrastrar capas a una base; acciones de Ctrl+K | AT-WSP-009 |
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
| E1 Sistema de diseño | En revisión: `geoduck/ui/pro/` — `tokens` (colores claro/oscuro con contraste AA verificado, familias, tamaños, espacios, radios, movimiento ≤ 150 ms), `style` (hoja generada y aplicada solo a la raíz de GeoDuck; sigue el tema de QGIS; F-123), `icons` (28 iconos SVG propios de trazo, de cualquier color), `widgets` (botones primario/secundario/fantasma/peligro y de icono, chips con Supr, «+ Filtro», segmentado, búsqueda con atajo, punto de estado, aviso con acciones y fundido). Galería `tools/pro_gallery.py` → `docs/evidence/g9/diseno/` | — |
