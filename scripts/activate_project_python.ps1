$envName = "masterresearch"
$conda = Get-Command conda -ErrorAction SilentlyContinue

if (-not $conda) {
    throw "Conda not found in PATH. Run this after installing Miniconda/Conda and opening a configured shell."
}

$hook = (& conda shell.powershell hook) | Out-String
Invoke-Expression $hook
conda activate $envName

if ($LASTEXITCODE -ne 0) {
    throw "Failed to activate conda environment: $envName"
}

$python = Get-Command python -ErrorAction SilentlyContinue
Write-Host "Conda environment activated for this PowerShell session."
if ($python) {
    Write-Host "python -> $($python.Source)"
}
