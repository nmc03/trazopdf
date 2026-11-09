<#
.SYNOPSIS
  Descarga los modelos de Tesseract (tessdata_fast) que no se guardan en git.
.DESCRIPTION
  Descarga fra, deu, por y osd (orientación) a assets\tessdata y comprueba su suma SHA-256.
  spa y eng ya están en el repositorio. Si un archivo existe con la suma correcta no se vuelve a bajar.
  Origen: https://github.com/tesseract-ocr/tessdata_fast (rama main, licencia Apache 2.0).
  Para actualizar un modelo, cambia su suma aquí tras revisar el origen.
#>
[CmdletBinding()]
param([string]$Destination = (Join-Path (Split-Path -Parent $PSScriptRoot) 'assets\tessdata'))

$ErrorActionPreference = 'Stop'
$baseUrl = 'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main'
$models = [ordered]@{
    'fra' = 'ced037562e8c80c13122dece28dd477d399af80911a28791a66a63ac1e3445ca'
    'deu' = '19d219bbb6672c869d20a9636c6816a81eb9a71796cb93ebe0cb1530e2cdb22d'
    'por' = 'c4932b937207a9514b7514d518b931a99938c02a28a5a5a553f8599ed58b7deb'
    'osd' = '9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff'
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
foreach ($name in $models.Keys) {
    $target = Join-Path $Destination "$name.traineddata"
    $expected = $models[$name]
    if ((Test-Path -LiteralPath $target -PathType Leaf) -and ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -eq $expected)) {
        Write-Host "$name.traineddata ya está y es correcto."
        continue
    }
    $partial = "$target.part"
    Write-Host "Descargando $name.traineddata ..."
    Invoke-WebRequest -Uri "$baseUrl/$name.traineddata" -OutFile $partial -UseBasicParsing
    $actual = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        Remove-Item -LiteralPath $partial -Force
        throw "La suma SHA-256 de $name.traineddata no coincide (esperada $expected, obtenida $actual). No se ha instalado."
    }
    Move-Item -LiteralPath $partial -Destination $target -Force
}
Write-Host 'Modelos listos en' $Destination
