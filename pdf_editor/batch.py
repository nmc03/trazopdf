"""Batch processing with recipes (no Qt): an ordered list of steps applied to every PDF of a set.

A recipe is a versioned JSON document. ``run_batch`` chains the steps file by file through
temporary files, never touches the originals and keeps going when one file fails.
The signing password is asked for at run time and is never part of a recipe.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .lang import _, N_

RECIPE_VERSION = 1
CONFLICT_MODES = ("renombrar", "omitir", "sobrescribir")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")
REPORT_NAME = "batch-report.json"
WATCH_DONE_FOLDER = "procesados"
PASSWORD_ENV = "PDFEDITOR_SIGN_PASSWORD"
OUTPUT_SUFFIX = "_procesado"
TEXT_SUFFIX = "_texto"

OK, SKIPPED, ERROR, CANCELLED_STATUS = "ok", "omitido", "error", "cancelado"


class RecipeError(ValueError):
    """The recipe is corrupt, from a newer version or names a step that does not exist."""


# --------------------------------------------------------------------- steps

@dataclass(frozen=True)
class Param:
    key: str
    kind: str            # bool | int | float | str | lines | choice | path
    default: object
    label: str           # source text (N_), translate with _() when shown
    choices: tuple = ()
    low: float | None = None
    high: float | None = None


@dataclass
class Context:
    password: str | None = None
    cancelled: Callable[[], bool] = lambda: False
    progress: Callable | None = None


def _check_cancel(ctx):
    if ctx.cancelled():
        raise InterruptedError(_("Operación cancelada."))


def _edit(src, dst, change):
    """Open src, apply change(engine) and save to dst. The source file is only read."""
    from .engine import PDFEngine
    engine = PDFEngine()
    try:
        engine.open(src)
        change(engine)
        engine.save(str(dst))
    finally:
        engine.dirty = False
        engine.close()


def _step_anonymize(src, dst, p, ctx):
    from . import anonymize
    rules = {"terms": p["terms"], "regexes": p["regexes"], "case_sensitive": p["case_sensitive"], "whole_word": p["whole_word"]}
    report = anonymize.anonymize(src, dst, rules, anonymize.Options(remove_all_annotations=p["remove_all_annotations"], keep_bookmarks=p["keep_bookmarks"]))
    if not report.ok:
        raise ValueError(_("La anonimización no superó la verificación; no se genera salida."))


def _step_ocr(src, dst, p, ctx):
    from . import ocr_batch
    ocr_batch.ocr_file(src, dst, p["languages"] or None, deskew=p["deskew"], cancelled=ctx.cancelled)


def _step_optimize(src, dst, p, ctx):
    from .engine import PDFEngine
    options = {"jpeg_quality": p["jpeg_quality"], "remove_metadata": p["remove_metadata"]}
    if p["dpi"]:
        options["dpi"] = p["dpi"]
    engine = PDFEngine()
    try:
        engine.open(src)
        outcome = engine.optimize_preview(**options)
    finally:
        engine.dirty = False
        engine.close()
    PDFEngine._atomic_write(dst, outcome["data"])


def _step_sanitize(src, dst, p, ctx):
    _edit(src, dst, lambda engine: engine.sanitize())


def _step_watermark(src, dst, p, ctx):
    _edit(src, dst, lambda engine: engine.watermark(p["text"], p["size"]))


def _step_number_pages(src, dst, p, ctx):
    _edit(src, dst, lambda engine: engine.number_pages(p["start"]))


def _step_bates(src, dst, p, ctx):
    _edit(src, dst, lambda engine: engine.bates(prefix=p["prefix"], suffix=p["suffix"], start=p["start"], digits=p["digits"], position=p["position"]))


def _step_rotate(src, dst, p, ctx):
    _edit(src, dst, lambda engine: engine.rotate(list(range(engine.page_count)), p["angle"]))


def _step_crop(src, dst, p, ctx):
    def change(engine):
        for index in range(engine.page_count):
            page = engine._page(index)
            box = page.rect * page.derotation_matrix
            left, top, right, bottom = (p[k] for k in ("left", "top", "right", "bottom"))
            if left + right >= box.width or top + bottom >= box.height:
                raise ValueError(_("Los márgenes a recortar son mayores que la página."))
            engine.crop(index, (left, top, box.width - right, box.height - bottom))
    _edit(src, dst, change)


def _step_sign(src, dst, p, ctx):
    from . import signing
    if not p["p12"]:
        raise ValueError(_("Indica el certificado (.p12 o .pfx) con el que firmar."))
    if ctx.password is None:
        raise ValueError(_("Falta la contraseña del certificado."))
    signing.sign_file(src, dst, p["p12"], ctx.password, None, signing.Appearance(reason=p["reason"], location=p["location"]))


def _step_export_text(src, dst, p, ctx):
    from .engine import PDFEngine
    engine = PDFEngine()
    try:
        engine.open(src)
        engine.export_text(str(dst))
    finally:
        engine.dirty = False
        engine.close()


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    params: tuple
    run: Callable
    position: str = "any"      # "last": nothing may follow it
    extension: str = ".pdf"


STEPS = {s.key: s for s in (
    Step("anonymize", N_("Anonimizar"), (
        Param("terms", "lines", [], N_("Términos (uno por línea)")),
        Param("regexes", "lines", [], N_("Expresiones regulares (una por línea)")),
        Param("case_sensitive", "bool", False, N_("Distinguir mayúsculas y minúsculas")),
        Param("whole_word", "bool", False, N_("Solo palabras completas")),
        Param("remove_all_annotations", "bool", False, N_("Quitar todas las anotaciones")),
        Param("keep_bookmarks", "bool", False, N_("Conservar los marcadores")),
    ), _step_anonymize),
    Step("ocr", N_("OCR (texto buscable)"), (
        Param("languages", "str", "", N_("Idiomas (por ejemplo spa+eng; vacío = automático)")),
        Param("deskew", "bool", True, N_("Enderezar y orientar las páginas")),
    ), _step_ocr),
    Step("optimize", N_("Optimizar"), (
        Param("dpi", "int", 0, N_("Reducir imágenes a ppp (0 = sin cambiar)"), low=0, high=1200),
        Param("jpeg_quality", "int", 75, N_("Calidad JPEG"), low=10, high=100),
        Param("remove_metadata", "bool", False, N_("Quitar metadatos")),
    ), _step_optimize),
    Step("sanitize", N_("Limpiar metadatos y contenido oculto"), (), _step_sanitize),
    Step("watermark", N_("Marca de agua"), (
        Param("text", "str", "CONFIDENCIAL", N_("Texto")),
        Param("size", "int", 36, N_("Tamaño"), low=6, high=144),
    ), _step_watermark),
    Step("number_pages", N_("Numerar páginas"), (
        Param("start", "int", 1, N_("Número inicial"), low=0, high=1000000),
    ), _step_number_pages),
    Step("bates", N_("Numeración Bates"), (
        Param("prefix", "str", "", N_("Prefijo")),
        Param("suffix", "str", "", N_("Sufijo")),
        Param("start", "int", 1, N_("Número inicial"), low=0, high=100000000),
        Param("digits", "int", 6, N_("Dígitos"), low=1, high=12),
        Param("position", "choice", "bottom-right", N_("Posición"), choices=("bottom-right", "bottom-left", "bottom-center", "top-right", "top-left", "top-center")),
    ), _step_bates),
    Step("rotate", N_("Girar todas las páginas"), (
        Param("angle", "choice", 90, N_("Grados"), choices=(90, 180, 270)),
    ), _step_rotate),
    Step("crop", N_("Recortar márgenes"), (
        Param("left", "float", 0.0, N_("Izquierdo (pt)"), low=0, high=2000),
        Param("top", "float", 0.0, N_("Superior (pt)"), low=0, high=2000),
        Param("right", "float", 0.0, N_("Derecho (pt)"), low=0, high=2000),
        Param("bottom", "float", 0.0, N_("Inferior (pt)"), low=0, high=2000),
    ), _step_crop),
    Step("sign", N_("Firmar con certificado"), (
        Param("p12", "path", "", N_("Certificado (.p12 / .pfx)")),
        Param("reason", "str", "", N_("Motivo")),
        Param("location", "str", "", N_("Lugar")),
    ), _step_sign, position="last"),
    Step("export_text", N_("Exportar texto"), (), _step_export_text, position="last", extension=".txt"),
)}


def step_label(key):
    return _(STEPS[key].label)


def default_params(key):
    return {p.key: (list(p.default) if isinstance(p.default, list) else p.default) for p in STEPS[key].params}


def new_step(key):
    if key not in STEPS:
        raise RecipeError(_("Paso desconocido: «{step}».", step=key))
    return {"step": key, "params": default_params(key)}


# ------------------------------------------------------------------- recipes

def _coerce(step, param, value):
    kind = param.kind
    bad = RecipeError(_("Valor no válido para «{param}» en el paso «{step}».", param=param.key, step=step))
    if kind == "bool":
        if not isinstance(value, bool):
            raise bad
    elif kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (kind == "int" and not isinstance(value, int) and value != int(value)):
            raise bad
        value = int(value) if kind == "int" else float(value)
        if (param.low is not None and value < param.low) or (param.high is not None and value > param.high):
            raise bad
    elif kind in ("str", "path"):
        if not isinstance(value, str):
            raise bad
    elif kind == "lines":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise bad
        value = [v for v in value if v.strip()]
    elif kind == "choice":
        if value not in param.choices:
            raise bad
    return value


def validate_recipe(data):
    """Return a normalised copy of a recipe dict (defaults filled in) or raise RecipeError."""
    if not isinstance(data, dict):
        raise RecipeError(_("La receta no tiene el formato esperado."))
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise RecipeError(_("La receta no indica su versión."))
    if version > RECIPE_VERSION or version < 1:
        raise RecipeError(_("La receta es de una versión ({version}) que esta aplicación no entiende.", version=version))
    name = data.get("name", "")
    if not isinstance(name, str):
        raise RecipeError(_("El nombre de la receta no es válido."))
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise RecipeError(_("La receta no tiene ningún paso."))
    clean = []
    for index, item in enumerate(steps):
        if not isinstance(item, dict) or not isinstance(item.get("step"), str):
            raise RecipeError(_("El paso {n} de la receta está dañado.", n=index + 1))
        key = item["step"]
        if key not in STEPS:
            raise RecipeError(_("Paso desconocido: «{step}».", step=key))
        given = item.get("params", {})
        if not isinstance(given, dict):
            raise RecipeError(_("Los parámetros del paso «{step}» están dañados.", step=key))
        known = {p.key: p for p in STEPS[key].params}
        for extra in given:
            if extra not in known:
                if "pass" in str(extra).lower() or "contrase" in str(extra).lower():
                    raise RecipeError(_("Una receta no puede guardar contraseñas; se piden al ejecutarla."))
                raise RecipeError(_("Parámetro desconocido «{param}» en el paso «{step}».", param=extra, step=key))
        params = default_params(key)
        for pkey, value in given.items():
            params[pkey] = _coerce(key, known[pkey], value)
        clean.append({"step": key, "params": params})
    for index, item in enumerate(clean[:-1]):
        if STEPS[item["step"]].position == "last":
            raise RecipeError(_("El paso «{step}» debe ser el último de la receta.", step=step_label(item["step"])))
    return {"version": RECIPE_VERSION, "name": name, "steps": clean}


def make_recipe(name, steps):
    return validate_recipe({"version": RECIPE_VERSION, "name": name, "steps": steps})


def recipe_from_json(text):
    try:
        data = json.loads(text)
    except ValueError as error:
        raise RecipeError(_("La receta está dañada y no se puede leer: {error}", error=error)) from error
    return validate_recipe(data)


def load_recipe(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise RecipeError(_("La receta está dañada y no se puede leer: {error}", error=error)) from error
    except OSError as error:
        raise RecipeError(_("No se puede leer la receta {name}: {error}", name=Path(path).name, error=error.strerror or error)) from error
    return recipe_from_json(text)


def save_recipe(recipe, path):
    from .engine import PDFEngine
    recipe = validate_recipe(recipe)
    PDFEngine._atomic_write(path, (json.dumps(recipe, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return recipe


def recipes_dir():
    """Folder with the user's recipes, inside the folder the app already uses for its data."""
    from PySide6.QtCore import QStandardPaths
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / "recetas"


