# SPDX-License-Identifier: GPL-2.0-or-later
"""Expresiones de QGIS → SQL de DuckDB para la modalidad Conectada (qgis-bridge-spec §5.2).

PyQGIS no expone `QgsSqlExpressionCompiler` (F-61): sin compilar, un filtro se evalúa en Python sobre toda
la tabla (18–113 s con 1–5 M filas, F-66). Se compilan comparaciones, `AND`/`OR`/`NOT`, `IN`, `IS [NOT]
NULL`, `LIKE`/`ILIKE` y aritmética básica sobre columnas que llegan sin convertir. Si algo no se puede
traducir con la misma semántica, se devuelve `None` y el proveedor evalúa la expresión en Python sobre
lo ya filtrado en SQL.
"""

from __future__ import annotations

import math

from qgis.core import (
    QgsExpressionNode,
    QgsExpressionNodeBinaryOperator,
    QgsExpressionNodeColumnRef,
    QgsExpressionNodeInOperator,
    QgsExpressionNodeLiteral,
    QgsExpressionNodeUnaryOperator,
)

from geoduck.domain.sql_text import quote_identifier, quote_string_literal

B = QgsExpressionNodeBinaryOperator.BinaryOperator
_BINARY = {
    B.boEQ: "=",
    B.boNE: "<>",
    B.boLT: "<",
    B.boLE: "<=",
    B.boGT: ">",
    B.boGE: ">=",
    B.boAnd: "AND",
    B.boOr: "OR",
    B.boLike: "LIKE",
    B.boILike: "ILIKE",
    B.boNotLike: "NOT LIKE",
    B.boNotILike: "NOT ILIKE",
    B.boPlus: "+",
    B.boMinus: "-",
    B.boMul: "*",
    B.boMod: "%",
}


def _literal(value: object) -> str | None:
    if value is None or (hasattr(value, "isNull") and value.isNull()):
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value) if math.isfinite(value) else None
    if isinstance(value, str):
        return quote_string_literal(value)
    return None


def compile_expression(node: QgsExpressionNode | None, columns: set[str]) -> str | None:  # noqa: PLR0911, PLR0912 - una rama por tipo de nodo
    """SQL equivalente o `None`. `columns`: columnas que se pueden comparar tal cual en DuckDB."""
    if node is None:
        return None
    if isinstance(node, QgsExpressionNodeColumnRef):
        return quote_identifier(node.name()) if node.name() in columns else None
    if isinstance(node, QgsExpressionNodeLiteral):
        return _literal(node.value())
    if isinstance(node, QgsExpressionNodeUnaryOperator):
        inner = compile_expression(node.operand(), columns)
        if inner is None:
            return None
        if node.op() == QgsExpressionNodeUnaryOperator.UnaryOperator.uoNot:
            return f"(NOT {inner})"
        if node.op() == QgsExpressionNodeUnaryOperator.UnaryOperator.uoMinus:
            return f"(-{inner})"
        return None
    if isinstance(node, QgsExpressionNodeInOperator):
        left = compile_expression(node.node(), columns)
        items = [compile_expression(n, columns) for n in node.list().list()]
        if left is None or any(i is None for i in items):
            return None
        return f"({left} {'NOT IN' if node.isNotIn() else 'IN'} ({', '.join(items)}))"  # type: ignore[arg-type]
    if isinstance(node, QgsExpressionNodeBinaryOperator):
        op = node.op()
        left = compile_expression(node.opLeft(), columns)
        right = compile_expression(node.opRight(), columns)
        if left is None or right is None:
            return None
        if op in (B.boIs, B.boIsNot):  # QGIS: igualdad que trata NULL como un valor
            is_not = op == B.boIsNot
            if right == "NULL":
                return f"({left} IS {'NOT ' if is_not else ''}NULL)"
            return f"({left} IS {'' if is_not else 'NOT '}DISTINCT FROM {right})"
        if op not in _BINARY:
            return None
        return f"({left} {_BINARY[op]} {right})"
    return None
