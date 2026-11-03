param([switch]$Stop)
$ErrorActionPreference = 'Stop'
$taskDocker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $taskDocker) {
    foreach ($taskDockerPath in @('C:\Program Files\Docker\Docker\resources\bin\docker.exe', (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'))) {
        if (Test-Path -LiteralPath $taskDockerPath) { $taskDocker = Get-Item -LiteralPath $taskDockerPath; break }
    }
}
$taskCompose = Join-Path $PSScriptRoot 'firecrawl\compose.yaml'
$taskEnv = Join-Path $PSScriptRoot '.env'
if (-not $taskDocker) {
    $taskContainerState = Join-Path $PSScriptRoot 'wsl-container-status.json'
    if (-not (Test-Path -LiteralPath $taskContainerState)) { throw 'The dedicated WSL container environment is not ready. Run Complete-FirecrawlWSL.ps1 after the required manual Windows restart.' }
    $taskState = Get-Content -LiteralPath $taskContainerState -Raw | ConvertFrom-Json
    if ($taskState.distro -ne 'CodexCrawlers' -or $taskState.status -ne 'docker_installed') { throw 'Docker Engine has not been installed in the dedicated WSL distribution.' }
    $taskLinuxCompose = (& wsl.exe -d CodexCrawlers -u root -- wslpath -a $taskCompose | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'The WSL environment is not available.' }
    $taskLinuxEnv = (& wsl.exe -d CodexCrawlers -u root -- wslpath -a $taskEnv | Out-String).Trim()
    & wsl.exe -d CodexCrawlers -u root -- service docker start
    if ($LASTEXITCODE -ne 0) { throw 'Could not start Docker Engine in WSL.' }
    if ($Stop) { & wsl.exe -d CodexCrawlers -u root -- docker compose --env-file $taskLinuxEnv -f $taskLinuxCompose down }
    else { & wsl.exe -d CodexCrawlers -u root -- docker compose --env-file $taskLinuxEnv -f $taskLinuxCompose up -d }
    if ($LASTEXITCODE -ne 0) { throw 'Firecrawl compose operation in WSL failed.' }
    return
}
$taskExe = $taskDocker.FullName
if (-not $taskExe) { $taskExe = $taskDocker.Source }
& $taskExe info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker is installed but its engine is not running.' }
if ($Stop) { & $taskExe compose --env-file $taskEnv -f $taskCompose down }
else { & $taskExe compose --env-file $taskEnv -f $taskCompose up -d }
if ($LASTEXITCODE -ne 0) { throw 'Firecrawl compose operation failed.' }
