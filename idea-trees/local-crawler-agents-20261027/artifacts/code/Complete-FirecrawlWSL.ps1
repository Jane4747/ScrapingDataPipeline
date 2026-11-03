# Resume after a required manual Windows restart. Does not restart Windows.
$ErrorActionPreference = 'Stop'
$taskImage = 'D:\CodexLocalCrawlers\installers\ubuntu-24.04.5-wsl-amd64.wsl'
$taskLinuxRoot = 'D:\CodexLocalCrawlers\WSL\CodexCrawlers'
$taskDistro = 'CodexCrawlers'
$taskStatePath = Join-Path $PSScriptRoot 'wsl-container-status.json'
$taskImageHash = 'bb415d824822c4b878125729af451a5d18fb13d1cf5cbed9a7393ad64ac6039e'
if (-not (Test-Path -LiteralPath $taskImage)) { throw 'The verified Ubuntu image has not been staged yet.' }
if ((Get-FileHash -LiteralPath $taskImage -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskImageHash) { throw 'The Ubuntu image failed integrity verification.' }
$taskNames = (& wsl.exe --list --quiet | Out-String) -replace "`0", ''
if ($taskNames -notmatch '(?m)^CodexCrawlers\s*$') {
    New-Item -ItemType Directory -Path $taskLinuxRoot -Force | Out-Null
    & wsl.exe --import $taskDistro $taskLinuxRoot $taskImage --version 2
    if ($LASTEXITCODE -ne 0) { throw 'WSL could not import Ubuntu. If Windows features are pending, restart Windows manually first.' }
    @{ distro = $taskDistro; linux_root = $taskLinuxRoot; status = 'imported'; automatic_restart = $false } | ConvertTo-Json | Set-Content -LiteralPath $taskStatePath -Encoding utf8
} else {
    $taskOwned = $false
    if (Test-Path -LiteralPath $taskStatePath) {
        $taskPrevious = Get-Content -LiteralPath $taskStatePath -Raw | ConvertFrom-Json
        $taskOwned = ($taskPrevious.distro -eq $taskDistro -and $taskPrevious.linux_root -eq $taskLinuxRoot)
    }
    if (-not $taskOwned) { throw 'A distribution with the same name already exists and is not registered to this deployment.' }
}
& wsl.exe -d $taskDistro -u root -- true
if ($LASTEXITCODE -ne 0) { throw 'The WSL 2 distribution cannot start. A manual Windows restart may still be required.' }
$taskLinuxScript = (& wsl.exe -d $taskDistro -u root -- wslpath -a (Join-Path $PSScriptRoot 'firecrawl\install-docker-wsl.sh') | Out-String).Trim()
& wsl.exe -d $taskDistro -u root -- bash $taskLinuxScript
if ($LASTEXITCODE -ne 0) { throw 'Docker Engine installation in the dedicated WSL distribution failed.' }
@{ distro = $taskDistro; linux_root = $taskLinuxRoot; status = 'docker_installed'; automatic_restart = $false } | ConvertTo-Json | Set-Content -LiteralPath $taskStatePath -Encoding utf8
& (Join-Path $PSScriptRoot 'Start-Firecrawl.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Firecrawl startup failed.' }
