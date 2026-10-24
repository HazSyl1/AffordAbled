param(
    [switch]$Live,
    [switch]$LiveOnly,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$apiRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $apiRoot ".venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
$arguments = @("scripts/run_agent_evaluations.py")

if ($Live) {
    $arguments += "--live"
}
if ($LiveOnly) {
    $arguments += "--live-only"
}
if ($Verbose) {
    $arguments += "--verbose"
}

Push-Location $apiRoot
try {
    & $python @arguments
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $exitCode
