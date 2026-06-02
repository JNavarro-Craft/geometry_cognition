param (
    [string]$Configuration = "Debug",
    [switch]$Install = $true
)

$ErrorActionPreference = "Stop"

Write-Host "Iniciando compilacion de RhinoSAP [$Configuration]..." -ForegroundColor Cyan

if (-not (Get-Command "dotnet" -ErrorAction SilentlyContinue)) {
    Write-Error "No se encontró 'dotnet'. Instala el SDK de .NET."
    exit 1
}

$ProjectFile = "$PSScriptRoot\RhinoSAP.csproj"
$OutputDir = "$PSScriptRoot\bin\$Configuration\net48"
$GhaName = "RhinoSAP.gha"
$GhLibrariesPath = "$env:APPDATA\Grasshopper\Libraries"

Write-Host "Restaurando dependencias..." -ForegroundColor Yellow
dotnet restore $ProjectFile
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "Compilando solucion..." -ForegroundColor Yellow
dotnet build $ProjectFile -c $Configuration --no-restore
if ($LASTEXITCODE -ne 0) {
    Write-Error "Error de compilacion."
    exit 1
}

$DllPath = "$OutputDir\RhinoSAP.dll"
$GhaPath = "$OutputDir\$GhaName"
if (-not (Test-Path $DllPath)) {
    Write-Error "No se encontró RhinoSAP.dll en $OutputDir"
    exit 1
}

Copy-Item $DllPath $GhaPath -Force
Write-Host "GHA generado en: $GhaPath" -ForegroundColor Green

if ($Install) {
    Write-Host "Instalando en Grasshopper..." -ForegroundColor Yellow

    if (-not (Test-Path $GhLibrariesPath)) {
        New-Item -ItemType Directory -Path $GhLibrariesPath | Out-Null
    }

    try {
        Copy-Item $GhaPath "$GhLibrariesPath\$GhaName" -Force
        if (Test-Path "$OutputDir\RhinoSAP.pdb") {
            Copy-Item "$OutputDir\RhinoSAP.pdb" "$GhLibrariesPath\RhinoSAP.pdb" -Force
        }
        Write-Host "Plugin instalado en: $GhLibrariesPath\$GhaName"
        Write-Host "Reinicia Rhino para cargar la nueva versión."
    }
    catch {
        Write-Error "No se pudo copiar el archivo. ¿Rhino/Grasshopper están abiertos?"
    }
}