def _slug(name):
    keep = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
    return keep or "receta"


def save_user_recipe(recipe, folder=None):
    folder = Path(folder) if folder else recipes_dir()
    recipe = validate_recipe(recipe)
    path = folder / (_slug(recipe["name"]) + ".json")
    save_recipe(recipe, path)
    return path


def list_user_recipes(folder=None):
    """[(path, recipe)] of the valid recipes saved by the user; corrupt files are left out."""
    folder = Path(folder) if folder else recipes_dir()
    found = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            found.append((path, load_recipe(path)))
        except RecipeError:
            continue
    return found


PRESET_NAMES = (N_("Anonimizar y archivar"), N_("Escaneo a PDF buscable"), N_("Reducir y limpiar"))


def builtin_recipes():
    def build(name, *steps):
        return make_recipe(name, [{"step": key, "params": params} for key, params in steps])
    return [
        build(PRESET_NAMES[0], ("anonymize", {}), ("optimize", {"remove_metadata": True})),
        build(PRESET_NAMES[1], ("ocr", {"deskew": True}), ("optimize", {})),
        build(PRESET_NAMES[2], ("optimize", {}), ("sanitize", {})),
    ]


def needs_password(recipe):
    return any(item["step"] == "sign" for item in recipe["steps"])


# -------------------------------------------------------------------- report

