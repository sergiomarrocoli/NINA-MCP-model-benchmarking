<#
One-time setup on the Windows mini PC. Run in an elevated PowerShell, with Sky Simulator and NINA
running (their paths are read from the running processes) and the benchmark user logged in:

    powershell -ExecutionPolicy Bypass -File setup.ps1 -PublicKey "ssh-ed25519 AAAA... comment"

What it does, and nothing more:
  1. Installs and starts the OpenSSH Server, limited to the local subnet in the firewall.
  2. Copies nina-control.ps1 and restart-app.ps1 to C:\nina-control and records the app paths.
  3. Registers two on-demand scheduled tasks that run restart-app.ps1 in the logged-on user's
     session (a process started straight from SSH has no desktop, and these are GUI apps).
  4. Authorises the key for `status`, `restart-sim` and `restart-nina` only: no shell, no
     forwarding, no other command.
#>
param(
    [Parameter(Mandatory)] [string] $PublicKey,
    [string] $User = $env:USERNAME,
    [string] $SkySimulatorPath,
    [string] $NinaPath
)
$ErrorActionPreference = "Stop"
$dir = "C:\nina-control"

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole("Administrators")) {
    throw "Run this in an elevated (Administrator) PowerShell."
}
if ($PublicKey -notmatch '^ssh-(ed25519|rsa) ') { throw "-PublicKey must be one public key line (ssh-ed25519 AAAA...)." }

# --- App paths: from the running processes unless given ---------------------------------------
function Find-Path($name, $given) {
    if ($given) { return $given }
    $p = Get-Process -Name $name -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $p) { throw "$name is not running; start it, or pass its full path as a parameter." }
    return $p.Path
}
$sim = Find-Path "sky_simulator" $SkySimulatorPath
$nina = Find-Path "NINA" $NinaPath
Write-Host "Sky Simulator: $sim"
Write-Host "NINA:          $nina"

# --- 1. OpenSSH Server -------------------------------------------------------------------------
if ((Get-WindowsCapability -Online -Name "OpenSSH.Server*").State -ne "Installed") {
    Add-WindowsCapability -Online -Name "OpenSSH.Server~~~~0.0.1.0" | Out-Null
}
Set-Service sshd -StartupType Automatic
Start-Service sshd
if (-not (Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -DisplayName "OpenSSH Server (sshd)" `
        -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
}
Set-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -RemoteAddress LocalSubnet

# --- 2. Scripts and app paths ------------------------------------------------------------------
New-Item -ItemType Directory -Force $dir | Out-Null
Copy-Item "$PSScriptRoot\nina-control.ps1", "$PSScriptRoot\restart-app.ps1" $dir -Force
@{ sim = $sim; nina = $nina } | ConvertTo-Json | Set-Content "$dir\apps.json"

# --- 3. On-demand tasks in the user's own session ----------------------------------------------
foreach ($t in @(@("sim", "NinaCtl-RestartSim"), @("nina", "NinaCtl-RestartNina"))) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File $dir\restart-app.ps1 -Target $($t[0])"
    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
    Register-ScheduledTask -TaskName $t[1] -Action $action -Principal $principal -Settings $settings -Force | Out-Null
}

# --- 4. Restricted key -------------------------------------------------------------------------
$line = 'restrict,command="powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/nina-control/nina-control.ps1" ' + $PublicKey
$isAdmin = (Get-LocalGroupMember -Group "Administrators" -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "*\$User" }) -ne $null
if ($isAdmin) {
    # Administrators use this file, not ~\.ssh\authorized_keys, and sshd insists on tight permissions.
    $file = "C:\ProgramData\ssh\administrators_authorized_keys"
    Set-Content -Path $file -Value $line -Encoding ascii
    icacls.exe $file /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F" | Out-Null
} else {
    $sshDir = "C:\Users\$User\.ssh"
    New-Item -ItemType Directory -Force $sshDir | Out-Null
    Set-Content -Path "$sshDir\authorized_keys" -Value $line -Encoding ascii
}
Restart-Service sshd
Write-Host "`nDone. From the Mac: python -m harness.minipc status"
