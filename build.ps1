[CmdletBinding()]
param([string]$OutputDirectory = 'dist', [switch]$SkipTesseract)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$entryPath = Join-Path $projectRoot 'main.py'
$iconPath = Join-Path $projectRoot 'assets\pdf-editor.ico'
$assetsPath = Join-Path $projectRoot 'assets'
$licensePath = Join-Path $projectRoot 'LICENSE'
$thirdPartyPath = Join-Path $projectRoot 'THIRD-PARTY.md'
$initPath = Join-Path $projectRoot 'pdf_editor\__init__.py'
$originalBuildPath = $env:PATH
$fetchTessdata = Join-Path $projectRoot 'tools\fetch_tessdata.ps1'

# The version is the single __version__ string in pdf_editor/__init__.py.
$initText = Get-Content -LiteralPath $initPath -Raw -Encoding utf8
$versionMatch = [regex]::Match($initText, '__version__\s*=\s*["''](?<v>[^"'']+)["'']')
if (-not $versionMatch.Success) {
    throw 'No se encuentra __version__ en pdf_editor\__init__.py.'
}
$version = $versionMatch.Groups['v'].Value

$resolvedOutput = [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDirectory))
if (-not $resolvedOutput.StartsWith($projectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'La carpeta de compilación debe estar dentro del proyecto.'
}

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'Falta .venv\Scripts\python.exe. Prepara el entorno siguiendo README.md.'
}
foreach ($required in @($entryPath, $licensePath, $thirdPartyPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Falta el archivo necesario: $required"
    }
}

# OCR 100 % local: se incluye Tesseract (carpeta 'tesseract' junto a la aplicación).
# Se busca en PDFEDITOR_TESSERACT (tesseract.exe o su carpeta) o en Program Files\Tesseract-OCR.
# Si no está, la compilación falla con un mensaje claro; -SkipTesseract continúa sin él (con aviso).
$tesseractExe = $null
if (-not $SkipTesseract) {
    $tesseractCandidates = @()
    if ($env:PDFEDITOR_TESSERACT) {
        $tesseractCandidates += $env:PDFEDITOR_TESSERACT
        $tesseractCandidates += Join-Path $env:PDFEDITOR_TESSERACT 'tesseract.exe'
    }
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432)) {
        if ($base) { $tesseractCandidates += Join-Path $base 'Tesseract-OCR\tesseract.exe' }
    }
    foreach ($candidate in $tesseractCandidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf) -and ([IO.Path]::GetFileName($candidate) -ieq 'tesseract.exe')) {
            $tesseractExe = (Resolve-Path -LiteralPath $candidate).Path
            break
        }
    }
    if (-not $tesseractExe) {
        throw 'No se encuentra tesseract.exe. Instálalo (https://github.com/UB-Mannheim/tesseract/wiki) o indica su ruta en PDFEDITOR_TESSERACT. Para compilar sin OCR integrado usa: .\build.ps1 -SkipTesseract'
    }
    Write-Host "Tesseract que se incluirá: $tesseractExe"
}
else {
    Write-Warning 'Se compila SIN Tesseract: el OCR dependerá de una instalación externa.'
}

# Modelos de idioma (fra, deu, por, osd) que no viven en git: se descargan con suma SHA-256.
$tessdataFolder = Join-Path $projectRoot 'assets\tessdata'
foreach ($model in @('spa', 'eng', 'fra', 'deu', 'por', 'osd')) {
    if (-not (Test-Path -LiteralPath (Join-Path $tessdataFolder "$model.traineddata") -PathType Leaf)) {
        Write-Host "Falta $model.traineddata; ejecutando tools\fetch_tessdata.ps1 ..."
        & $fetchTessdata
        break
    }
}

Push-Location -LiteralPath $projectRoot
try {
    # Avoid collecting incompatible ICU/UCRT DLLs from other bundled tools.
    # Qt uses the ICU implementation supplied by Windows 10/11.
    $env:PATH = @((Join-Path $projectRoot '.venv\Scripts'), (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) -join ';'
    Write-Host "Compilando TrazoPDF $version en $OutputDirectory ..."
    # PyInstaller logs to stderr; in Windows PowerShell 5.1 that becomes a
    # terminating NativeCommandError under 'Stop', so relax it for this call.
    $ErrorActionPreference = 'Continue'
    & $pythonPath -m PyInstaller --noconfirm --clean --windowed --log-level WARN --name 'TrazoPDF' --onedir --distpath $OutputDirectory --icon $iconPath --add-data "$assetsPath;assets" --add-data "$licensePath;." --add-data "$thirdPartyPath;." --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets $entryPath 2>&1 | ForEach-Object { "$_" }
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller terminó con el código $LASTEXITCODE."
    }

    $bundlePath = Join-Path $resolvedOutput 'TrazoPDF'
    $exePath = Join-Path $bundlePath 'TrazoPDF.exe'
    if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
        throw "No se ha generado el ejecutable esperado: $exePath"
    }

    if ($tesseractExe) {
        $tesseractTarget = Join-Path $bundlePath 'tesseract'
        New-Item -ItemType Directory -Force -Path $tesseractTarget | Out-Null
        $tesseractSource = Split-Path -Parent $tesseractExe
        Copy-Item -LiteralPath $tesseractExe -Destination $tesseractTarget -Force
        Get-ChildItem -LiteralPath $tesseractSource -Filter '*.dll' -File | Copy-Item -Destination $tesseractTarget -Force
        foreach ($notice in @('LICENSE', 'AUTHORS', 'README.md')) {
            $noticePath = Join-Path $tesseractSource $notice
            if (Test-Path -LiteralPath $noticePath -PathType Leaf) { Copy-Item -LiteralPath $noticePath -Destination (Join-Path $tesseractTarget "TESSERACT-$notice") -Force }
        }
        if (-not (Test-Path -LiteralPath (Join-Path $tesseractTarget 'tesseract.exe') -PathType Leaf)) {
            throw 'No se pudo copiar tesseract.exe al paquete.'
        }
        Write-Host "Tesseract incluido en: $tesseractTarget"
    }

    # Checksums for every file in the bundle, relative to the output folder.
    $checksumPath = Join-Path $resolvedOutput 'SHA256SUMS.txt'
    $lines = Get-ChildItem -LiteralPath $bundlePath -Recurse -File |
        Sort-Object FullName |
        ForEach-Object {
            $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            $relative = $_.FullName.Substring($resolvedOutput.Length + 1).Replace('\', '/')
            "$hash  $relative"
        }
    [IO.File]::WriteAllText($checksumPath, (($lines -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))

    Write-Host "Aplicación creada: $exePath"
    Write-Host "Sumas SHA-256: $checksumPath"
}
finally {
    $env:PATH = $originalBuildPath
    Pop-Location
}
