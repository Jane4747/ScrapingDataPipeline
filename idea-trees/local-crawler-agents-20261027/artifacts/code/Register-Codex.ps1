$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot 'envs\gateway\Scripts\python.exe'
$taskGateway = Join-Path $PSScriptRoot 'gateway.py'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run Install.ps1 first.' }
$taskCodex = Get-Command codex -ErrorAction Stop
& $taskCodex.Source mcp add local_crawlers -- $taskPython $taskGateway
if ($LASTEXITCODE -ne 0) { throw 'Codex MCP registration failed.' }
Write-Output 'Registered local_crawlers. Reload MCP connections or start a new Codex chat to load its tools.'
