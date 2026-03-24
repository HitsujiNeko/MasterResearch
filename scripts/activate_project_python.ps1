$projectRoot = Split-Path -Parent $PSScriptRoot
$venvScripts = Join-Path $projectRoot ".venv\Scripts"

if (-not (Test-Path (Join-Path $venvScripts "python.exe"))) {
    throw "Project Python not found: $venvScripts\\python.exe"
}

$env:PATH = "$venvScripts;$env:PATH"
Set-Alias -Name python -Value (Join-Path $venvScripts "python.exe") -Scope Global
Set-Alias -Name pip -Value (Join-Path $venvScripts "pip.exe") -Scope Global

Write-Host "Project Python activated for this PowerShell session."
Write-Host "python -> $(Join-Path $venvScripts 'python.exe')"
