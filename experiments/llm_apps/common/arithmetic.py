"""The one safe arithmetic evaluator, shared by A4's tool and A5's solver.

Only numbers and ``+ - * / // % **`` are allowed: the expression is parsed with
:mod:`ast` and walked against a whitelist, so there is no ``eval``, no name, no
attribute access and no call. Anything else raises :class:`UnsafeExpression`.
"""

from __future__ import annotations

import ast
from typing import cast

MAX_EXPRESSION = 120
MAX_POWER = 12
MAX_MAGNITUDE = 1_000_000.0

_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
)


class UnsafeExpression(ValueError):
    """The expression is not plain arithmetic, and is refused."""


def safe_evaluate(expression: str) -> float:
    """Evaluate arithmetic from a whitelist of AST nodes; never ``eval``."""
    if not isinstance(expression, str) or not expression.strip():
        raise UnsafeExpression("give a plain arithmetic expression")
    if len(expression) > MAX_EXPRESSION:
        raise UnsafeExpression(
            f"the expression is longer than {MAX_EXPRESSION} characters"
        )
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpression("that is not a valid arithmetic expression") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise UnsafeExpression("only numbers and + - * / // % ** are allowed")
        if isinstance(node, ast.Constant) and (
            isinstance(node.value, bool) or not isinstance(node.value, (int, float))
        ):
            raise UnsafeExpression("only numbers are allowed")
    return _evaluate(tree.body)


def _evaluate(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        value = float(cast(float, node.value))
        if abs(value) > MAX_MAGNITUDE:
            raise UnsafeExpression("that number is too large")
        return value
    if isinstance(node, ast.UnaryOp):
        operand = _evaluate(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        return operand
    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise UnsafeExpression("cannot divide by zero")
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            if right == 0:
                raise UnsafeExpression("cannot divide by zero")
            return float(left // right)
        if isinstance(node.op, ast.Mod):
            if right == 0:
                raise UnsafeExpression("cannot divide by zero")
            return left % right
        if abs(right) > MAX_POWER or abs(left) > MAX_MAGNITUDE:
            raise UnsafeExpression("that power is too large")
        return left**right
    raise UnsafeExpression("only numbers and + - * / // % ** are allowed")


def format_number(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:.6g}"
