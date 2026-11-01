# GeoDuck — Visión y límites del producto

**Estado:** aprobado en principio · **Owner:** propietario del producto · **Fecha base:** 2026-11-01

## 1. Problema y oportunidad
El usuario de QGIS que ya usa DuckDB debería poder abrir una sesión, adjuntar archivos `.duckdb`, escribir SQL y entregar resultados como capas nativas sin exportar manualmente CSV, GeoPackage ni depender de un servidor. El valor de GeoDuck no es reinventar QGIS: es hacer que DuckDB se sienta **integrado, completo y transparente** dentro de QGIS.

## 2. Propuesta de valor
> **DuckDB procesa; GeoDuck interpreta el resultado y lo entrega; QGIS lo administra.**

GeoDuck privilegia la fidelidad semántica y la facilidad de uso por encima de interfaces cargadas de botones y promesas de rendimiento no demostradas.

## 3. Usuarios principales
- Especialista GIS que escribe SQL para análisis espacial.
- Analista de datos que dispone de tablas DuckDB, espaciales y no espaciales.
- Profesional que necesita combinar bases persistentes adjuntas y explorar sus datos dentro de QGIS.

No se necesita saber programar Python; sí son útiles conocimientos de SQL para la experiencia avanzada. Acciones de UI cubrirán los casos de selección de tabla/vista y ATTACH/DETACH.

## 4. Principios UX
1. Un panel acoplable en QGIS con explorador, editor y resultados, y diseño visual sobrio.
2. El siguiente paso evidente: abrir → consultar → entregar a QGIS.
3. Predeterminados inteligentes solo cuando no existe ambigüedad; preguntar cuando hay varias geometrías o CRS incierto.
4. Explicar los efectos de acciones sensibles, sin restringir artificialmente el SQL completo.
5. No alterar capas entregadas a QGIS, incluso tras `DETACH` o cierre de GeoDuck.
6. Mostrar límites reales: la vista previa no es el resultado completo; QGIS memory consume RAM.
7. Progreso y cancelación claros; no declarar éxito anticipado.

## 5. Frontera de propiedad
**GeoDuck es responsable** de instalación, sesión DuckDB, editor SQL, exploración, preview, selección de geometría, conversión de tipos, transferencia y validación antes de la entrega.

**QGIS es responsable**, después de una entrega exitosa, de renderizar, simbolizar, editar, guardar, exportar, eliminar y conservar las capas de memoria según sus propias reglas. Las capas no llevan conexión viva a DuckDB.

## 6. No objetivos de la Alpha inicial
No dashboards, no URLs/web, no API server, no capas DuckDB en modo vivo, no sincronización automática, no cambios en los datos fuente por editar la capa QGIS, no sustitución del administrador de capas, no soporte de QGIS 2.

## 7. Métrica de éxito
Flujo extremo a extremo reproducible; SQL de DuckDB sin dialecto inventado; `DETACH` sin residuos de GeoDuck ni pérdida de capas ya entregadas; manejo correcto de geometrías/CRS; interfaz QGIS responsiva; instalación y pruebas de compatibilidad verificadas.
