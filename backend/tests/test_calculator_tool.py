"""
The calculator evaluates plain arithmetic and math functions only: numexpr must
never resolve other names from the surrounding Python code.
"""

import math

import pytest

pytest.importorskip("numexpr")

from app.agents import tools  # noqa: E402
from app.agents.tools import _safe_calc  # noqa: E402


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 ** 10 + 1", 1025),
        ("2^3", 8),
        ("1e3 + 1", 1001),
        ("7 % 4", 3),
        ("sqrt(16) + sin(0)", 4),
        ("2*pi", 2 * math.pi),
        ("log(e)", 1),
        ("arctan2(1, 1)", math.pi / 4),
    ],
)
def test_arithmetic_and_math_functions(expression, expected):
    assert float(_safe_calc(expression)) == pytest.approx(expected)


@pytest.mark.parametrize("expression", ["expression", "numexpr", "allowed", "_CALC_MAX_LENGTH", "x + 1"])
def test_other_names_are_rejected(expression):
    assert _safe_calc(expression).startswith("Error: unknown name")


def test_module_and_frame_names_are_not_resolved_even_if_allowed(monkeypatch):
    # Without explicit namespaces numexpr reads the caller's globals and would answer 200.
    monkeypatch.setattr(tools, "_CALC_FUNCTIONS", tools._CALC_FUNCTIONS | {"_CALC_MAX_LENGTH"})
    result = _safe_calc("_CALC_MAX_LENGTH")
    assert result.startswith("Error")
    assert "200" not in result


def test_unsafe_characters_and_long_input_are_rejected():
    assert _safe_calc("__import__('os')") == "Error: expression contains unsafe characters"
    assert _safe_calc("1+" * 150 + "1").startswith("Error: expression longer than")