@dataclass
class FileResult:
    source: str
    status: str
    output: str = ""
    message: str = ""
    seconds: float = 0.0

    def to_dict(self):
        return {"source": self.source, "status": self.status, "output": self.output, "message": self.message, "seconds": round(self.seconds, 2)}


@dataclass
class BatchReport:
    recipe: str = ""
    results: list = field(default_factory=list)
    cancelled: bool = False
    pending: int = 0

    def count(self, status):
        return sum(1 for r in self.results if r.status == status)

    @property
    def ok(self):
        return self.count(OK)

    @property
    def skipped(self):
        return self.count(SKIPPED)

    @property
    def errors(self):
        return self.count(ERROR)

    def to_dict(self):
        return {"recipe": self.recipe, "ok": self.ok, "skipped": self.skipped, "errors": self.errors, "cancelled": self.cancelled,
                "pending": self.pending, "files": [r.to_dict() for r in self.results]}

    def to_text(self):
        lines = []
        for r in self.results:
            name = Path(r.source).name
            if r.status == OK:
                lines.append(_("OK · {source} → {target}", source=name, target=Path(r.output).name))
            elif r.status == SKIPPED:
                lines.append(_("OMITIDO · {source}: {message}", source=name, message=r.message))
            elif r.status == CANCELLED_STATUS:
                lines.append(_("CANCELADO · {source}", source=name))
            else:
                lines.append(_("ERROR · {source}: {error}", source=name, error=r.message))
        lines.append(_("{ok} correctos, {skipped} omitidos, {errors} con error.", ok=self.ok, skipped=self.skipped, errors=self.errors)
                     + (_(" Cancelado: quedan {n} sin procesar.", n=self.pending) if self.cancelled else ""))
        return "\n".join(lines)


