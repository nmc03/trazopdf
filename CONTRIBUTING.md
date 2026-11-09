# Cómo contribuir

Gracias por tu interés en TrazoPDF. Las contribuciones son bienvenidas: informes de errores, mejoras de documentación, traducciones y cambios de código.

## Antes de empezar

- Para un cambio grande, abre primero un issue para comentar el enfoque.
- Para vulnerabilidades, no abras un issue público: sigue [SECURITY.md](SECURITY.md).
- Participar implica respetar el [código de conducta](CODE_OF_CONDUCT.md).

## Preparar el entorno

Necesitas Windows 10 u 11 y Python 3.13.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pdf_editor
```

Tesseract y LibreOffice son opcionales; solo hacen falta para probar OCR y la conversión de Office.

## Pruebas

Las pruebas usan la plataforma `offscreen` de Qt, así que no abren ventanas visibles:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
```

Si un cambio modifica el comportamiento, añade o ajusta una prueba en el módulo correspondiente de `tests/`. Todas las pruebas deben pasar antes de abrir un pull request.

## Estilo de código

- Python con nombres, comentarios y mensajes de la interfaz en español cuando afectan al usuario.
- Sigue el estilo existente del módulo que modificas. No reformatees archivos completos en un cambio no relacionado.
- Evita dependencias nuevas salvo que sean necesarias; si las añades, indica su licencia en la descripción del cambio y en [THIRD-PARTY.md](THIRD-PARTY.md).
- Las operaciones largas deben ejecutarse fuera del hilo de la interfaz.

## Commits y pull requests

- Mensajes de commit breves, en imperativo o en presente, describiendo qué cambia y por qué.
- Un pull request por tema. Describe el problema, la solución y cómo lo has probado.
- Indica si el cambio afecta a la compilación, a los instaladores o a la documentación pública.

## Licencia de las contribuciones

TrazoPDF se publica bajo AGPL-3.0-or-later. Al enviar una contribución aceptas publicarla con esa misma licencia.
