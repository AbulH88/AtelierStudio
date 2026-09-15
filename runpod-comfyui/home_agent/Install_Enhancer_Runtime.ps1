param(
    [string]$Source = 'C:\Users\jimi\Desktop\DLSS.5.Visual.Enhancer.v9.0',
    [string]$Destination = 'C:\AtelierStudio\enhancer_runtime'
)

$sourcePath = (Resolve-Path -LiteralPath $Source -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath (Join-Path $sourcePath 'LICENSE')) -or
    -not (Test-Path -LiteralPath (Join-Path $sourcePath 'src')) -or
    -not (Test-Path -LiteralPath (Join-Path $sourcePath 'bin'))) {
    throw 'The selected source is not the tested DLSS Visual Enhancer package.'
}
if (Test-Path -LiteralPath $Destination) {
    throw "Destination exists; inspect it before reinstalling: $Destination"
}
$parent = Split-Path -Parent $Destination
New-Item -ItemType Directory -Path $parent -Force | Out-Null
New-Item -ItemType Directory -Path $Destination | Out-Null
Copy-Item -LiteralPath (Join-Path $sourcePath 'src') -Destination $Destination -Recurse
Copy-Item -LiteralPath (Join-Path $sourcePath 'bin') -Destination $Destination -Recurse
Copy-Item -LiteralPath (Join-Path $sourcePath 'LICENSE') -Destination $Destination
Write-Host "Installed local enhancer runtime at $Destination"
Write-Host 'RIFE uses the separately installed ComfyUI-Frame-Interpolation nodes and checkpoints.'
