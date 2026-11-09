if __name__ == "__main__":
    try:
        from pdf_editor.app import main
        main()
    except Exception:
        import traceback
        from pathlib import Path
        Path("pdf-editor-startup-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
