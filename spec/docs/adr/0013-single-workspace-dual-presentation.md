# ADR-0013 — Un solo workspace, dos presentaciones

**Estado:** Aceptado (propietario, 2026-11-02) · **Fase:** G5 · Workspace UX (`v0.6.0a1`) · **Issue:** #49
**Relacionados:** ADR-0010 (fronteras), ADR-0012 (tres modalidades), ui-ux-spec §8, session-spec §2.

## Contexto
GeoDuck vive hoy en un `QDockWidget`. El diseño aprobado en issue #49 pide trabajar en una ventana propia
amplia (por defecto) o en un panel acoplado que deje ver el mapa, con el mismo contenido. La sesión DuckDB,
el worker, los resultados, las cargas en curso y la edición de capas Conectadas no pueden duplicarse ni
reiniciarse por cambiar de presentación.

## Decisión
- Un `WorkspaceController` (estado y coordinación) y un `WorkspaceContent` (explorador, editor, resultados,
  registro y estado) **únicos** por instancia de GeoDuck.
- Dos shells intercambiables: `WindowShell` (`QMainWindow`, hija de la ventana principal de QGIS) y
  `DockShell` (`QDockWidget`). Solo uno es visible.
- Alternar = mover `WorkspaceContent` de un shell a otro en el hilo GUI, conservando identidad y conexiones.
  Las tareas pertenecen al controlador y a los servicios, nunca a un shell.
- Cerrar u ocultar un shell no es cerrar la sesión.
- Preferencias de presentación en `QgsSettings` (`geoduck/workspace/`) con versión de esquema.

## Alternativas rechazadas
- **Dos interfaces sincronizadas:** duplica señales y estado; riesgo de dobles ejecuciones.
- **`QDockWidget` flotante como ventana:** no da una ventana de trabajo real (menús, tamaño, foco) en Windows.
- **Recrear editor y resultados al alternar:** pierde cursor, selección y resultados, o repite consultas.
- **Segunda sesión DuckDB:** el archivo en escritura admite un solo proceso y el estado no se comparte.

## Consecuencias
- Propiedad Qt explícita: el contenido nunca queda sin padre ni con dos.
- Señales conectadas una sola vez al controlador (idempotentes); prueba de 20 alternancias (AT-UX-012).
- Traslado reversible: si falla, el shell de origen sigue operativo y nada se repite (AT-UX-014).
- G6 (SQL Professional) se construye sobre `WorkspaceContent`, sin nuevos shells.

## Invariantes y reversión
Sin SQL ni cargas repetidas, sin `COMMIT`/`ROLLBACK`/`DETACH` por alternar, sin cambios pendientes perdidos,
sin extensiones cargadas en silencio. Volver al panel único (comportamiento de G4) es posible quitando
`WindowShell`: el contenido y el controlador no dependen de él.
