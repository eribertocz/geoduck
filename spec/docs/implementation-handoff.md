# GeoDuck — Contrato de trabajo para Claude Code (implementador)

**Arquitectura/especificación:** ChatGPT. **Implementación:** Claude Code. **Aprobación de producto/releases:** propietario.

## 1. Instrucción de arranque
> Implementar GeoDuck exclusivamente según `README.md`, `docs/product-spec.md`, `docs/architecture.md`, `specs/*.md`, `qa/*.md` y `docs/roadmap.md`. Antes de escribir features, ejecutar spikes G0-A/G0-B y producir un informe de compatibilidad verificable en Windows/QGIS3/QGIS4. No reescribir el producto como web app o servidor. No añadir un dialecto SQL. Mantener la frontera GeoDuck→QGIS.

## 2. Regla de oro
**DuckDB procesa; GeoDuck transfiere; QGIS administra.** Las capas entregadas son nativas QGIS memory, sin dependencia viva ni administración posterior por GeoDuck.

## 3. Orden de implementación
1. Preparar estructura mínima QGIS, metadatos, tests, UI dock y diagnóstico de entorno.
2. Integrar sesión raíz `:memory:` y worker propietario sin global connection.
3. Conexión principal mediante `ATTACH` RO/RW, explorador sincronizado, `DETACH` real y test de locks.
4. Parser nativo de scripts, ejecución ordenada, previews acotadas, resultado por sentencia.
5. Bridge Arrow por lotes y conversión PyQGIS en main thread con atomicidad.
6. Spatial multi-geometría + CRS + errores.
7. SQL editor profesional y UX refinada.
8. Cancelación/benchmark/packaging/hardening.

## 4. Implementar sin inventar
- No inventar `con.execute().to_arrow_reader()` streaming (se priorizan relaciones).
- No usar Qt widgets ni `QgsProject`/`QgsVectorLayer` dentro de worker.
- No reejecutar DML/DDL ni un script completo al cargar resultado.
- No auto-reconnect después de `DETACH`.
- No materializar todas las filas a pandas o `fetchall()`.
- No asumir CRS predeterminado.
- No publicar capas parciales o confundir preview con resultado completo.
- No bajar DuckDB por debajo de 1.5.0; toda API utilizada debe tener ruta probada para DuckDB 1.5.x y 2.x.
- No declarar «QGIS 3/4 compatible» sin prueba en ambos.

## 5. Contrato de PR
Cada PR informa: `versión/phase`, resumen, IDs GD-*, evidencias AT-*, riesgos, capturas UI cuando aplique, cambios de dependencias y alternativas evaluadas. Test fallido o limitación real se documenta, no se esconde.

Los ADR son obligatorios si se cambia: root session, API Arrow, responsable de capas, memoria→provider live, seguridad de extensiones, threading, dependencia tecnológica o estrategia multi-statement.

## 6. Definition of Done
- Criterios de aceptación satisfechos.
- Unit/integration/E2E pertinentes pasaron con evidencia.
- Sin pérdida silenciosa de datos, capas parciales, recursos activos post-DETACH o manipulación Qt en hilo secundario.
- Docs/README/roadmap actualizados.
- Sin dependencias no justificadas; instalación reproducible.
- Merge por el propietario según sus reglas de proyecto; no asumir privilegios.

## 7. Preguntas que sí debe elevar al propietario
Cambios de producto, aceptación de degradaciones incompatibles, renuncias a QGIS3/4 o DuckDB2, nuevos motores, persistent caches/SQL history sensible, arquitectura con servidor, nuevos alcances (dashboards/URL/live layers), fecha de beta/stable.

## 8. Primer entregable solicitado
Informe G0-A/G0-B con tabla de entornos reales, comandos/evidencia de import, funcionamiento de Arrow/Spatial, PyQGIS memory, editor SQL y recomendación de empaquetado Windows, más `metadata.txt` mínimo y test smoke; **sin** construir antes una arquitectura gigante sin pruebas.

## Actualización obligatoria de alcance
Claude Code debe implementar soporte mínimo de **DuckDB 1.5.0** y mantener compatibilidad probada con DuckDB 2.x. Queda prohibido codificar una dependencia incondicional de una API exclusiva de 2.x sin adaptación y prueba equivalente para 1.5.x.
