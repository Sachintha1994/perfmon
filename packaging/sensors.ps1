# Registers / removes the scheduled task that runs the bundled LibreHardwareMonitor
# with admin rights at sign-in (so there's no UAC prompt every boot).
# Called by the PerfMon installer and uninstaller (elevated).
param(
  [Parameter(Mandatory)] [ValidateSet("install", "uninstall")] [string] $Action,
  [Parameter(Mandatory)] [string] $AppDir
)
$ErrorActionPreference = "Stop"
$TaskPath = "\PerfMon\"
$TaskName = "Sensors"
$Exe = Join-Path $AppDir "LibreHardwareMonitor\LibreHardwareMonitor.exe"

# NB: PowerShell variable names are case-insensitive - don't reuse $action/$appdir names
# for anything else, or they'd collide with the validated -Action / -AppDir parameters.
function Stop-BundledLhm {
  Get-Process LibreHardwareMonitor -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path -like "$AppDir*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue
}

if ($Action -eq "install") {
  # Run for whichever user signs in; "Highest" gives admin users an elevated LHM.
  $users = (New-Object Security.Principal.SecurityIdentifier "S-1-5-32-545").Translate([Security.Principal.NTAccount]).Value
  $principal = New-ScheduledTaskPrincipal -GroupId $users -RunLevel Highest
  $trigger = New-ScheduledTaskTrigger -AtLogOn
  $trigger.Delay = "PT10S"
  $taskAction = New-ScheduledTaskAction -Execute $Exe -WorkingDirectory (Split-Path $Exe)
  # Laptop-friendly: start and keep running on battery, never time out.
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
  Register-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Principal $principal -Trigger $trigger `
    -Action $taskAction -Settings $settings -Description "Starts LibreHardwareMonitor for PerfMon temperature monitoring." -Force | Out-Null
  # Let signed-in users start it on demand (PerfMon does this when temps aren't available).
  # Non-essential: if this fails, PerfMon falls back to starting LHM with a UAC prompt.
  try {
    $svc = New-Object -ComObject Schedule.Service; $svc.Connect()
    $task = $svc.GetFolder($TaskPath).GetTask($TaskName)
    $sddl = $task.GetSecurityDescriptor(4)   # DACL only, so the appended ACE lands in the DACL
    if ($sddl -notmatch "\(A;;GRGX;;;AU\)") { $task.SetSecurityDescriptor($sddl + "(A;;GRGX;;;AU)", 0) }
  } catch { Write-Warning "could not let users start the task: $_" }
  # Stop any LibreHardwareMonitor already running (bundled or a separate install): only one
  # instance can serve sensor data on port 8085, and PerfMon's bundled copy replaces it.
  Get-Process LibreHardwareMonitor -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 1
  Start-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName
}
else {
  Stop-BundledLhm
  Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  try { $svc = New-Object -ComObject Schedule.Service; $svc.Connect(); $svc.GetFolder("\").DeleteFolder("PerfMon", 0) } catch {}
}
