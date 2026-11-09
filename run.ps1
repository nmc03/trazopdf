[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$applicationPath = Join-Path $projectRoot 'dist\TrazoPDF\TrazoPDF.exe'
if (-not (Test-Path -LiteralPath $applicationPath)) { $applicationPath = Join-Path $projectRoot 'dist-v0.3\TrazoPDF\TrazoPDF.exe' }
if (-not (Test-Path -LiteralPath $applicationPath)) { $applicationPath = Join-Path $projectRoot 'dist-v0.2\TrazoPDF\TrazoPDF.exe' }
$pythonWindowedPath = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'

if (Test-Path -LiteralPath $applicationPath -PathType Leaf) {
    Start-Process -FilePath $applicationPath -WorkingDirectory $projectRoot -WindowStyle Normal
    exit 0
}

if (Test-Path -LiteralPath $pythonWindowedPath -PathType Leaf) {
    Start-Process -FilePath $pythonWindowedPath -ArgumentList @('-m', 'pdf_editor') -WorkingDirectory $projectRoot -WindowStyle Normal
    exit 0
}

Write-Error @'
No se encuentra TrazoPDF compilado ni su entorno Python.
Desde esta carpeta, prepara el entorno con:
  py -3.13 -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
Luego vuelve a ejecutar .\run.ps1.
'@
