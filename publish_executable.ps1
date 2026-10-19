# Publish only this project's staged EXE; leave the running app alone if build failed.
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'build\executable-stage\LogComparator.exe'
$target = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'dist\LogComparator.exe'))
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw 'The staged executable is missing. Run build_executable.ps1 first.'
}
[System.IO.Directory]::CreateDirectory((Split-Path -Parent $target)) | Out-Null
$temporary = Join-Path (Split-Path -Parent $target) ('.LogComparator-' + [guid]::NewGuid().ToString('N') + '.exe')
$backup = $temporary + '.previous'
$published = $false
try {
    Copy-Item -LiteralPath $source -Destination $temporary
    # One-file PyInstaller runs a parent and a child from the same path.
    $running = @(Get-Process -Name LogComparator -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $target })
    foreach ($process in $running) {
        try { Stop-Process -Id $process.Id -Force -ErrorAction Stop }
        catch {
            if (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) { throw }
        }
    }
    foreach ($process in $running) {
        if (-not $process.WaitForExit(10000)) { throw 'LogComparator did not stop in time.' }
    }
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            if ([System.IO.File]::Exists($target)) {
                [System.IO.File]::Replace($temporary, $target, $backup)
            } else {
                [System.IO.File]::Move($temporary, $target)
            }
            $published = $true
            Write-Output ('Executable published: ' + $target)
            break
        } catch [System.IO.IOException] {
            if ($attempt -eq 20) { throw }
            Start-Sleep -Milliseconds 250
        } catch [System.UnauthorizedAccessException] {
            if ($attempt -eq 20) { throw }
            Start-Sleep -Milliseconds 250
        }
    }
} finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
    if ($published -and (Test-Path -LiteralPath $backup)) {
        Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
    }
}
