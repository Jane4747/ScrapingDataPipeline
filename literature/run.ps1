param(
    [Parameter(Mandatory=$true)][string]$Spec,
    [switch]$DryRun,
    [switch]$Resume
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if ($env:SCRAPING_PYTHON) {
    $literaturePython = $env:SCRAPING_PYTHON
} elseif (Test-Path -LiteralPath (Join-Path $repoRoot '.runtime.json')) {
    $literaturePython = (Get-Content -LiteralPath (Join-Path $repoRoot '.runtime.json') -Raw | ConvertFrom-Json).python
} else {
    $literaturePython = (Get-Command python -ErrorAction Stop).Source
}
$specPath = (Resolve-Path -LiteralPath $Spec).Path
$collectorArgs = @('-B','-u','-X','utf8',(Join-Path $PSScriptRoot 'collector.py'),'--spec',$specPath,'--json')
if ($DryRun) { $collectorArgs += '--dry-run' }
if ($Resume) { $collectorArgs += '--resume' }
& $literaturePython @collectorArgs
exit $LASTEXITCODE

