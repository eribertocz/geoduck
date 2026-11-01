# SPDX-License-Identifier: GPL-2.0-or-later
"""Estado transaccional de la sesión (G1 paso 6, GD-SES-005; ADR-0007 puntos 5 y 6)."""

from __future__ import annotations

from enum import Enum


class TransactionState(str, Enum):
    #: Modo autocommit: no hay transacción explícita.
    NONE = "NONE"
    #: Transacción explícita abierta y utilizable.
    ACTIVE = "ACTIVE"
    #: Transacción abortada: solo admite `ROLLBACK`. Un `COMMIT` revertiría sin avisar (F-07).
    ABORTED = "ABORTED"

    @property
    def is_open(self) -> bool:
        return self is not TransactionState.NONE
