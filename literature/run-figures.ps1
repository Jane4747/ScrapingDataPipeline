param(
    [Parameter(Mandatory=$true)][string]$Spec,
    [switch]$DryRun,
    [switch]$Resume,
    [ValidateSet('scan','figures','assets','all')][string]$Stage='all'
)
$ErrorActionPreference='Stop'
if ($env:FIGURE_PYTHON) {
    $figurePython=$env:FIGURE_PYTHON
} else {
    $figurePython=(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'figure-runtime.json') -Raw | ConvertFrom-Json).python
}
$figureSpec=(Resolve-Path -LiteralPath $Spec).Path
$figureArgs=@('-B','-u','-X','utf8',(Join-Path $PSScriptRoot 'extract_figures.py'),'--spec',$figureSpec,'--stage',$Stage)
if ($DryRun) { $figureArgs+='--dry-run' }
if ($Resume) { $figureArgs+='--resume' }
& $figurePython @figureArgs
exit $LASTEXITCODE

