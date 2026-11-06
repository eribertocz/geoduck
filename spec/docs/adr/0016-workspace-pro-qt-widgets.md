# ADR-0016 — Workspace Pro: interfaz nueva con Qt Widgets y sistema de diseño propio

**Estado:** Propuesto (aprobado el rumbo por el propietario, 2026-11-05) · **Fase:** G9 · `v0.10.0a1` ·
**Contrato:** workspace-pro-spec
**Relacionados:** ADR-0010 (paquetes), ADR-0011 (convivencia), ADR-0012 (cargas), ADR-0013 (dos presentaciones),
ADR-0014 (archivos `.sql`).

## Contexto
El propietario pide una interfaz de administrador de base de datos moderna, minimalista y profesional, con
libertad de diseño comparable a una aplicación web, **nueva** (no una corrección de la de G5–G8). Se evaluó
construirla con Svelte + TypeScript + Tailwind dentro de Qt WebEngine, con QML/Qt Quick y con Qt Widgets
(análisis del 2026-11-05).

Hechos comprobados:
- **Qt WebEngine no está garantizado en QGIS:** no viene en el instalador `.msi` de QGIS 3.x para Windows; en
  OSGeo4W 3.x es un paquete opcional; en QGIS 4.0 con OSGeo4W hubo informes de que faltaba el módulo de Python
  (QGIS #65398, marzo de 2026); el paquete de macOS no lo trae (QGIS PR #67624, cerrado sin fusionar en octubre
  de 2026); falta en QGIS 3.34, 3.44 y 4.2 de conda-forge (los de la CI de GeoDuck, verificado 2026-11-05).
- Instalarlo por cuenta de GeoDuck está prohibido (ADR-0011: nada de `pip` silencioso) y pedírselo al usuario
  contradice la instalación fácil.
- Qt Quick (QML) sí está en los tres entornos de la CI; Qt Widgets, siempre.

## Decisión
- La interfaz nueva se construye con **Qt Widgets** (`qgis.PyQt`) y un **sistema de diseño propio**: tokens
  (colores, tipografía, espacios, radios, sombras) en un solo lugar, temas claro y oscuro, estilos generados y
  aplicados solo a GeoDuck, y componentes dibujados a mano donde Qt se ve anticuado.
- **Sin motor web** y **sin QML como base**. QML solo si una pieza concreta lo justifica, tras un spike en
  Windows y un ADR.
- Paquete nuevo `geoduck/ui/pro/`; la interfaz actual se retira cuando la nueva cubre todo (workspace-pro-spec
  §12). Motor, aplicación y puente con QGIS no cambian.
- Se mantienen `QgsCodeEditorSQL`, el lienzo del mapa y el arrastre del panel de capas de QGIS.

## Alternativas rechazadas
- **Svelte + Qt WebEngine + QWebChannel:** máxima libertad visual, pero falla en compatibilidad e instalación
  (arriba); la CI no podría probar la interfaz; un proceso Chromium aparte (del orden de 100–300 MB); los datos
  pasan como JSON por QWebChannel; el editor SQL, el mapa y el arrastre de capas quedarían fuera.
- **QML/Qt Quick como base:** disponible, pero con diferencias entre Qt 5 y Qt 6, riesgos con los controladores
  gráficos en Windows y peor integración con el editor y los diálogos de QGIS.
- **Corregir la interfaz actual:** descartado por el propietario: la interfaz debe ser nueva.

## Consecuencias
- Pro: funciona en toda instalación de QGIS 3.34+ y 4.x, sin dependencias nuevas; la CI sigue probando la
  interfaz en Qt 5 y Qt 6; integración total con QGIS.
- Pro: la calidad visual depende del sistema de diseño y de los componentes propios, no del motor.
- Contra: más trabajo de dibujo propio (grilla, pestañas, chips, paleta) que con HTML/CSS.
- Si QGIS llega a traer Qt WebEngine en todas sus instalaciones, se puede reconsiderar con un ADR nuevo.
