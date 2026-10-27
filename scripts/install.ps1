param(
    [ValidateSet('research', 'full')][string]$Profile = 'research',
    [string]$Python = $env:SCRAPING_PYTHON,
    [string]$ReposRoot = $env:SCRAPING_REPOS,
    [string]$IndexUrl,
    [switch]$InstallBrowser
)

$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $taskLocalPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $taskLocalPython -PathType Leaf) {
        $Python = $taskLocalPython
    } elseif (Test-Path -LiteralPath (Join-Path $taskRoot '.runtime.json') -PathType Leaf) {
        $taskRuntime = Get-Content -LiteralPath (Join-Path $taskRoot '.runtime.json') -Raw | ConvertFrom-Json
        if (-not $taskRuntime.python -or -not [IO.Path]::IsPathRooted([string]$taskRuntime.python)) {
            throw '.runtime.json must contain an absolute Python path in its python field.'
        }
        $Python = [string]$taskRuntime.python
    } elseif ($env:CONDA_PREFIX -and (Test-Path -LiteralPath (Join-Path $env:CONDA_PREFIX 'python.exe') -PathType Leaf)) {
        $Python = Join-Path $env:CONDA_PREFIX 'python.exe'
    } else {
        $taskPythonCommand = Get-Command python -CommandType Application -ErrorAction SilentlyContinue
        if (-not $taskPythonCommand) { throw 'Python not found. Pass -Python or set SCRAPING_PYTHON.' }
        $Python = $taskPythonCommand.Source
        if ($Python -match '[\\/]Microsoft[\\/]WindowsApps[\\/]python[^\\/]*\.exe$') {
            throw 'Only the Windows Python app alias was found. Pass -Python or configure SCRAPING_PYTHON/.runtime.json.'
        }
    }
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Python does not exist: $Python" }
$Python = (Resolve-Path -LiteralPath $Python).Path
if (-not $ReposRoot) { $ReposRoot = Join-Path $taskRoot 'repos' }

# Check required local checkouts before installing. No automatic cloning.
if ($Profile -eq 'full') {
    $taskMissingRepos = @()
    foreach ($taskRepo in @('goverment_spider', 'NewsCrawler', 'crawl4ai', 'feapder', 'news-please')) {
        $taskRepoPath = Join-Path $ReposRoot $taskRepo
        if (-not (Test-Path -LiteralPath $taskRepoPath -PathType Container)) { $taskMissingRepos += $taskRepoPath }
    }
    if ($taskMissingRepos.Count -gt 0) {
        throw ('Required local repositories are missing. Set -ReposRoot or SCRAPING_REPOS: ' + ($taskMissingRepos -join ', '))
    }
    foreach ($taskRepo in @('crawl4ai', 'feapder', 'news-please')) {
        $taskRepoPath = Join-Path $ReposRoot $taskRepo
        if (-not ((Test-Path -LiteralPath (Join-Path $taskRepoPath 'pyproject.toml')) -or (Test-Path -LiteralPath (Join-Path $taskRepoPath 'setup.py')))) {
            throw "Repository is not installable: $taskRepoPath"
        }
    }
}
$taskRequirement = Join-Path $taskRoot $(if ($Profile -eq 'full') { 'requirements-pipeline.txt' } else { 'requirements-research.txt' })
if (-not (Test-Path -LiteralPath $taskRequirement -PathType Leaf)) { throw "Missing requirements: $taskRequirement" }

function Invoke-TaskPip {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PipArgs)
    $taskPipArguments = @('-m', 'pip', 'install')
    if ($IndexUrl) { $taskPipArguments += @('--index-url', $IndexUrl) }
    & $Python @taskPipArguments @PipArgs
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed (exit $LASTEXITCODE)." }
}

$taskPreviousPath = $env:PATH
$taskPreviousConda = $env:CONDA_PREFIX
$taskPreviousBrowsers = $env:PLAYWRIGHT_BROWSERS_PATH
$taskPrefix = Split-Path -Parent $Python
try {
    $env:PATH = (@($taskPrefix, (Join-Path $taskPrefix 'Library\bin'), (Join-Path $taskPrefix 'Library\usr\bin'), (Join-Path $taskPrefix 'Scripts'), $taskPreviousPath) -join [IO.Path]::PathSeparator)
    if (Test-Path -LiteralPath (Join-Path $taskPrefix 'conda-meta') -PathType Container) { $env:CONDA_PREFIX = $taskPrefix }
    Invoke-TaskPip -r $taskRequirement
    if ($Profile -eq 'full') {
        foreach ($taskRepo in @('feapder', 'news-please', 'crawl4ai')) {
            Invoke-TaskPip --editable (Join-Path $ReposRoot $taskRepo)
        }
        Invoke-TaskPip demjson3
    }
    if ($InstallBrowser) {
        if ($Profile -eq 'research') { Invoke-TaskPip 'playwright>=1.49' }
        if (-not $env:PLAYWRIGHT_BROWSERS_PATH) { $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $taskRoot '.playwright-browsers' }
        & $Python -m playwright install chromium
        if ($LASTEXITCODE -ne 0) { throw "Browser installation failed (exit $LASTEXITCODE)." }
    }
    @{ python = $Python } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskRoot '.runtime.json') -Encoding utf8
    Write-Output "INSTALL_DONE profile=$Profile browser=$InstallBrowser"
} finally {
    $env:PATH = $taskPreviousPath
    $env:CONDA_PREFIX = $taskPreviousConda
    $env:PLAYWRIGHT_BROWSERS_PATH = $taskPreviousBrowsers
}
