# ADR propuestos (pendientes de aprobación)

Estos ADR **no** modifican el contrato aprobado en `spec/`. Al aprobarse, el arquitecto los incorpora a
`spec/docs/adr/` y enmienda las especificaciones afectadas.

| ADR | Tema | Recoge | Fase | Estado |
|---|---|---|---|---|
| [0006](0006-connection-ownership.md) | Propiedad exclusiva de la conexión, serialización, ciclo de vida de lectores | Decisión arquitectónica 2026-11-01; F-01, F-02 | G0 | Propuesto |
| [0007](0007-cancellation-interrupt.md) | `interrupt()` como excepción controlada | Decisión arquitectónica 2026-11-01; F-09 | G0 | Propuesto |
| [0008](0008-geoarrow-geometry-transport.md) | Geometría y CRS vía GeoArrow nativo | Decisión arquitectónica 2026-11-01; F-10 | G3/G4 | Propuesto (requiere enmienda de spatial-spec §5) |
| [0009](0009-pyarrow-selection-by-matrix.md) | PyArrow por celda de matriz | Decisión arquitectónica 2026-11-01; F-03 | G0 | Propuesto |
| [0010](0010-package-boundaries.md) | Paquetes y fronteras de importación verificadas | architecture.md §6 | G0 | Propuesto |
