$envName = "masterresearch"
$conda = Get-Command conda -ErrorAction SilentlyContinue

if (-not $conda) {
    throw "Conda not found in PATH. Run this after installing Miniconda/Conda and opening a configured shell."
}

& conda run --no-capture-output -n $envName python @args
