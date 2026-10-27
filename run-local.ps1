# Run this workspace without changing the caller's working directory or environment.
$ErrorActionPreference = 'Stop'
$taskPython = $env:SCRAPING_PYTHON
if (-not $taskPython) {
    $localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $localPython) {
        $taskPython = $localPython
    } elseif (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.runtime.json') -PathType Leaf) {
        $taskRuntime = Get-Content -LiteralPath (Join-Path $PSScriptRoot '.runtime.json') -Raw | ConvertFrom-Json
        if (-not $taskRuntime.python -or -not [IO.Path]::IsPathRooted([string]$taskRuntime.python)) {
            throw '.runtime.json must contain an absolute Python path in its python field.'
        }
        $taskPython = [string]$taskRuntime.python
    } elseif ($env:CONDA_PREFIX -and (Test-Path -LiteralPath (Join-Path $env:CONDA_PREFIX 'python.exe') -PathType Leaf)) {
        $taskPython = Join-Path $env:CONDA_PREFIX 'python.exe'
    } else {
        $pythonCommand = Get-Command python -CommandType Application -ErrorAction SilentlyContinue
        if (-not $pythonCommand) {
            throw 'Python not found. Set SCRAPING_PYTHON to your Python 3.10+ executable.'
        }
        $taskPython = $pythonCommand.Source
        if ($taskPython -match '[\\/]Microsoft[\\/]WindowsApps[\\/]python[^\\/]*\.exe$') {
            throw 'Only the Windows Python app alias was found. Set SCRAPING_PYTHON or .runtime.json to an installed Python executable.'
        }
    }
}
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) {
    throw "Python does not exist: $taskPython"
}
$taskPython = (Resolve-Path -LiteralPath $taskPython).Path
$taskPrefix = Split-Path -Parent $taskPython
$previousPath = $env:PATH
$previousEncoding = $env:PYTHONIOENCODING
$previousPython = $env:SCRAPING_PYTHON
$previousConda = $env:CONDA_PREFIX
$taskExitCode = 1
Push-Location -LiteralPath $PSScriptRoot
try {
    $env:PATH = (@($taskPrefix, (Join-Path $taskPrefix 'Library\bin'), (Join-Path $taskPrefix 'Library\usr\bin'), (Join-Path $taskPrefix 'Scripts'), $previousPath) -join [IO.Path]::PathSeparator)
    if (Test-Path -LiteralPath (Join-Path $taskPrefix 'conda-meta') -PathType Container) { $env:CONDA_PREFIX = $taskPrefix }
    $env:PYTHONIOENCODING = 'utf-8'
    $env:SCRAPING_PYTHON = $taskPython
    & $taskPython -B -X utf8 -m pipeline @args
    $taskExitCode = $LASTEXITCODE
} finally {
    $env:PATH = $previousPath
    $env:PYTHONIOENCODING = $previousEncoding
    $env:SCRAPING_PYTHON = $previousPython
    $env:CONDA_PREFIX = $previousConda
    Pop-Location
}
exit $taskExitCode
