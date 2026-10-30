param(
    [string]$Start = '2024-01-01',
    [string]$End = (Get-Date -Format 'yyyy-MM-dd'),
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')][string]$TaskId = ('medical-202401-' + (Get-Date -Format 'yyyyMMdd-HHmmss')),
    [string]$Python = $env:SCRAPING_PYTHON,
    [Parameter(Mandatory=$true)][string]$DaguExe,
    [Parameter(Mandatory=$true)][string]$NodeExe,
    [Parameter(Mandatory=$true)][string]$ArtifactModules,
    [int]$Port = 8098,
    [switch]$Resume,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = (Get-Command python -ErrorAction Stop).Source }
foreach ($required in @($Python, $DaguExe, $NodeExe, $ArtifactModules)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required runtime is missing: $required" }
}
$runtimeHome = Join-Path $repo 'outputs\dagu-runtime'
$env:DAGU_HOME = $runtimeHome
$dagDir = Join-Path $runtimeHome 'dags'
$logDir = Join-Path $runtimeHome 'service-logs'
New-Item -ItemType Directory -Path $dagDir,$logDir -Force | Out-Null
$configFile = Join-Path $runtimeHome 'config.yaml'
if (-not (Test-Path -LiteralPath $configFile)) {
    @"
host: 127.0.0.1
port: $Port
allowed_hosts: [127.0.0.1, localhost]
auth:
  mode: none
coordinator:
  enabled: false
check_updates: false
skip_examples: true
terminal:
  enabled: false
ui:
  navbar_title: SearchingAgent
queues:
  enabled: true
  config:
    - name: medical-tender-updates
      max_concurrency: 1
"@ | Set-Content -Encoding utf8 -LiteralPath $configFile
}
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
Push-Location $repo
try {
    $planArgs = @('-u','-B','-m','pipeline.research.tender_update','plan','--task-id',$TaskId,'--start',$Start,'--end',$End,'--dag-dir',$dagDir,'--python',$Python,'--node',$NodeExe,'--artifact-modules',$ArtifactModules)
    if ($Resume) { $planArgs += '--resume' }
    & $Python @planArgs --dry-run
    if ($LASTEXITCODE -ne 0) { throw 'Task scope validation failed.' }
    & $Python @planArgs
    if ($LASTEXITCODE -ne 0) { throw 'Task preparation failed.' }
    $dagName = 'medical-tender-' + $TaskId
    $dagFile = Join-Path $dagDir ($dagName + '.yaml')
    & $DaguExe validate --dagu-home $runtimeHome $dagFile
    if ($LASTEXITCODE -ne 0) { throw 'Dagu workflow validation failed.' }
    $pidFile = Join-Path $runtimeHome 'server-process.json'
    $existing = $null
    if (Test-Path -LiteralPath $pidFile) {
        $saved = Get-Content -Raw -LiteralPath $pidFile | ConvertFrom-Json
        $candidate = Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
        if ($candidate -and $candidate.Path -eq $DaguExe -and $candidate.StartTime.ToUniversalTime().Ticks -eq ([datetime]$saved.started_at).ToUniversalTime().Ticks) { $existing = $candidate }
    }
    if (-not $existing) {
        $client = [System.Net.Sockets.TcpClient]::new()
        try { $client.Connect('127.0.0.1',$Port); $occupied=$true } catch { $occupied=$false } finally { $client.Dispose() }
        if ($occupied) { throw "Port $Port belongs to another process; no new service started." }
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $serviceArgs = @('start-all','--dagu-home',('"'+$runtimeHome+'"'),'--host','127.0.0.1','--port',[string]$Port)
        $existing = Start-Process -FilePath $DaguExe -ArgumentList $serviceArgs -WorkingDirectory $repo -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir "$stamp.out.log") -RedirectStandardError (Join-Path $logDir "$stamp.err.log")
        $ready=$false
        for ($i=0;$i -lt 30;$i++) {
            $existing.Refresh()
            if ($existing.HasExited) { throw 'Dagu service exited. Inspect service-logs.' }
            try { $health=Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/" -TimeoutSec 1; if ($health.StatusCode -eq 200) { $ready=$true;break } } catch { }
            Start-Sleep -Milliseconds 300
        }
        if (-not $ready) { throw 'Dagu did not become ready.' }
        @{pid=$existing.Id;started_at=$existing.StartTime.ToUniversalTime().ToString('o');executable=$DaguExe;port=$Port} | ConvertTo-Json | Set-Content -Encoding utf8 -LiteralPath $pidFile
    }
    $runId = $TaskId + '-' + ([guid]::NewGuid().ToString('N').Substring(0,6))
    & $DaguExe enqueue --dagu-home $runtimeHome --run-id $runId $dagFile
    if ($LASTEXITCODE -ne 0) { throw 'Dagu enqueue failed.' }
    $runUrl = "http://127.0.0.1:$Port/dag-runs/$dagName/$runId"
    $taskFolder = Join-Path $repo "outputs\tender-updates\$TaskId"
    @{task_id=$TaskId;run_id=$runId;dag_name=$dagName;dashboard_url=$runUrl;output_dir=$taskFolder;dagu_home=$runtimeHome} | ConvertTo-Json | Set-Content -Encoding utf8 -LiteralPath (Join-Path $taskFolder 'launch.json')
    if (-not $NoBrowser) { Start-Process $runUrl | Out-Null }
    Write-Output "Task queued; dashboard: $runUrl"
    Write-Output "Outputs: $taskFolder"
} finally { Pop-Location }
