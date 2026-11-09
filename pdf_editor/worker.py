"""Isolated process for long operations; the GUI keeps its own document intact."""
import json
from pathlib import Path

from .engine import PDFEngine
from .lang import _


def run_worker(request_file):
    request_file = Path(request_file)
    folder = request_file.parent
    result = {"ok": False}
    engine = PDFEngine()
    try:
        request = json.loads(request_file.read_text(encoding="utf-8"))
        engine.reject_dirs = [d for d in request.get("reject_dirs", []) if isinstance(d, str)]
        cancelled = lambda: (folder / "cancel").exists()
        if cancelled():
            raise InterruptedError(_("Operación cancelada."))
        if request["operation"] == "ocr":
            engine.open(folder / "source.pdf")
            def progress(done, total):
                engine._atomic_write(folder / "progress.json", json.dumps({"done": done, "total": total}).encode())
            engine.ocr(request.get("language", "spa+eng"), progress=progress, cancelled=cancelled, deskew=bool(request.get("deskew", False)))
        elif request["operation"] == "office":
            engine.convert_office(request["path"], cancelled=cancelled)
        elif request["operation"] == "compare":
            from .comparison import compare_documents
            def progress(done, total):
                engine._atomic_write(folder / "progress.json", json.dumps({"done": done, "total": total}).encode())
            result["report"] = compare_documents(folder / "source.pdf", request["path"], request["output_folder"],
                                                 progress=progress, cancelled=cancelled)
        elif request["operation"] == "optimize":
            engine.open(folder / "source.pdf")
            outcome = engine.optimize_preview(**request.get("options", {}))
            PDFEngine._atomic_write(folder / "output.pdf", outcome.pop("data"))
            result["report"] = outcome
        elif request["operation"] == "check":
            engine.open(folder / "source.pdf")
            result["report"] = engine.check_document()
        else:
            raise ValueError(_("Operación de procesamiento desconocida."))
        if cancelled():
            raise InterruptedError(_("Operación cancelada."))
        if request["operation"] not in ("compare", "optimize", "check"):
            engine.save(folder / "output.pdf", allow_pending_redactions=bool(request.get("allow_pending", False)))
        result["ok"] = True
    except InterruptedError:
        result["cancelled"] = True
    except Exception as error:
        result["error"] = str(error) or type(error).__name__
    finally:
        engine.close()
        PDFEngine._atomic_write(folder / "result.json", json.dumps(result).encode("utf-8"))
