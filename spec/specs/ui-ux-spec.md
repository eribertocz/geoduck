# SPEC GD-UX — Interfaz moderna, minimalista y profesional

**Estado:** baseline Alpha · **ID:** GD-UX-001

## 1. Filosofía
Una sola superficie coherente dentro de QGIS: **explorar, escribir, consultar y entregar**. UI nativa Qt, respetando tema claro/oscuro de QGIS, tipografía de sistema, espaciado generoso, controles discretos, íconos consistentes y estados visibles. No introducir landing pages, dashboards ni animaciones innecesarias.

## 2. Disposición del dock
```text
┌─ GeoDuck ────────────── [Sesión: memoria | Archivo RO/RW] [Estado] ──┐
│ Explorador de catálogos │ Editor SQL [tab 1] [tab 2]                 │
│   ▶ memory             │ [Ejecutar] [Actual] [Selección] [Todo]    │
│   ▼ comercial (RO)     │ SELECT ...                                 │
│     esquemas           │                                            │
│       tablas/vistas    ├────────────────────────────────────────────┤
│   + Adjuntar / Detach  │ Resultados [#1] [#2] [Ejecuciones]         │
│                       │ Preview paginado / error / plan            │
│                       │ [Cargar activo en QGIS] [Cargar elegidos]   │
└───────────────────────┴────────────────────────────────────────────┘
```

El explorador puede colapsarse; el área del editor y resultados tiene divisores ajustables. El dock es redimensionable, con estados vacíos informativos.

## 3. Interacciones definidas
- **Inicio:** tarjeta discreta «En memoria» / «Archivo DuckDB», selector de archivo, toggle «Solo lectura / Lectura y escritura», botón «Iniciar sesión». La UI se desbloquea al confirmar la sesión.
- **ATTACH:** icono `+` al lado de catálogos; diálogo path, alias, RO/RW; feedback al finalizar.
- **DETACH:** menú contextual «Desadjuntar» con confirmación si hay operaciones propias activas. No mostrar advertencia falsa de que se perderán capas QGIS ya entregadas.
- **Tabla/Vista:** doble clic abre preview opcional o añade una consulta en editor; clic derecho «Cargar completa en QGIS» con selector espacial si aplica.
- **SQL:** botón principal «Ejecutar» opera sobre sentencia actual si no hay selección, o selección según preferencia explícita; comandos «Todo» y «Selección» inequívocos.
- **Resultados:** pestañas por sentencia con nombre legible y ID; cambiar pestaña selecciona solo ese resultado. `Cargar en QGIS` siempre etiqueta el resultado objetivo.
- **Múltiples geometrías:** selector pequeño con radiobutton/checkbox por columna, nombre/tipo/CRS; permitir uno o varios. No modal por cada consulta cuando no hay ambigüedad.
- **Progreso:** nombre operación, estado, filas procesadas, tiempo, cancelar; sin porcentaje inventado cuando no existe total.
- **Errores:** título comprensible, detalle expandible, acción de recuperación; conservar SQL para corregirlo.

## 4. Diseño visual
- Diseño monocromático por defecto con un acento derivado del tema QGIS; estados semanticamente accesibles (éxito/advertencia/error).
- Controles con alturas y espacios coherentes; evitar iconos sin texto o tooltip.
- Autocompletado contextual no intrusivo; errores de SQL resaltados sin cubrir código.
- Pestañas cerrables, atajos conocidos (Ctrl+Enter ejecutar actual, Ctrl+Shift+Enter ejecutar todo, Esc cancelar donde sea seguro), configurables.
- UI responsive dentro del dock; no usar tamaños fijos que hagan inutilizable un panel estrecho.

## 5. Accesibilidad e internacionalización
- Teclado completo, foco visible, etiquetado accesible, contraste, tooltips y lectores de pantalla cuando Qt lo permita.
- Español inicial; internacionalización por catálogos de traducción con idioma inglés listo para incorporar.
- Formatos numéricos locales en UI sin alterar sintaxis SQL ni precisión interna.

## 6. Estados obligatorios
`sin sesión`, `conectando`, `listo`, `ejecutando`, `preview disponible`, `resolución espacial`, `transfiriendo`, `cancelando`, `entrega exitosa`, `fallo recuperable`.

Para «entrega exitosa», no mostrar «capa lista» hasta que el proyecto QGIS haya registrado capas íntegras. Cuando se desadjunta una base, el explorador se actualiza; las capas entregadas no aparecen como «desconectadas» porque son independientes.

## 7. UX QA
Prueba de tareas guiadas con persona no programadora: adjuntar base, abrir tabla, cargar punto, desadjuntar y constatar que capa sigue visible. Prueba SQL avanzada: crear temporal, múltiples SELECT, alternar resultados, cargar sólo uno. Probar UI en Qt5 y Qt6 con distintos tamaños DPI.
