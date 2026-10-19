# Version source: Git tags and generated build_info.json metadata.
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    # PyInstaller logs progress to stderr; PowerShell 5 must use its exit code,
    # rather than treating redirected informational output as a fatal error.
    $ErrorActionPreference = 'Continue'
    try {
        & .\.venv\Scripts\python.exe .\create_release.py --build-only
        $buildExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = 'Stop'
    }
    if ($buildExitCode -ne 0) { throw 'Executable build failed.' }
    Write-Output ('Executable ready: ' + (Join-Path $PSScriptRoot 'dist\LogComparator.exe'))
} finally {
    Pop-Location
}
