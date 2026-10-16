param([int]$Port = 8080, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $webArgs = @('web_app.py', '--port', $Port)
    if ($NoBrowser) { $webArgs += '--no-browser' }
    & '.\.venv\Scripts\python.exe' @webArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
