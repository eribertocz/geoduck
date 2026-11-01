## Fase / versión
<!-- p. ej. G0 · v0.1.0a1 -->

## Resumen

## Requisitos (`GD-*`) e issues
<!-- Closes #N · GD-SES-001 -->

## Evidencia de aceptación (`AT-*`)
<!-- comando ejecutado, combinación (QGIS/Python/DuckDB/PyArrow) y resultado; enlace a artefacto de CI -->

| Prueba | Combinación | Resultado |
|---|---|---|

## Riesgos y limitaciones conocidas
<!-- un test fallido o una limitación real se documenta aquí, no se esconde -->

## Cambios de dependencias
<!-- ninguno / detalle y justificación -->

## Alternativas evaluadas

## Capturas de UI (si aplica)

## Lista de control
- [ ] No se usa la conexión DuckDB fuera del Session Worker (salvo la excepción documentada de cancelación).
- [ ] Ningún objeto QGIS/Qt de proyecto o widget se manipula fuera del hilo principal.
- [ ] Sin cambios de contrato en `spec/` (si los hay, enlazar ADR aprobado).
- [ ] Probado en DuckDB 1.5.x y 2.x.
- [ ] `CHANGELOG.md` actualizado.

> El merge a `main` lo realiza exclusivamente el propietario.
