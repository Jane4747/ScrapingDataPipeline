# Run with an administrator token. Never restarts Windows.
$ErrorActionPreference = 'Stop'
$taskStatePath = Join-Path $PSScriptRoot 'host-setup-status.json'
$taskState = [ordered]@{ started_at = (Get-Date).ToString('o'); automatic_restart = $false; status = 'running'; features = @(); restart_required = $false }
function Save-TaskState { $taskState | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $taskStatePath -Encoding UTF8 }
Save-TaskState
try {
    $taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $taskPrincipal = New-Object Security.Principal.WindowsPrincipal($taskIdentity)
    if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator authorization is required.' }
    foreach ($taskFeature in @('Microsoft-Windows-Subsystem-Linux','VirtualMachinePlatform')) {
        $taskBefore = Get-WindowsOptionalFeature -Online -FeatureName $taskFeature
        if ($taskBefore.State -ne 'Enabled') {
            $taskResult = Enable-WindowsOptionalFeature -Online -FeatureName $taskFeature -All -NoRestart
            if ($taskResult.RestartNeeded) { $taskState.restart_required = $true }
        }
        $taskAfter = Get-WindowsOptionalFeature -Online -FeatureName $taskFeature
        if ([string]$taskAfter.State -match 'Pending') { $taskState.restart_required = $true }
        $taskState.features += @{ name = $taskFeature; before = [string]$taskBefore.State; after = [string]$taskAfter.State }
        Save-TaskState
    }
    $taskMsi = Join-Path $PSScriptRoot 'installers\wsl.3.0.3.0.x64.msi'
    if (-not (Test-Path -LiteralPath $taskMsi)) { throw 'Download and verify the WSL installer first.' }
    $taskSignature = Get-AuthenticodeSignature -FilePath $taskMsi
    if ($taskSignature.Status -ne 'Valid' -or $taskSignature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') { throw 'The WSL installer Microsoft signature could not be verified.' }
    $taskState.installer_signature = [string]$taskSignature.Status
    Save-TaskState
    $taskMsiLog = Join-Path $PSScriptRoot 'logs\wsl-msi.log'
    $taskInstall = Start-Process -FilePath "$env:WINDIR\System32\msiexec.exe" -ArgumentList @('/i',('"' + $taskMsi + '"'),'/qn','/norestart','/L*v',('"' + $taskMsiLog + '"')) -WindowStyle Hidden -Wait -PassThru
    $taskState.installer_exit_code = $taskInstall.ExitCode
    if ($taskInstall.ExitCode -eq 3010) { $taskState.restart_required = $true }
    elseif ($taskInstall.ExitCode -ne 0) { throw ('WSL MSI failed with exit code ' + $taskInstall.ExitCode) }
    New-Item -ItemType Directory -Path 'D:\CodexLocalCrawlers\WSL' -Force | Out-Null
    $taskState.linux_data_directory = 'D:\CodexLocalCrawlers\WSL'
    $taskState.status = if ($taskState.restart_required) { 'waiting_for_manual_restart' } else { 'wsl_host_configured' }
    $taskState.finished_at = (Get-Date).ToString('o')
    Save-TaskState
} catch {
    $taskState.status = 'failed'
    $taskState.error = $_.Exception.Message
    $taskState.finished_at = (Get-Date).ToString('o')
    Save-TaskState
    exit 1
}
