# Builds the portable folder dist\Cleaner: Cleaner.exe + _internal\ + ai\ (model and llama.cpp runtimes).
# The model and runtimes are taken from ..\rizzo-flow (downloaded there by `rizzo download`):
# hard links when on the same drive (no extra space), copies otherwise.
param(
    [string]$RizzoDir = (Join-Path $PSScriptRoot "..\rizzo-flow"),
    [switch]$NoAi
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

uv sync --locked
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

& .venv\Scripts\pyinstaller.exe --noconfirm --clean cleaner.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$dist = Join-Path $PSScriptRoot "dist\Cleaner"
if ($NoAi) { Write-Host "Build senza modello: $dist"; exit 0 }

$rizzo = (Resolve-Path $RizzoDir).Path
$gguf = Join-Path $rizzo "models\Spark-X2.5-4B-GGUF\Spark-X2.5-4B-Q8_0.gguf"
if (-not (Test-Path $gguf)) { throw "Modello non trovato: $gguf (esegui 'uv run rizzo download' in rizzo-flow)" }

function Link-Or-Copy($source, $target) {
    New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
    if (Test-Path $target) { Remove-Item $target -Force }
    try { New-Item -ItemType HardLink -Path $target -Target $source | Out-Null }
    catch { Copy-Item $source $target }
}

$ai = Join-Path $dist "ai"
Link-Or-Copy $gguf (Join-Path $ai "models\Spark-X2.5-4B-GGUF\Spark-X2.5-4B-Q8_0.gguf")
Get-ChildItem (Join-Path $rizzo "runtimes") -Directory -Filter "llama-*" | ForEach-Object {
    $runtime = $_
    Get-ChildItem $runtime.FullName -File -Recurse | ForEach-Object {
        $relative = $_.FullName.Substring($runtime.FullName.Length + 1)
        Link-Or-Copy $_.FullName (Join-Path $ai "runtimes\$($runtime.Name)\$relative")
    }
}
Copy-Item (Join-Path $rizzo "LICENSE") (Join-Path $ai "LICENSE-rizzo-flow.txt") -Force
Copy-Item (Join-Path $rizzo "NOTICE") (Join-Path $ai "NOTICE-rizzo-flow.txt") -Force
Copy-Item (Join-Path $PSScriptRoot "LEGGIMI.txt") (Join-Path $dist "LEGGIMI.txt") -Force
Copy-Item (Join-Path $PSScriptRoot "LICENSE") (Join-Path $dist "LICENSE.txt") -Force
Copy-Item (Join-Path $PSScriptRoot "NOTICE") (Join-Path $dist "NOTICE.txt") -Force

$size = (Get-ChildItem $dist -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
Write-Host ("Cartella portable pronta: {0} ({1:N1} GB)" -f $dist, $size)
