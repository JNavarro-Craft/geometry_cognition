param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"

$projectPath = "rhino_bridge/plugin/RhinoPrefabGeometryPlugin.csproj"
$framework = "net48"
$assemblyName = "rhino_bridge"
$outputDll = "rhino_bridge/plugin/bin/$Configuration/$framework/$assemblyName.dll"
$distDir = "rhino_bridge/dist"
$outputRhp = "$distDir/$assemblyName.rhp"

Write-Host "Building Rhino plugin ($Configuration)..."
dotnet build $projectPath -c $Configuration

if (-not (Test-Path $outputDll)) {
    throw "Build succeeded but DLL not found: $outputDll"
}

if (-not (Test-Path $distDir)) {
    New-Item -ItemType Directory -Path $distDir | Out-Null
}

Copy-Item -Path $outputDll -Destination $outputRhp -Force
Write-Host "Generated: $outputRhp"
