[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $PSScriptRoot 'pdf-editor.iss'
$buildScript = Join-Path $projectRoot 'build.ps1'
$initPath = Join-Path $projectRoot 'pdf_editor\__init__.py'
$bundlePath = Join-Path $projectRoot 'dist\TrazoPDF'

# 1. Localizar ISCC.exe: variable de entorno, instalación para todos los usuarios o instalación por usuario.
$candidates = @()
if ($env:INNO_SETUP_ISCC) { $candidates += $env:INNO_SETUP_ISCC }
$candidates += Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
$candidates += Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'
$candidates += Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'

$iscc = $null
foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        $iscc = $candidate
        break
    }
}
if (-not $iscc) {
    Write-Error @'
No se encuentra ISCC.exe (Inno Setup 6).
Instala Inno Setup 6 desde https://jrsoftware.org/isinfo.php o indica la ruta con la variable
de entorno INNO_SETUP_ISCC, por ejemplo:
  $env:INNO_SETUP_ISCC = 'C:\Ruta\a\ISCC.exe'
No se ha creado el instalador. La aplicación compilada sigue disponible con .\build.ps1.
'@
    exit 1
}
Write-Host "Usando ISCC: $iscc"

# 2. Compilar la aplicación.
& $buildScript
if ($LASTEXITCODE -ne 0) { throw "build.ps1 terminó con el código $LASTEXITCODE." }
if (-not (Test-Path -LiteralPath (Join-Path $bundlePath 'TrazoPDF.exe') -PathType Leaf)) {
    throw "No se encuentra la aplicación compilada en $bundlePath."
}

# 3. Leer la versión desde el mismo origen que build.ps1.
$initText = Get-Content -LiteralPath $initPath -Raw -Encoding utf8
$versionMatch = [regex]::Match($initText, '__version__\s*=\s*["''](?<v>[^"'']+)["'']')
if (-not $versionMatch.Success) { throw 'No se encuentra __version__ en pdf_editor\__init__.py.' }
$version = $versionMatch.Groups['v'].Value

# 4. Compilar el instalador.
$numeric = [regex]::Match($version, '^\d+(\.\d+){0,3}').Value
$parts = @($numeric.Split('.') + @('0','0','0','0'))[0..3] -join '.'
& $iscc "/DMyAppVersion=$version" "/DMyAppVersionNumeric=$parts" "/DSourceDir=$bundlePath" $scriptPath
if ($LASTEXITCODE -ne 0) { throw "ISCC terminó con el código $LASTEXITCODE." }

$setupPath = Join-Path $PSScriptRoot "Output\TrazoPDF-$version-setup.exe"
Write-Host "Instalador creado: $setupPath"