def write_report(report, folder):
    from .engine import PDFEngine
    path = Path(folder) / REPORT_NAME
    PDFEngine._atomic_write(path, (json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return path


# --------------------------------------------------------------------- engine

def collect_inputs(inputs, recursive=False, *, accept_images=False, exclude=None):
    """[(path, relative_folder)] for the files and folders given; relative_folder keeps subfolders of a folder input."""
    wanted = (".pdf",) + (IMAGE_SUFFIXES if accept_images else ())
    exclude = Path(exclude).resolve() if exclude else None
    found, seen = [], set()

    def add(path, relative, walked=False):
        resolved = path.resolve()
        if resolved in seen or (walked and exclude and exclude in resolved.parents):
            return
        seen.add(resolved)
        found.append((path, relative))

    for item in inputs:
        item = Path(item)
        if item.is_dir():
            walker = item.rglob("*") if recursive else item.glob("*")
            for path in sorted(walker):
                if path.is_file() and path.suffix.lower() in wanted:
                    add(path, path.parent.relative_to(item), True)
        else:
            add(item, Path("."))
    return found


def _unique(path):
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def _process_file(source, tmp, recipe, ctx):
    """Chain the steps through files in tmp; return the last one."""
    current = source
    for index, item in enumerate(recipe["steps"]):
        _check_cancel(ctx)
        step = STEPS[item["step"]]
        out = tmp / f"paso{index + 1}{step.extension}"
        step.run(current, out, item["params"], ctx)
        if not out.is_file():
            raise ValueError(_("El paso «{step}» no generó ningún archivo.", step=_(step.label)))
        current = out
    return current


def run_batch(inputs, output_dir, recipe, *, recursive=False, on_conflict="renombrar", progress=None, cancelled=None, password=None, on_result=None):
    """Apply ``recipe`` to every PDF in ``inputs`` (files and/or folders) writing into ``output_dir``.

    Originals are never modified. A failing file is reported and the next one goes on.
    ``progress(done, total, name)``, ``on_result(FileResult)`` and ``cancelled()`` are optional; cancelling stops between
    steps (or inside OCR) and leaves no partial output. Returns a BatchReport.
    """
    if on_conflict not in CONFLICT_MODES:
        raise ValueError(_("Modo de conflicto desconocido: «{mode}».", mode=on_conflict))
    recipe = validate_recipe(recipe)
    cancelled = cancelled or (lambda: False)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ctx = Context(password=password, cancelled=cancelled, progress=progress)
    last = STEPS[recipe["steps"][-1]["step"]]
    suffix = TEXT_SUFFIX if last.extension == ".txt" else OUTPUT_SUFFIX
    report = BatchReport(recipe=recipe["name"])

    def add(result):
        report.results.append(result)
        if on_result:
            on_result(result)

    inputs = [Path(i) for i in inputs]
    accept_images = recipe["steps"][0]["step"] == "ocr"
    files = collect_inputs(inputs, recursive, accept_images=accept_images, exclude=output_dir)
    # Explicit inputs that do not exist or are not PDFs are reported, not silently ignored.
    listed = {p.resolve() for p, _r in files}
    extras = [i for i in inputs if not i.is_dir() and i.resolve() not in listed]
    total = len(files)
    for bad in extras:
        add(FileResult(str(bad), ERROR, message=_("No existe el archivo.") if not bad.exists() else _("No es un PDF.")))
    claimed = set()
    for done, (source, relative) in enumerate(files):
        if cancelled():
            report.cancelled, report.pending = True, total - done
            break
        if progress:
            progress(done, total, source.name)
        started = time.monotonic()
        target = output_dir / relative / (source.stem + suffix + last.extension)
        tmp = None
        try:
            if target.resolve() == source.resolve():
                target = _unique(target)
            if (target.exists() or target in claimed) and on_conflict == "omitir":
                add(FileResult(str(source), SKIPPED, str(target), _("Ya existe {name}.", name=target.name)))
                continue
            if target in claimed or (target.exists() and on_conflict == "renombrar"):
                target = _unique(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(prefix=".lote-", dir=target.parent))
            result = _process_file(source, tmp, recipe, ctx)
            _check_cancel(ctx)
            os.replace(result, target)
            claimed.add(target)
            add(FileResult(str(source), OK, str(target), seconds=time.monotonic() - started))
        except InterruptedError:
            add(FileResult(str(source), CANCELLED_STATUS, seconds=time.monotonic() - started))
            report.cancelled, report.pending = True, total - done - 1
            break
        except Exception as error:
            add(FileResult(str(source), ERROR, message=_error_text(error), seconds=time.monotonic() - started))
        finally:
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)
    if progress and not report.cancelled:
        progress(total, total, "")
    return report


def _error_text(error):
    text = str(error)
    return text if text else type(error).__name__


# ----------------------------------------------------------------- watch mode

def watch(folder, recipe, output_dir, *, interval=5.0, stop=None, password=None, on_report=None):
    """Poll ``folder`` and process each new PDF once its size stops changing.

    The processed file is moved to ``folder/procesados``; files that fail stay where they are and
    are not retried until the watcher restarts. ``stop()`` ends the loop. Returns the cumulative report.
    """
    folder, output_dir = Path(folder), Path(output_dir)
    recipe = validate_recipe(recipe)
    stop = stop or (lambda: False)
    done_folder = folder / WATCH_DONE_FOLDER
    total = BatchReport(recipe=recipe["name"])
    sizes, failed = {}, set()
    while not stop():
        current = {}
        for path in sorted(folder.glob("*")):
            if path.is_file() and path.suffix.lower() == ".pdf" and path not in failed:
                try:
                    current[path] = path.stat().st_size
                except OSError:
                    continue
        ready = [p for p, size in current.items() if size > 0 and sizes.get(p) == size]
        sizes = current
        for path in ready:
            if stop():
                break
            part = run_batch([path], output_dir, recipe, on_conflict="renombrar", password=password)
            total.results.extend(part.results)
            if part.errors:
                failed.add(path)
            else:
                done_folder.mkdir(exist_ok=True)
                os.replace(path, _unique(done_folder / path.name))
            if on_report:
                on_report(part, total)
        slept = 0.0
        while slept < interval and not stop():
            time.sleep(min(0.1, interval))
            slept += 0.1
    return total


# ------------------------------------------------------------------------ CLI

USAGE = N_("Uso:\n  --batch RECETA.json --in CARPETA_O_ARCHIVO --out CARPETA [--recursive] [--on-conflict renombrar|omitir|sobrescribir]\n  --watch CARPETA_ENTRADA --recipe RECETA.json --out CARPETA")


def _say(text):
    stream = sys.stdout
    if stream is not None:
        try:
            try:
                stream.write(text + "\n")
            except UnicodeEncodeError:       # consola de Windows con página de códigos antigua
                encoding = getattr(stream, "encoding", None) or "ascii"
                stream.write((text + "\n").encode(encoding, "replace").decode(encoding, "replace"))
            stream.flush()
        except (OSError, ValueError):
            pass


def _usage_error(message):
    _say(_("Error: {message}", message=message))
    _say(_(USAGE))
    return 2


def cli_main(argv):
    """Run --batch / --watch without a window. Exit code: 0 all fine, 1 some file failed, 2 wrong usage."""
    import argparse

    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError(message)

    parser = Parser(add_help=False, prog="TrazoPDF")
    parser.add_argument("--batch")
    parser.add_argument("--watch")
    parser.add_argument("--recipe")
    parser.add_argument("--in", dest="source")
    parser.add_argument("--out")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--on-conflict", default="renombrar", choices=CONFLICT_MODES)
    parser.add_argument("--interval", type=float, default=5.0)
    try:
        args = parser.parse_args(argv)
    except ValueError as error:
        return _usage_error(str(error))
    except SystemExit:
        return 2
    if bool(args.batch) == bool(args.watch):
        return _usage_error(_("Usa --batch o --watch, no los dos."))
    recipe_path = args.batch or args.recipe
    if not recipe_path or not args.out or (args.batch and not args.source):
        return _usage_error(_("Faltan argumentos."))
    if args.interval <= 0:
        return _usage_error(_("El intervalo debe ser positivo."))
    try:
        recipe = load_recipe(recipe_path)
    except RecipeError as error:
        return _usage_error(str(error))
    password = None
    if needs_password(recipe):
        password = os.environ.get(PASSWORD_ENV)
        if password is None and sys.stdin is not None and sys.stdin.isatty():
            import getpass
            password = getpass.getpass(_("Contraseña del certificado: "))
        if password is None:
            return _usage_error(_("La receta firma con certificado: define la variable de entorno {name} con la contraseña.", name=PASSWORD_ENV))
    out = Path(args.out)
    if args.watch:
        folder = Path(args.watch)
        if not folder.is_dir():
            return _usage_error(_("No existe la carpeta vigilada: {path}", path=folder))
        out.mkdir(parents=True, exist_ok=True)
        _say(_("Vigilando {path}; pulsa Ctrl+C para parar.", path=folder))

        def on_report(part, total):
            _say(part.to_text())
            write_report(total, out)
        try:
            total = watch(folder, recipe, out, interval=args.interval, password=password, on_report=on_report)
        except KeyboardInterrupt:
            total = None
        if total is None:
            # Ctrl+C interrupted the loop: the results so far were already printed and written.
            try:
                saved = json.loads((out / REPORT_NAME).read_text(encoding="utf-8"))
                return 1 if saved.get("errors") else 0
            except (OSError, ValueError):
                return 0
        write_report(total, out)
        return 1 if total.errors else 0
    source = Path(args.source)
    if not source.exists():
        return _usage_error(_("No existe la entrada: {path}", path=source))
    try:
        report = run_batch([source], out, recipe, recursive=args.recursive, on_conflict=args.on_conflict, password=password)
    except ValueError as error:
        return _usage_error(str(error))
    if not report.results:
        return _usage_error(_("No se encontró ningún PDF en {path}.", path=source))
    write_report(report, out)
    _say(report.to_text())
    return 1 if report.errors else 0
