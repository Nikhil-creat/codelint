"""
Static analysis engine for the AI Code Review Assistant.

This module performs real static analysis on Python source code using the
built-in `ast` module (Abstract Syntax Tree) — the same technique used by
tools like pylint and bandit. It checks for:

  - Code structure & complexity (cyclomatic complexity per function)
  - Common bug-prone patterns (bare excepts, mutable default args, etc.)
  - Security risks (eval/exec, shell=True, hardcoded secrets)
  - Style issues (long lines, missing docstrings, overly long functions)

A weighted scoring model converts the discovered issues into a single
0-100 "code health score", which is what makes the dashboard meaningful
over time.
"""
import ast
import re
from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class Issue:
    category: str      # "bug", "security", "style", "complexity"
    severity: str       # "high", "medium", "low"
    line: int
    message: str

    def to_dict(self):
        return {
            "category": self.category,
            "severity": self.severity,
            "line": self.line,
            "message": self.message,
        }


# Severity weights used to compute the overall score deduction
SEVERITY_WEIGHT = {"high": 8, "medium": 4, "low": 1.5}

SECRET_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|api_key|apikey|token)\s*=\s*['\"][^'\"]{3,}['\"]"
)


class ComplexityVisitor(ast.NodeVisitor):
    """Computes a simplified cyclomatic complexity for each function.

    Cyclomatic complexity = 1 + number of decision points (if/for/while/
    except/boolean-ops/comprehension-ifs) in the function body. This is
    the standard McCabe complexity metric used by real linters.
    """

    def __init__(self):
        self.function_complexity: Dict[str, int] = {}

    def visit_FunctionDef(self, node):
        self._analyze_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._analyze_function(node)
        self.generic_visit(node)

    def _analyze_function(self, node):
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
            elif isinstance(child, (ast.comprehension,)):
                complexity += len(child.ifs)
        self.function_complexity[f"{node.name} (line {node.lineno})"] = complexity


class CodeAnalyzer:
    def __init__(self, source: str):
        self.source = source
        self.lines = source.splitlines()
        self.issues: List[Issue] = []
        self.tree = None
        self.syntax_error = None

    def analyze(self) -> Dict:
        try:
            self.tree = ast.parse(self.source)
        except SyntaxError as e:
            self.syntax_error = f"Line {e.lineno}: {e.msg}"
            return self._build_result(functions=0, classes=0, avg_cx=0.0)

        self._check_bugs()
        self._check_security()
        self._check_style()
        complexity_map = self._check_complexity()

        num_functions = sum(
            1 for n in ast.walk(self.tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        num_classes = sum(1 for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef))
        avg_cx = (
            sum(complexity_map.values()) / len(complexity_map) if complexity_map else 0.0
        )

        return self._build_result(num_functions, num_classes, avg_cx)

    # ---- individual checks -------------------------------------------------

    def _check_bugs(self):
        for node in ast.walk(self.tree):
            # Bare except clauses swallow all errors, including KeyboardInterrupt
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                self.issues.append(Issue(
                    "bug", "medium", node.lineno,
                    "Bare 'except:' catches all exceptions — specify an exception type."
                ))
            # Mutable default arguments are a classic Python footgun
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in node.args.defaults:
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        self.issues.append(Issue(
                            "bug", "high", node.lineno,
                            f"Mutable default argument in '{node.name}' — use None and "
                            f"initialize inside the function instead."
                        ))
            # Comparing to None/True/False with == instead of is
            if isinstance(node, ast.Compare):
                for op, comparator in zip(node.ops, node.comparators):
                    if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(comparator, ast.Constant):
                        if comparator.value in (None, True, False):
                            self.issues.append(Issue(
                                "bug", "low", node.lineno,
                                f"Use 'is'/'is not' when comparing to {comparator.value!r}, not '=='."
                            ))

    def _check_security(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                func_name = self._call_name(node)
                if func_name in ("eval", "exec"):
                    self.issues.append(Issue(
                        "security", "high", node.lineno,
                        f"Use of '{func_name}()' can execute arbitrary code — avoid it."
                    ))
                if func_name == "system" or (func_name == "popen"):
                    self.issues.append(Issue(
                        "security", "medium", node.lineno,
                        "Shelling out via os.system/popen risks command injection."
                    ))
                if func_name in ("run", "call", "Popen"):
                    for kw in node.keywords:
                        if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                            self.issues.append(Issue(
                                "security", "high", node.lineno,
                                "subprocess call with shell=True risks command injection."
                            ))
                if func_name == "loads" and self._is_pickle_call(node):
                    self.issues.append(Issue(
                        "security", "high", node.lineno,
                        "pickle.loads() on untrusted data can execute arbitrary code."
                    ))

        for i, line in enumerate(self.lines, start=1):
            if SECRET_PATTERN.search(line):
                self.issues.append(Issue(
                    "security", "high", i,
                    "Possible hardcoded secret/credential — use environment variables instead."
                ))

    def _check_style(self):
        for i, line in enumerate(self.lines, start=1):
            if len(line) > 100:
                self.issues.append(Issue(
                    "style", "low", i,
                    f"Line too long ({len(line)} > 100 characters)."
                ))
            if line.strip().startswith("# TODO") or line.strip().startswith("#TODO"):
                self.issues.append(Issue(
                    "style", "low", i, "Unresolved TODO comment."
                ))

        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not ast.get_docstring(node):
                    self.issues.append(Issue(
                        "style", "low", node.lineno,
                        f"'{node.name}' is missing a docstring."
                    ))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    body_lines = (node.end_lineno or node.lineno) - node.lineno
                    if body_lines > 50:
                        self.issues.append(Issue(
                            "style", "medium", node.lineno,
                            f"'{node.name}' is {body_lines} lines long — consider splitting it up."
                        ))
                    if len(node.args.args) > 5:
                        self.issues.append(Issue(
                            "style", "medium", node.lineno,
                            f"'{node.name}' takes {len(node.args.args)} parameters — consider a config object."
                        ))

    def _check_complexity(self) -> Dict[str, int]:
        visitor = ComplexityVisitor()
        visitor.visit(self.tree)
        for name, cx in visitor.function_complexity.items():
            if cx > 10:
                line = int(name.split("line ")[1].rstrip(")"))
                self.issues.append(Issue(
                    "complexity", "high", line,
                    f"'{name.split(' (')[0]}' has high cyclomatic complexity ({cx}) — refactor into smaller functions."
                ))
            elif cx > 6:
                line = int(name.split("line ")[1].rstrip(")"))
                self.issues.append(Issue(
                    "complexity", "medium", line,
                    f"'{name.split(' (')[0]}' has moderate cyclomatic complexity ({cx})."
                ))
        return visitor.function_complexity

    # ---- helpers -------------------------------------------------------------

    def _call_name(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return None

    def _is_pickle_call(self, node: ast.Call):
        return (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "pickle"
        )

    def _build_result(self, functions: int, classes: int, avg_cx: float) -> Dict:
        score = 100.0
        counts = {"bug": 0, "security": 0, "style": 0, "complexity": 0}
        for issue in self.issues:
            score -= SEVERITY_WEIGHT[issue.severity]
            counts[issue.category] += 1
        score = max(0.0, round(score, 1))

        return {
            "score": score,
            "lines_of_code": len([l for l in self.lines if l.strip()]),
            "num_functions": functions,
            "num_classes": classes,
            "avg_complexity": round(avg_cx, 2),
            "issues": [i.to_dict() for i in self.issues],
            "issue_counts": counts,
            "syntax_error": self.syntax_error,
        }
