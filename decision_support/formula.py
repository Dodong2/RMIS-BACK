"""Custom scoring formulas for DSS indicators (client Task 76-B, Figma "Scoring Formula / Method").

A formula is plain arithmetic, parsed with `ast` and evaluated by walking a whitelist of node types, never `eval`.
Allowed: numbers, + - * /, parentheses, unary minus, min(...), max(...), and the variables in VARIABLES.
The result is clamped to 0-100, the same scale as the standard scores.
"""
import ast
import operator

# `score` = this indicator's standard 0-100 score; the rest are the raw values of each standard metric.
VARIABLES = (
    "score",
    "output_score",
    "compliance_score",
    "budget_utilization_pct",
    "monitoring_health",
    "renewal_eligible",
    "overrun_risk_inverse",
    "risk_score_inverse",
)
MAX_LENGTH = 300
# Task 77-A: people type the symbols they see in the standard formula text, so these are read as their ASCII form.
_ALIASES = {"×": "*", "÷": "/", "−": "-", "–": "-"}
_ALLOWED_CHARS = set("0123456789.+-*/(),_ \t\nabcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")

_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCTIONS = {"min": min, "max": max}


def _check(node):
    if isinstance(node, ast.Expression):
        return _check(node.body)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        return _check(node.left) | _check(node.right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _check(node.operand)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return set()
    if isinstance(node, ast.Name):
        if node.id not in VARIABLES:
            raise ValueError(f'Unknown variable "{node.id}". Use: {", ".join(VARIABLES)}.')
        return {node.id}
    if isinstance(node, ast.Call):
        if not (isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS) or node.keywords:
            raise ValueError("Only min(...) and max(...) can be called.")
        if len(node.args) < 2:
            raise ValueError(f"{node.func.id}(...) needs at least two values.")
        names = set()
        for arg in node.args:
            names |= _check(arg)
        return names
    raise ValueError("Only numbers, variables, + - * /, parentheses, min() and max() are allowed.")


def normalize(expression):
    text = (expression or "").strip()
    for alias, ascii_op in _ALIASES.items():
        text = text.replace(alias, ascii_op)
    return text


def validate(expression):
    """Return the variables the formula uses, or raise ValueError with a message for the user."""
    text = normalize(expression)
    if not text:
        raise ValueError("Enter a formula, or uncheck Edit to use the standard formula.")
    if len(text) > MAX_LENGTH:
        raise ValueError(f"A formula can be at most {MAX_LENGTH} characters.")
    bad = next((ch for ch in text if ch not in _ALLOWED_CHARS), None)
    if bad is not None:
        raise ValueError(f'"{bad}" can\'t be used in a formula. Use numbers, variables, + - * /, parentheses, min() and max().')
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        raise ValueError("The formula is not valid arithmetic. Check the operators and parentheses.")
    return _check(tree)


def _eval(node, values):
    if isinstance(node, ast.Expression):
        return _eval(node.body, values)
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, values), _eval(node.right, values)
        if isinstance(node.op, ast.Div) and right == 0:
            return 0.0  # shortcut: x / 0 counts as 0 (agreed default), not an error that stops the run
        return _BINARY[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp):
        return _UNARY[type(node.op)](_eval(node.operand, values))
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return float(values[node.id])
    return _FUNCTIONS[node.func.id](_eval(a, values) for a in node.args)


def evaluate(expression, values):
    """Score 0-100 for one project. `values` must hold every variable the formula uses."""
    validate(expression)
    result = _eval(ast.parse(normalize(expression), mode="eval"), values)
    return max(0.0, min(100.0, result))
