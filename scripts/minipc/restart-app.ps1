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

# Sky Simulator comes up idle: its Alpaca server only starts when "Start simulation." is pressed, and the
# app has no start-on-launch setting. Press it through Windows UI Automation (docs/minipc-remote.md).
if ($Target -ne "sim") { return }
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type -Namespace Win -Name Mouse -MemberDefinition @"
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
"@
$AE = [System.Windows.Automation.AutomationElement]

function Find-Button($window) {
    $all = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($e in $all) { if ($e.Current.Name -like "Start simulation*") { return $e } }
    $names = ($all | ForEach-Object { "$($_.Current.ControlType.ProgrammaticName):'$($_.Current.Name)'" } | Select-Object -First 80) -join "; "
    Log "no 'Start simulation.' control among $($all.Count) elements: $names"
    return $null
}

$window = $null
for ($i = 0; $i -lt 60 -and -not $window; $i++) {
    Start-Sleep -Seconds 1
    $p = Get-Process -Name $name -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
    if ($p) { $window = $AE::FromHandle($p.MainWindowHandle) }
}
if (-not $window) { Log "START FAILED: no Sky Simulator window within 60 s"; return }

Start-Sleep -Seconds 3  # let the window finish drawing
$button = Find-Button $window
if (-not $button) { Log "START FAILED: button not found"; return }
try {
    $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    Log "pressed 'Start simulation.' (invoke)"
} catch {
    # The control is visible but cannot be invoked: click where it is.
    $r = $button.Current.BoundingRectangle
    [Win.Mouse]::SetCursorPos([int]($r.X + $r.Width / 2), [int]($r.Y + $r.Height / 2)) | Out-Null
    [Win.Mouse]::mouse_event(0x2, 0, 0, 0, [UIntPtr]::Zero)
    [Win.Mouse]::mouse_event(0x4, 0, 0, 0, [UIntPtr]::Zero)
    Log "pressed 'Start simulation.' (mouse click, invoke failed: $($_.Exception.Message))"
}
