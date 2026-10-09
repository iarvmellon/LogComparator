# Version source: Git tags and generated build_info.json metadata.
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    & .\.venv\Scripts\python.exe .\create_release.py --update-build-info
    if ($LASTEXITCODE -ne 0) { throw 'Could not generate Git build metadata.' }
    & .\.venv\Scripts\pyinstaller.exe --onefile --name LogComparator --add-data "build_info.json;." main.py
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    Write-Output ('Executable ready: ' + (Join-Path $PSScriptRoot 'dist\LogComparator.exe'))
} finally {
    Pop-Location
}
