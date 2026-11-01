# SPDX-License-Identifier: GPL-2.0-or-later
"""Matriz de capacidades por versión de DuckDB.

Único lugar donde se decide según la versión de DuckDB. Cada capacidad cita la evidencia G0
(`docs/evidence/g0/README.md`). No se añaden ramas sin una prueba reproducible
(spec/docs/technology.md, GD-COMP-DB-001).
"""

from __future__ import annotations

from dataclasses import dataclass

from geoduck.domain.versions import Version

#: Mínimo funcional aprobado (spec/docs/technology.md).
MINIMUM = (1, 5, 0)
#: Recomendado: corrige `to_arrow_table()` de GEOMETRY (F-04). Pendiente de decisión D5.
RECOMMENDED = (1, 5, 4)

#: Versiones en las que `interrupt()` desde otro hilo se verificó con la suite de regresión
#: (F-09, `tests/engine/test_cancellation.py`). Ampliar este conjunto exige pasar esos tests
#: en la versión nueva (ADR-0007). Clave: (major, minor, patch).
INTERRUPT_VERIFIED: frozenset[tuple[int, int, int]] = frozenset(
    {
        (1, 5, 0),
        (1, 5, 1),
        (1, 5, 2),
        (1, 5, 3),
        (1, 5, 4),
        (1, 5, 5),
        (1, 5, 6),
        (2, 0, 0),
    }
)


@dataclass(frozen=True)
class EngineCapabilities:
    version: Version
    #: >= 1.5.0
    supported: bool
    #: >= 1.5.4
    recommended: bool
    #: `interrupt()` desde otro hilo verificado para esta versión exacta (ADR-0007).
    interrupt_verified: bool
    #: El motor rechaza por sí mismo el uso concurrente y las sentencias con un resultado abierto
    #: (2.0+: `ResourceInUseException`). En 1.5.x NO lo hace (F-01, F-02); GeoDuck protege siempre.
    engine_guards_open_result: bool
    #: `ATTACH ? AS x` con parámetro (2.0+; F-06). GeoDuck no lo usa: cita literales.
    attach_accepts_parameters: bool
    #: `con.complete()` existe para terminar un resultado DB-API abierto sin leerlo (2.0+).
    has_complete: bool

    @classmethod
    def for_version(cls, text: str) -> EngineCapabilities:
        v = Version.parse(text)
        is_2x = v.at_least(2, 0, 0)
        return cls(
            version=v,
            supported=v.at_least(*MINIMUM),
            recommended=v.at_least(*RECOMMENDED),
            interrupt_verified=(not v.is_prerelease) and v.release() in INTERRUPT_VERIFIED,
            engine_guards_open_result=is_2x,
            attach_accepts_parameters=is_2x,
            has_complete=is_2x,
        )


def is_interrupt_error(exc: BaseException) -> bool:
    """Reconoce una interrupción del motor.

    En `execute()` llega como `duckdb.InterruptException`; dentro de un lector Arrow llega como
    `OSError` con el texto «INTERRUPT Error» (F-09). Se compara por nombre de clase para no depender
    de la jerarquía de excepciones de cada versión.
    """
    if type(exc).__name__ == "InterruptException":
        return True
    return isinstance(exc, OSError) and "INTERRUPT Error" in str(exc)
