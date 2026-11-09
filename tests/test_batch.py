"""Recipes and batch processing: chain of steps, conflicts, cancel, CLI and watch mode."""
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pymupdf as fitz
import pytest

from pdf_editor import batch

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def make_pdf(path, text="Contacto 12345678Z y maria@example.com", pages=1):
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 100), f"{text} p{i}")
    doc.set_metadata({"author": "Autora"})
    doc.save(str(path))
    doc.close()
    return Path(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def three_step():
    return batch.make_recipe("tres", [{"step": "anonymize", "params": {}}, {"step": "optimize", "params": {}}, {"step": "sanitize", "params": {}}])


def cli(*args, **kw):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([PY, "-m", "pdf_editor", *map(str, args)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, env=env, **kw)


def test_three_steps_one_corrupt_file(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    good = [make_pdf(src / "a.pdf"), make_pdf(src / "b.pdf")]
    (src / "c.pdf").write_bytes(b"esto no es un pdf")
    before = {p.name: digest(p) for p in src.iterdir()}
    out = tmp_path / "out"
    report = batch.run_batch([src], out, three_step())
    assert (report.ok, report.errors, report.skipped) == (2, 1, 0)
    bad = [r for r in report.results if r.status == batch.ERROR]
    assert Path(bad[0].source).name == "c.pdf" and bad[0].message
    assert sorted(p.name for p in out.iterdir()) == ["a_procesado.pdf", "b_procesado.pdf"], "sin temporales"
    for p in out.iterdir():
        with fitz.open(str(p)) as doc:
            assert "12345678Z" not in doc[0].get_text() and "maria@example.com" not in doc[0].get_text()
    assert before == {p.name: digest(p) for p in src.iterdir()}, "originales intactos"
    data = report.to_dict()
    assert data["ok"] == 2 and data["errors"] == 1 and len(data["files"]) == 3
    assert "ERROR" in report.to_text() and good[0].exists()


def test_on_conflict_modes(tmp_path):
    src = make_pdf(tmp_path / "a.pdf")
    out = tmp_path / "out"
    recipe = batch.make_recipe("r", [{"step": "number_pages", "params": {}}])
    batch.run_batch([src], out, recipe)
    first = out / "a_procesado.pdf"
    mark = first.read_bytes()
    first.write_bytes(b"VIEJO")
    skipped = batch.run_batch([src], out, recipe, on_conflict="omitir")
    assert skipped.skipped == 1 and first.read_bytes() == b"VIEJO"
    renamed = batch.run_batch([src], out, recipe, on_conflict="renombrar")
    assert renamed.ok == 1 and first.read_bytes() == b"VIEJO" and (out / "a_procesado (2).pdf").is_file()
    over = batch.run_batch([src], out, recipe, on_conflict="sobrescribir")
    assert over.ok == 1 and first.read_bytes() != b"VIEJO" and fitz.open(str(first)).page_count == 1 and mark
    with pytest.raises(ValueError):
        batch.run_batch([src], out, recipe, on_conflict="otro")


def test_output_in_input_folder_never_overwrites_original(tmp_path):
    src = make_pdf(tmp_path / "a.pdf")
    before = digest(src)
    report = batch.run_batch([src], tmp_path, batch.make_recipe("r", [{"step": "rotate", "params": {}}]), on_conflict="sobrescribir")
    assert report.ok == 1 and digest(src) == before


def test_recursive_keeps_subfolders(tmp_path):
    src = tmp_path / "in"
    (src / "sub").mkdir(parents=True)
    make_pdf(src / "a.pdf")
    make_pdf(src / "sub" / "b.pdf")
    recipe = batch.make_recipe("r", [{"step": "rotate", "params": {"angle": 180}}])
    assert batch.run_batch([src], tmp_path / "o1", recipe).ok == 1
    deep = batch.run_batch([src], tmp_path / "o2", recipe, recursive=True)
    assert deep.ok == 2 and (tmp_path / "o2" / "sub" / "b_procesado.pdf").is_file()
    with fitz.open(str(tmp_path / "o2" / "a_procesado.pdf")) as doc:
        assert doc[0].rotation == 180


def test_other_steps_and_export_text(tmp_path):
    src = make_pdf(tmp_path / "a.pdf", pages=2)
    recipe = batch.make_recipe("varios", [
        {"step": "watermark", "params": {"text": "BORRADOR"}}, {"step": "bates", "params": {"prefix": "X-"}},
        {"step": "number_pages", "params": {}}, {"step": "crop", "params": {"left": 10, "top": 10, "right": 10, "bottom": 10}},
        {"step": "export_text", "params": {}}])
    report = batch.run_batch([src], tmp_path / "o", recipe)
    assert report.ok == 1, report.to_text()
    text = Path(report.results[0].output).read_text(encoding="utf-8")
    assert report.results[0].output.endswith("_texto.txt") and "BORRADOR" in text and "X-000001" in text
    fail = batch.run_batch([src], tmp_path / "o2", batch.make_recipe("c", [{"step": "crop", "params": {"left": 1000, "right": 1000}}]))
    assert fail.errors == 1


def test_bad_recipes_give_clear_errors(tmp_path):
    corrupt = tmp_path / "r.json"
    corrupt.write_text("{no es json", encoding="utf-8")
    with pytest.raises(batch.RecipeError, match="dañada"):
        batch.load_recipe(corrupt)
    with pytest.raises(batch.RecipeError, match="Paso desconocido: «teletransportar»"):
        batch.validate_recipe({"version": 1, "steps": [{"step": "teletransportar"}]})
    with pytest.raises(batch.RecipeError, match="versión"):
        batch.validate_recipe({"version": 99, "steps": [{"step": "sanitize"}]})
    with pytest.raises(batch.RecipeError):
        batch.validate_recipe({"version": 1, "steps": []})
    with pytest.raises(batch.RecipeError, match="Valor no válido"):
        batch.validate_recipe({"version": 1, "steps": [{"step": "rotate", "params": {"angle": 45}}]})
    with pytest.raises(batch.RecipeError, match="último"):
        batch.validate_recipe({"version": 1, "steps": [{"step": "export_text"}, {"step": "optimize"}]})
    with pytest.raises(batch.RecipeError):
        batch.load_recipe(tmp_path / "no-existe.json")


def test_save_load_roundtrip_and_presets(tmp_path):
    names = [r["name"] for r in batch.builtin_recipes()]
    assert names == ["Anonimizar y archivar", "Escaneo a PDF buscable", "Reducir y limpiar"]
    recipe = three_step()
    path = batch.save_user_recipe(recipe, tmp_path / "recetas")
    assert batch.load_recipe(path) == recipe
    (tmp_path / "recetas" / "rota.json").write_text("[]")
    assert [r["name"] for _p, r in batch.list_user_recipes(tmp_path / "recetas")] == ["tres"]


def test_signing_password_never_in_recipe(tmp_path):
    recipe = batch.make_recipe("firma", [{"step": "sign", "params": {"p12": "/x/cert.p12", "reason": "ok"}}])
    path = tmp_path / "f.json"
    batch.save_recipe(recipe, path)
    assert "secreto" not in path.read_text() and "password" not in path.read_text().lower()
    assert batch.needs_password(recipe)
    with pytest.raises(batch.RecipeError, match="contraseñas"):
        batch.validate_recipe({"version": 1, "steps": [{"step": "sign", "params": {"password": "secreto"}}]})
    src = make_pdf(tmp_path / "a.pdf")
    assert batch.run_batch([src], tmp_path / "o", recipe).errors == 1, "sin contraseña no firma"


def test_sign_step_with_certificate(tmp_path):
    from tests.test_signing_visible import make_pfx
    from pdf_editor import signing
    pfx = make_pfx(tmp_path, "Alicia", "a.p12")
    src = make_pdf(tmp_path / "a.pdf")
    recipe = batch.make_recipe("firma", [{"step": "rotate", "params": {}}, {"step": "sign", "params": {"p12": str(pfx), "reason": "prueba"}}])
    report = batch.run_batch([src], tmp_path / "o", recipe, password="pw")
    assert report.ok == 1, report.to_text()
    assert len(signing.validate_file(report.results[0].output)) == 1
    wrong = batch.run_batch([src], tmp_path / "o2", recipe, password="mal")
    assert wrong.errors == 1 and not list((tmp_path / "o2").glob("*.pdf"))
    saved = batch.save_user_recipe(recipe, tmp_path / "r")
    assert "pw" not in saved.read_text() or "pw" not in json.loads(saved.read_text())["steps"][1]["params"].values()


def test_cancel_midway_leaves_no_partial_files(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    for n in "abc":
        make_pdf(src / f"{n}.pdf")
    state = {"calls": 0}

    def cancelled():
        state["calls"] += 1
        return state["calls"] > 7   # during the second file

    out = tmp_path / "out"
    report = batch.run_batch([src], out, three_step(), cancelled=cancelled)
    assert report.cancelled and report.pending >= 1 and report.ok == 1
    assert [p.name for p in out.iterdir()] == ["a_procesado.pdf"], "sin parciales ni temporales"
    assert all(Path(r.output).exists() for r in report.results if r.status == batch.OK)


def test_progress_is_reported(tmp_path):
    for n in "ab":
        make_pdf(tmp_path / f"{n}.pdf")
    ticks = []
    batch.run_batch([tmp_path / "a.pdf", tmp_path / "b.pdf"], tmp_path / "o", batch.make_recipe("r", [{"step": "rotate", "params": {}}]), progress=lambda d, t, n: ticks.append((d, t, n)))
    assert ticks[0][:2] == (0, 2) and ticks[-1][:2] == (2, 2)


def test_cli_exit_codes(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    make_pdf(src / "a.pdf")
    recipe = tmp_path / "r.json"
    batch.save_recipe(batch.make_recipe("r", [{"step": "optimize", "params": {}}]), recipe)
    out = tmp_path / "out"
    done = cli("--batch", recipe, "--in", src, "--out", out)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "OK" in done.stdout and (out / "a_procesado.pdf").is_file()
    assert json.loads((out / "batch-report.json").read_text())["ok"] == 1
    skipped = cli("--batch", recipe, "--in", src, "--out", out, "--on-conflict", "omitir")
    assert skipped.returncode == 0 and "OMITIDO" in skipped.stdout
    (src / "mala.pdf").write_bytes(b"basura")
    failed = cli("--batch", recipe, "--in", src, "--out", tmp_path / "out2")
    assert failed.returncode == 1 and "ERROR" in failed.stdout
    assert cli("--batch", recipe, "--out", out).returncode == 2
    assert cli("--batch", tmp_path / "nada.json", "--in", src, "--out", out).returncode == 2
    assert cli("--batch", recipe, "--in", src, "--out", out, "--on-conflict", "borrar").returncode == 2
    assert cli("--batch", recipe, "--watch", src, "--out", out).returncode == 2
    assert cli("--batch", recipe, "--in", tmp_path / "no", "--out", out).returncode == 2


def test_watch_function_processes_new_pdf(tmp_path):
    inbox = tmp_path / "in"
    inbox.mkdir()
    out = tmp_path / "out"
    recipe = batch.make_recipe("r", [{"step": "rotate", "params": {}}])
    seen = []
    import threading
    stop = threading.Event()
    thread = threading.Thread(target=lambda: seen.append(batch.watch(inbox, recipe, out, interval=0.1, stop=stop.is_set)))
    thread.start()
    try:
        make_pdf(inbox / "nuevo.pdf")
        deadline = time.time() + 20
        while time.time() < deadline and not (inbox / "procesados" / "nuevo.pdf").exists():
            time.sleep(0.1)
    finally:
        stop.set()
        thread.join(10)
    assert (inbox / "procesados" / "nuevo.pdf").is_file() and not (inbox / "nuevo.pdf").exists()
    assert (out / "nuevo_procesado.pdf").is_file() and seen[0].ok == 1


def test_cli_watch_processes_and_stops_on_interrupt(tmp_path):
    inbox = tmp_path / "in"
    inbox.mkdir()
    out = tmp_path / "out"
    recipe = tmp_path / "r.json"
    batch.save_recipe(batch.make_recipe("r", [{"step": "rotate", "params": {}}]), recipe)
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen([PY, "-m", "pdf_editor", "--watch", str(inbox), "--recipe", str(recipe), "--out", str(out), "--interval", "0.3"],
                            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env)
    try:
        make_pdf(inbox / "x.pdf")
        deadline = time.time() + 60
        while time.time() < deadline and not (out / "batch-report.json").exists():
            time.sleep(0.2)
        assert (inbox / "procesados" / "x.pdf").exists() or (out / "x_procesado.pdf").exists()
        if sys.platform == "win32":      # Windows no admite SIGINT en Popen: se termina el proceso
            proc.terminate()
            stdout, _err = proc.communicate(timeout=30)
            assert (out / "x_procesado.pdf").is_file()
            return
        proc.send_signal(signal.SIGINT)
        stdout, _err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0, stdout
    assert (out / "x_procesado.pdf").is_file() and json.loads((out / "batch-report.json").read_text())["ok"] == 1


def test_batch_module_makes_no_network_calls(tmp_path, monkeypatch):
    import socket

    def refuse(*a, **k):
        raise AssertionError("no debe usar la red")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    src = make_pdf(tmp_path / "a.pdf")
    assert batch.run_batch([src], tmp_path / "o", three_step()).ok == 1
    source = Path(batch.__file__).read_text(encoding="utf-8")
    assert "urllib" not in source and "requests" not in source and "http" not in source.replace("https://", "")


# --- dialog -----------------------------------------------------------------

@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_runs_a_preset_and_saves_recipes(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from pdf_editor.batch_dialog import BatchDialog
    src = make_pdf(tmp_path / "a.pdf")
    dialog = BatchDialog(None, recipes_folder=tmp_path / "recetas")
    names = [dialog.recipe_combo.itemText(i) for i in range(dialog.recipe_combo.count())]
    assert "Reducir y limpiar" in names and "Anonimizar y archivar" in names
    dialog.recipe_combo.setCurrentIndex(names.index("Reducir y limpiar"))
    assert dialog.steps_list.count() == 2
    dialog.move_step(1) if dialog.steps_list.setCurrentRow(1) is None else None
    assert [s["step"] for s in dialog.steps] == ["optimize", "sanitize"]
    dialog.steps_list.setCurrentRow(1)
    dialog.move_step(-1)
    assert [s["step"] for s in dialog.steps] == ["sanitize", "optimize"]
    dialog.remove_step()
    dialog.add_step.__self__  # steps API stays usable
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Mi receta", True)))
    dialog.save_recipe()
    assert [r["name"] for _p, r in batch.list_user_recipes(tmp_path / "recetas")] == ["Mi receta"]
    assert dialog.current_name() == "Mi receta"
    dialog.add_inputs([str(src)])
    dialog.output.setText(str(tmp_path / "out"))
    dialog.start()
    dialog.thread.wait(60000)
    qapp.processEvents()
    assert dialog.table.rowCount() == 1 and dialog.table.item(0, 1).text() == "Correcto"
    assert (tmp_path / "out" / "a_procesado.pdf").is_file()
    dialog.close()
    dialog.deleteLater()
    from PySide6.QtCore import QEvent
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
