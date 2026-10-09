param([string]$Python)

$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw 'Install Git for Windows and reopen PowerShell before running setup.'
    }
    $projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $projectPython)) {
        $launcherArgs = @()
        if ($Python) {
            $launcher = $Python
        } elseif (Get-Command py -ErrorAction SilentlyContinue) {
            $launcher = 'py'
            $launcherArgs = @('-3')
        } elseif (Get-Command python -ErrorAction SilentlyContinue) {
            $launcher = 'python'
        } else {
            throw 'Install Python 3.10 or newer with Tkinter, or specify -Python with its executable path.'
        }
        & $launcher @launcherArgs -c "import sys, tkinter; assert sys.version_info >= (3, 10), 'Python 3.10 or newer is required'"
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ with Tkinter is required.' }
        & $launcher @launcherArgs -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the project virtual environment.' }
    }
    & $projectPython -c "import sys, tkinter; assert sys.version_info >= (3, 10), 'Python 3.10 or newer is required'"
    if ($LASTEXITCODE -ne 0) { throw 'The project virtual environment requires Python 3.10+ with Tkinter.' }
    & $projectPython -m pip install -r requirements.txt -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Could not install project dependencies.' }
    & $projectPython create_release.py --update-build-info
    if ($LASTEXITCODE -ne 0) { throw 'Could not generate Git build metadata.' }
    . (Join-Path $PSScriptRoot '.venv\Scripts\Activate.ps1')
    Write-Output 'Setup complete. The project virtual environment is active. Run python main.py to start LogComparator.'
    Write-Output 'Run .\build_executable.ps1 to build the executable without publishing a release.'
} finally {
    Pop-Location
}
