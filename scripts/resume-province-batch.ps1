<#
.SYNOPSIS
  Resume a province batch outside the agent session.

.DESCRIPTION
  The collection worker is a child of whatever started it, so closing the app
  that launched it also ends the run. This script starts the same DAG from a
  plain console window instead, which keeps running after the agent is gone.

  Before starting it refuses to run while a region lock is still held by a live
  process; stale locks (holder already dead) and a stale pacing file are
  removed, because a pacing value written before a reboot is meaningless to
  time.monotonic() and would otherwise stall every worker.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\resume-province-batch.ps1 -Batch 1
#>
param(
    [ValidateSet(1,2)][int]$Batch = 1,
    [string]$TaskId,
    [string]$DaguExe = 'C:\Users\Jane\.codex\.chatgpt-projects\g-p-6ad9720f1cd48191b33b188cf4398a78\work\searchingagent-dagu-20261029\bin\dagu.exe',
    [switch]$WhatIfOnly
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not $TaskId) { $TaskId = "province-b$Batch-2024-20261029" }
$taskDir = Join-Path $repo "outputs\province-updates\$TaskId"
$daguHome = Join-Path $repo 'outputs\dagu-runtime'
$dagFile = Join-Path $daguHome "dags\pt-$TaskId.yaml"

foreach ($path in @($taskDir, $dagFile, $DaguExe)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing: $path" }
}

$blocked = @()
$cleared = @()
foreach ($lock in Get-ChildItem -Path (Join-Path $taskDir 'regions') -Filter 'source.lock' -Recurse -ErrorAction SilentlyContinue) {
    $holder = $null
    try { $holder = (Get-Content -Raw -LiteralPath $lock.FullName | ConvertFrom-Json).pid } catch { }
    if ($holder -and (Get-Process -Id $holder -ErrorAction SilentlyContinue)) {
        $blocked += "$($lock.Directory.Name) held by pid $holder"
    } else {
        Remove-Item -LiteralPath $lock.FullName -Force
        $cleared += "regions/$($lock.Directory.Name)/source.lock"
    }
}
foreach ($name in @('.source-pace', '.source-pace.lck')) {
    $file = Join-Path $taskDir $name
    if (-not (Test-Path -LiteralPath $file)) { continue }
    try {
        Remove-Item -LiteralPath $file -Force -ErrorAction Stop
        $cleared += $name
    } catch {
        $blocked += "$name is in use by a running worker"
    }
}
if ($blocked) { throw ('A region is still running; stop it first: ' + ($blocked -join '; ')) }
if ($cleared) { Write-Output ('cleared stale state: ' + ($cleared -join ', ')) }

$runId = "manual-b$Batch-" + (Get-Date -Format 'MMdd-HHmmss')
if ($WhatIfOnly) { Write-Output "would run: $DaguExe start --dagu-home `"$daguHome`" --run-id $runId `"$dagFile`""; return }

Set-Location $repo
$env:PYTHONUTF8 = '1'
& $DaguExe start --dagu-home $daguHome --run-id $runId $dagFile
exit $LASTEXITCODE
