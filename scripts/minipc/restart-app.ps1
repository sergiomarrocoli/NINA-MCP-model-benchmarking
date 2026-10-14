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
# app has no start-on-launch setting. UI Automation sees nothing inside its window (0 elements, 14 Oct), so
# look for the button as a plain Win32 child window and click it with a BM_CLICK message (docs/minipc-remote.md).
if ($Target -ne "sim") { return }
Add-Type -Namespace Win -Name Native -MemberDefinition @"
public delegate bool EnumProc(System.IntPtr hwnd, System.IntPtr lParam);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool EnumChildWindows(System.IntPtr parent, EnumProc cb, System.IntPtr lParam);
[System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)] public static extern int GetWindowText(System.IntPtr hwnd, System.Text.StringBuilder text, int max);
[System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)] public static extern int GetClassName(System.IntPtr hwnd, System.Text.StringBuilder text, int max);
public delegate bool EnumTop(System.IntPtr hwnd, System.IntPtr lParam);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool EnumWindows(EnumTop cb, System.IntPtr lParam);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(System.IntPtr hwnd, out uint pid);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool IsWindowVisible(System.IntPtr hwnd);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern System.IntPtr SendMessage(System.IntPtr hwnd, uint msg, System.IntPtr w, System.IntPtr l);
"@

function Get-Children($parent) {
    $script:found = New-Object System.Collections.ArrayList
    $cb = [Win.Native+EnumProc]{ param($h, $l)
        $t = New-Object System.Text.StringBuilder 256; $c = New-Object System.Text.StringBuilder 256
        [void][Win.Native]::GetWindowText($h, $t, 256); [void][Win.Native]::GetClassName($h, $c, 256)
        [void]$script:found.Add([pscustomobject]@{ Handle = $h; Text = $t.ToString(); Class = $c.ToString() })
        $true }
    [void][Win.Native]::EnumChildWindows($parent, $cb, [IntPtr]::Zero)
    return $script:found
}

# Every top-level window of the app: Lazarus programs keep a hidden helper window that Windows reports as the
# "main window", and the real form is another one.
function Get-TopWindows($pids) {
    $script:tops = New-Object System.Collections.ArrayList
    $cb = [Win.Native+EnumTop]{ param($h, $l)
        $procId = 0; [void][Win.Native]::GetWindowThreadProcessId($h, [ref]$procId)
        if ($pids -contains [int]$procId) {
            $t = New-Object System.Text.StringBuilder 256; $c = New-Object System.Text.StringBuilder 256
            [void][Win.Native]::GetWindowText($h, $t, 256); [void][Win.Native]::GetClassName($h, $c, 256)
            [void]$script:tops.Add([pscustomobject]@{ Handle = $h; Text = $t.ToString(); Class = $c.ToString(); Visible = [Win.Native]::IsWindowVisible($h) })
        }
        $true }
    [void][Win.Native]::EnumWindows($cb, [IntPtr]::Zero)
    return $script:tops
}

# The form can appear a while after launch and its controls a little after that, so keep looking.
$button = $null; $tops = @(); $children = @()
for ($i = 0; $i -lt 60 -and -not $button; $i++) {
    Start-Sleep -Seconds 1
    $pids = @(Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
    $tops = @(Get-TopWindows $pids)
    $children = @(foreach ($w in $tops) { Get-Children $w.Handle })
    $button = @($tops) + @($children) | Where-Object { $_.Text -like "Start simulation*" } | Select-Object -First 1
}
if (-not $button) {
    $list = (@($tops | ForEach-Object { "TOP $($_.Class):'$($_.Text)' visible=$($_.Visible)" }) + @($children | Select-Object -First 60 | ForEach-Object { "$($_.Class):'$($_.Text)'" })) -join "; "
    Log "START FAILED: no 'Start simulation.' window among $($tops.Count) top-level and $($children.Count) child windows: $list"
    return
}
[void][Win.Native]::SendMessage($button.Handle, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)  # BM_CLICK
Log "pressed '$($button.Text)' ($($button.Class), BM_CLICK)"
