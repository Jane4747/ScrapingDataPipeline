param(
    [ValidateSet('gateway','browser-use','scrapegraphai','skyvern')]
    [string[]]$Components = @('gateway','browser-use','scrapegraphai','skyvern'),
    [string]$BasePython = 'C:\Users\Jane\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe',
    [switch]$InstallSkyvernBrowser
)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'logs') -Force | Out-Null
$taskPackages = @{
    'gateway' = @('mcp==2.3.0','httpx==0.28.1','beautifulsoup4==4.15.0','psutil==7.2.2','truststore==0.10.5')
    'browser-use' = @('browser-use==0.13.14')
    'scrapegraphai' = @('scrapegraphai==2.3.1')
    'skyvern' = @('skyvern[local]==1.0.56')
}
foreach ($taskName in $Components) {
    $taskEnv = Join-Path $PSScriptRoot ('envs\' + $taskName)
    $taskPython = Join-Path $taskEnv 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $taskPython)) {
        & $BasePython -m venv --without-pip $taskEnv
        if ($LASTEXITCODE -ne 0) { throw ('Cannot create environment: ' + $taskName) }
    }
    $taskLog = Join-Path $PSScriptRoot ('logs\install-' + $taskName + '.log')
    Write-Output ('Installing ' + $taskName + '; detailed log: ' + $taskLog)
    & $BasePython -m pip --python $taskPython install --disable-pip-version-check --no-cache-dir --index-url https://pypi.org/simple @($taskPackages[$taskName]) *> $taskLog
    if ($LASTEXITCODE -ne 0) { throw ('Installation failed. See ' + $taskLog) }
    & $BasePython -m pip --python $taskPython check
    if ($LASTEXITCODE -ne 0) { throw ('Dependency check failed: ' + $taskName) }
    & $BasePython -m pip --python $taskPython freeze | Set-Content -LiteralPath (Join-Path $PSScriptRoot ($taskName + '.lock.txt')) -Encoding utf8
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.env'))) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '.env.example') -Destination (Join-Path $PSScriptRoot '.env')
    & (Join-Path $PSScriptRoot 'envs\gateway\Scripts\python.exe') -c 'from pathlib import Path;import secrets,sys;p=Path(sys.argv[1])/".env";p.write_text(p.read_text(encoding="utf-8").replace("FIRECRAWL_POSTGRES_PASSWORD=", "FIRECRAWL_POSTGRES_PASSWORD="+secrets.token_urlsafe(24)),encoding="utf-8")' $PSScriptRoot
}
if ($InstallSkyvernBrowser) {
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PSScriptRoot 'cache\browsers'
    & (Join-Path $PSScriptRoot 'envs\skyvern\Scripts\python.exe') -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Skyvern Chromium installation failed.' }
}
Write-Output 'Local packages installed. Model configuration and Firecrawl/Docker readiness are reported separately by crawler_status.'
