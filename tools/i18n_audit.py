"""Lista textos en español del código que no pasan por _() / N_() (candidatos a traducir)."""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPANISH = re.compile(r"[áéíóúñ¿¡…]|\b(el|la|los|las|de|del|para|con|sin|una|un|no|se|que|en|es|por|tu|tus)\b", re.I)
SKIP_FILES = {"lang.py", "smoke.py", "theme.py"}


def main():
    total = 0
    for path in sorted((ROOT / "pdf_editor").glob("*.py")):
        if path.name in SKIP_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        wrapped = set()
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_", "N_", "ntext"):
                for sub in ast.walk(node):
                    wrapped.add(id(sub))
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                body = node.body
                if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                    docs.add(id(body[0].value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in wrapped and id(node) not in docs:
                text = node.value
                if len(text) > 2 and SPANISH.search(text) and " " in text.strip():
                    print(f"{path.name}:{node.lineno}: {text[:80]!r}")
                    total += 1
    print("sin envolver:", total)


if __name__ == "__main__":
    sys.exit(main())
