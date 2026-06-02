# Script temporal para instalar el plugin RhinoSAP
$sourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ghaPath = Join-Path $sourceDir "bin\Debug\net48\RhinoSAP.gha"
$pdbPath = Join-Path $sourceDir "bin\Debug\net48\RhinoSAP.pdb"
$destDir = "$env:APPDATA\Grasshopper\Libraries"

Write-Host "Instalando plugin RhinoSAP..." -ForegroundColor Cyan
Write-Host "Origen GHA: $ghaPath" -ForegroundColor Yellow
Write-Host "Destino: $destDir" -ForegroundColor Yellow

if (-not (Test-Path $ghaPath)) {
    Write-Error "No se encontró el archivo GHA en $ghaPath"
    exit 1
}

if (-not (Test-Path $destDir)) {
    New-Item -ItemType Directory -Path $destDir | Out-Null
}

try {
    Copy-Item $ghaPath $destDir -Force
    if (Test-Path $pdbPath) {
        Copy-Item $pdbPath $destDir -Force
    }
    Write-Host "Plugin instalado exitosamente en $destDir" -ForegroundColor Green
    Write-Host "Reinicia Rhino para cargar el plugin." -ForegroundColor Green
} catch {
    Write-Error "Error al instalar el plugin: $_"
}

