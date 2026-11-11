#Requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Config,
    [ValidateSet('evidence','excel','ppt','all')][string]$Stage = 'all',
    [string]$OutputRoot = (Join-Path $PSScriptRoot '..\..\outputs\pdf_charts'),
    [string]$RunId = ('run-' + (Get-Date -AsUTC -Format 'yyyyMMddTHHmmssfffZ')),
    [string]$RuntimeRoot = (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'),
    [string]$SourcePdf,
    [string]$PresentationSkillDir,
    [string]$SpreadsheetSkillDir,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
if ($RunId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,100}$') { throw 'RunId只能包含字母、数字、下划线和连字符。' }
$taskConfig = (Resolve-Path -LiteralPath $Config).Path
$taskOutputRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputRoot)
$RuntimeRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($RuntimeRoot)
$taskRunDir = Join-Path $taskOutputRoot $RunId
if (Test-Path -LiteralPath $taskRunDir) { throw '运行目录已存在。请使用新的RunId，避免覆盖历史。' }
$taskPython = Join-Path $RuntimeRoot 'python\python.exe'
$taskNode = Join-Path $RuntimeRoot 'node\bin\node.exe'
$taskModules = Join-Path $RuntimeRoot 'node\node_modules'
$taskPoppler = Join-Path $RuntimeRoot 'native\poppler\Library\bin\pdftoppm.exe'
$required = @($taskPython)
if ($Stage -ne 'evidence') { $required += @($taskNode,$taskModules) }
foreach ($taskPath in $required) {
    if (-not (Test-Path -LiteralPath $taskPath)) { throw ('缺少本机运行依赖：' + $taskPath) }
}
function Find-TaskSkill([string]$Package,[string]$SkillName) {
    $taskSkillRoot = Join-Path $env:USERPROFILE ('.codex\plugins\cache\openai-primary-runtime\' + $Package)
    $taskCandidates = Get-ChildItem -LiteralPath $taskSkillRoot -Directory | Where-Object { $_.Name -match '^\d+\.\d+\.\d+$' } | Sort-Object { [version]$_.Name } -Descending
    foreach ($taskCandidate in $taskCandidates) {
        $taskSkill = Join-Path $taskCandidate.FullName ('skills\' + $SkillName)
        if (Test-Path -LiteralPath (Join-Path $taskSkill 'SKILL.md')) { return $taskSkill }
    }
    throw ('未找到技能运行资源：' + $Package)
}
if ($Stage -in @('ppt','all') -and -not $PresentationSkillDir) { $PresentationSkillDir = Find-TaskSkill 'presentations' 'presentations' }
if ($Stage -in @('excel','all') -and -not $SpreadsheetSkillDir) { $SpreadsheetSkillDir = Find-TaskSkill 'spreadsheets' 'spreadsheets' }
if ($PresentationSkillDir) { $PresentationSkillDir = (Resolve-Path -LiteralPath $PresentationSkillDir).Path }
if ($SpreadsheetSkillDir) { $SpreadsheetSkillDir = (Resolve-Path -LiteralPath $SpreadsheetSkillDir).Path }
if ($Stage -in @('all','evidence') -and -not (Test-Path -LiteralPath $taskPoppler)) { throw '缺少PDF页面渲染工具。' }
$taskValidation = & $taskPython (Join-Path $PSScriptRoot 'validate_data.py') $taskConfig
if ($LASTEXITCODE -ne 0) { throw '数据配置校验失败。' }
$taskInput = Get-Content -LiteralPath $taskConfig -Raw | ConvertFrom-Json
$taskInput.source.path = if ($SourcePdf) { (Resolve-Path -LiteralPath $SourcePdf).Path } else { [IO.Path]::GetFullPath($taskInput.source.path, (Split-Path -Parent $taskConfig)) }
$runConfig = Join-Path $taskRunDir 'input.json'
if ($Stage -in @('all','evidence') -and -not (Test-Path -LiteralPath $taskInput.source.path -PathType Leaf)) { throw ('找不到源PDF：' + $taskInput.source.path) }
if ($DryRun) {
    [pscustomobject]@{ status='dry_run_passed'; config=$taskConfig; stage=$Stage; runDirectory=$taskRunDir; runtime=$RuntimeRoot } | ConvertTo-Json -Compress
    return
}
$taskOldEnv = @{}
foreach ($taskKey in @('RUNTIME_PYTHON','RUNTIME_NODE_MODULES','PRESENTATION_SKILL_DIR')) { $taskOldEnv[$taskKey] = [Environment]::GetEnvironmentVariable($taskKey,'Process') }
New-Item -ItemType Directory -Path $taskRunDir | Out-Null
$taskInput | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $runConfig -Encoding utf8
$taskValidation | Set-Content -LiteralPath (Join-Path $taskRunDir 'data-validation.json') -Encoding utf8
$taskStatus = [ordered]@{ status='running'; config=$taskConfig; stage=$Stage; runDirectory=$taskRunDir; startedAtUtc=(Get-Date -AsUTC -Format o); completedStages=@(); note='数据配置应先与PDF原图或配套表核对。结构校验不能代替目视核对。' }
try {
    $env:RUNTIME_PYTHON = $taskPython
    $env:RUNTIME_NODE_MODULES = $taskModules
    $env:PRESENTATION_SKILL_DIR = $PresentationSkillDir
    if ($Stage -in @('evidence','all')) {
        & $taskPython (Join-Path $PSScriptRoot 'extract_evidence.py') --config $runConfig --output (Join-Path $taskRunDir 'evidence') --poppler $taskPoppler *> (Join-Path $taskRunDir 'evidence.log')
        if ($LASTEXITCODE -ne 0) { throw 'PDF页面提取失败，查看evidence.log。' }
        $taskStatus.completedStages += 'evidence'
    }
    if ($Stage -in @('excel','all')) {
        Push-Location $SpreadsheetSkillDir
        try { & $taskNode 'container_tools/mark_artifact_operation_started.mjs' --operation-kind create --expected-output-count 1 --output-format xlsx; if ($LASTEXITCODE -ne 0) { throw 'Excel创建标记失败。' } } finally { Pop-Location }
        & $taskNode (Join-Path $PSScriptRoot 'build_excel.mjs') $runConfig $taskRunDir *> (Join-Path $taskRunDir 'excel.log')
        if ($LASTEXITCODE -ne 0) { throw 'Excel生成失败，查看excel.log。' }
        $taskStatus.completedStages += 'excel'
    }
    if ($Stage -in @('ppt','all')) {
        Push-Location $PresentationSkillDir
        try { & $taskNode 'container_tools/mark_artifact_operation_started.mjs' --operation-kind create --expected-output-count 1 --output-format pptx; if ($LASTEXITCODE -ne 0) { throw 'PPT创建标记失败。' } } finally { Pop-Location }
        & $taskNode (Join-Path $PSScriptRoot 'build_ppt.mjs') $runConfig $taskRunDir *> (Join-Path $taskRunDir 'ppt.log')
        if ($LASTEXITCODE -ne 0) { throw 'PPT生成失败，查看ppt.log。' }
        $taskStatus.completedStages += 'ppt'
    }
    $taskStatus.status = 'completed'
} catch {
    $taskStatus.status = 'failed'
    $taskStatus.error = $_.Exception.Message
    throw
} finally {
    $taskStatus.finishedAtUtc = Get-Date -AsUTC -Format o
    $taskStatus | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $taskRunDir 'status.json') -Encoding utf8
    foreach ($taskKey in $taskOldEnv.Keys) { [Environment]::SetEnvironmentVariable($taskKey,$taskOldEnv[$taskKey],'Process') }
}
$taskStatus | ConvertTo-Json -Depth 6 -Compress
