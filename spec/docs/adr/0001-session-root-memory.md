# ADR-0001: una sesión DuckDB con raíz en memoria

**Estado:** Aceptado para Alpha · **Fecha:** 2026-11-01

## Contexto
El usuario exige iniciar `:memory:` o seleccionar archivo `.duckdb` RO/RW, y poder adjuntar/desadjuntar bases desde UI o SQL sin mantener archivos abiertos tras `DETACH`.

## Decisión
GeoDuck crea una conexión física explícita a `:memory:`. Los archivos —incluido el elegido en inicio— se incorporan como catálogos `ATTACH`. El Session Worker mantiene el ciclo de vida; la raíz interna queda protegida frente a detach de UI.

## Consecuencias
Pro: siempre se puede volver al catálogo raíz y desadjuntar el principal sin destruir el editor; temporales independientes de archivos.

Contra: conviene explicar qué es «base principal visible» frente a raíz física, y validar que `USE`/nombres de catálogos no confundan al usuario. El root no es un segundo motor.

## Verificación
AT-SES-001..005, en especial locks externos después de detach y sin referencias ocultas.
