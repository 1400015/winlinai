"""Runtime compatibility of annotations with the supported Python floor.

The project still supports Python 3.8 (``requires-python = ">=3.8"``), so an
annotation that is evaluated at import time must not use syntax that only
exists in a newer interpreter: PEP 585 generics (``list[str]``) arrived in
3.9 and PEP 604 unions (``int | None``) in 3.10.

Local variable annotations are not evaluated at runtime, but module level and
class level annotations are, which turns an otherwise valid annotation into
an ``ImportError`` on an older interpreter. ``from __future__ import
annotations`` postpones the evaluation of every annotation in the module, so a
module that uses it may use the modern syntax freely.
"""

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"

# Subscripted builtins and the PEP 604 union operator.
MODERN_BUILTINS = {"list", "dict", "set", "frozenset", "tuple", "type"}
# Standard-library generics that only became subscriptable in 3.9.
MODERN_STDLIB = {"Queue", "SimpleQueue", "ContextVar", "Lock", "RLock", "Event"}


def _annotation_nodes(tree):
    """Yield annotations that are evaluated when the module is imported."""
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            # Module level: `name: T = value`.
            yield node.annotation
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and item.value is not None:
                    # Class level: `name: T = value`.
                    yield item.annotation
                elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # A default value or a decorator is evaluated at import.
                    for argument in list(item.args.args) + list(item.args.kwonlyargs):
                        if argument.annotation is not None:
                            yield argument.annotation
                    if item.returns is not None:
                        yield item.returns


def _uses_modern_syntax(annotation):
    """Report whether the annotation needs Python 3.9 or 3.10."""
    for node in ast.walk(annotation):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return True
        if isinstance(node, ast.Subscript):
            value = node.value
            if isinstance(value, ast.Name) and value.id in MODERN_BUILTINS:
                return True
            if isinstance(value, ast.Name) and value.id in MODERN_STDLIB:
                return True
    return False


def _imports_annotations_future(tree):
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            return any(alias.name == "annotations" for alias in node.names)
    return False


class AnnotationCompatibilityTests(unittest.TestCase):
    def test_no_module_uses_newer_annotation_syntax_than_the_floor(self):
        offenders = []
        for path in sorted(SOURCE.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if _imports_annotations_future(tree):
                continue
            for annotation in _annotation_nodes(tree):
                if _uses_modern_syntax(annotation):
                    offenders.append("{}: {}".format(
                        path.relative_to(ROOT), ast.unparse(annotation)))
        self.assertEqual([], offenders,
                         "These annotations fail at import time on Python 3.8:\n" + "\n".join(offenders))

    def test_every_module_still_parses(self):
        for path in sorted(SOURCE.rglob("*.py")):
            with self.subTest(module=path.name):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


if __name__ == "__main__":
    unittest.main()
