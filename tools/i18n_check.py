"""Extrae las claves _("...") del código y comprueba los catálogos de assets/locales.

Uso: python tools/i18n_check.py [--write-missing]   (devuelve 1 si falta alguna traducción)
--write-missing añade a cada catálogo las claves que faltan con valor "" para traducirlas.
"""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "assets" / "locales"


def keys():
    found = {}
    for path in sorted((ROOT / "pdf_editor").glob("*.py")):
        if path.name == "lang.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_", "N_", "ntext"):
                args = node.args[:1] if node.func.id in ("_", "N_") else node.args[1:3]
                for arg in args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        found.setdefault(arg.value, f"{path.name}:{node.lineno}")
    return found


def main():
    write = "--write-missing" in sys.argv
    source = keys()
    bad = 0
    for catalog in sorted(LOCALES.glob("*.json")):
        data = json.loads(catalog.read_text(encoding="utf-8"))
        missing = [k for k in source if not data.get(k)]
        extra = [k for k in data if k not in source]
        print(f"{catalog.stem}: {len(source) - len(missing)}/{len(source)} traducidas, {len(extra)} sobrantes")
        if write:
            for k in missing:
                data.setdefault(k, "")
            for k in extra:
                del data[k]
            catalog.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        elif missing:
            bad = 1
            for k in missing[:10]:
                print("  falta:", k[:70], "←", source[k])
    print(f"claves totales: {len(source)}")
    return bad


if __name__ == "__main__":
    sys.exit(main())
