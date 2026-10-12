# Run by the NinaCtl-* scheduled tasks inside the logged-on user's session: close the app, start it
# again from the path recorded by setup.ps1. Appends to C:\nina-control\log.txt.
param([Parameter(Mandatory)] [ValidateSet("sim", "nina")] [string] $Target)
$dir = "C:\nina-control"
$apps = Get-Content "$dir\apps.json" | ConvertFrom-Json
$exe = $apps.$Target
$name = if ($Target -eq "sim") { "sky_simulator" } else { "NINA" }
function Log($m) { "$((Get-Date).ToString('s'))  $Target  $m" | Add-Content "$dir\log.txt" }

Log "restart requested"
foreach ($p in Get-Process -Name $name -ErrorAction SilentlyContinue) {
    [void]$p.CloseMainWindow()
    if (-not $p.WaitForExit(10000)) {
        Log "pid $($p.Id) did not close in 10 s, killing"
        Stop-Process -Id $p.Id -Force
        $p.WaitForExit(10000) | Out-Null
    }
}
Start-Sleep -Seconds 2
Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe)
Log "started $exe"
