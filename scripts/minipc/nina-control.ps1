# Forced command for the benchmark SSH key (see setup.ps1). Runs one of three fixed actions and
# refuses everything else; the key has no shell. Output is JSON on stdout.
$cmd = "$env:SSH_ORIGINAL_COMMAND".Trim()

function Show-Status {
    $apps = foreach ($n in "sky_simulator", "NINA") {
        $p = Get-Process -Name $n -ErrorAction SilentlyContinue | Select-Object -First 1
        [pscustomobject]@{
            name = $n; running = [bool]$p
            started = if ($p) { $p.StartTime.ToString("s") } else { $null }
            memory_mb = if ($p) { [int]($p.WorkingSet64 / 1MB) } else { $null }
            responding = if ($p) { $p.Responding } else { $null }
        }
    }
    $servicing = [bool](Get-Process -Name DismHost, TiWorker, "Modern*Setup*" -ErrorAction SilentlyContinue)
    [pscustomobject]@{ apps = $apps; windows_servicing = $servicing; time = (Get-Date).ToString("s") } |
        ConvertTo-Json -Compress -Depth 4
}

function Restart-App($task) {
    Start-ScheduledTask -TaskName $task
    Start-Sleep -Seconds 2
    [pscustomobject]@{ started = $task } | ConvertTo-Json -Compress
}

switch ($cmd) {
    "status"       { Show-Status }
    "restart-sim"  { Restart-App "NinaCtl-RestartSim" }
    "restart-nina" { Restart-App "NinaCtl-RestartNina" }
    default        { [Console]::Error.WriteLine("not allowed: '$cmd' (use status, restart-sim, restart-nina)"); exit 2 }
}
