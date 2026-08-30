<#
.SYNOPSIS
  Register "FlightPriceTracker" as a Windows Scheduled Task.
  Run once as Administrator (or just your own user account if UAC allows).

.USAGE
  cd "C:\Users\schaa\Claude\Projects\Travel"
  .\setup_task.ps1

  To remove the task later:
  Unregister-ScheduledTask -TaskName "FlightPriceTracker" -Confirm:$false
#>

$TaskName   = "FlightPriceTracker"
$ProjectDir = "C:\Users\schaa\Claude\Projects\Travel"
$PythonExe  = (Get-Command python).Source   # uses whichever python is on PATH

# Runs daily at 07:00. StartWhenAvailable (below) means if the PC was off at 07:00,
# the task fires immediately when it comes back online — so it always runs once per day.
$Trigger = New-ScheduledTaskTrigger -Daily -At "07:00"

# The action: python -m scripts.run_all  (from the project directory)
$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "-m scripts.run_all" `
    -WorkingDirectory $ProjectDir

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Host "Updating existing task '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Trigger $Trigger `
    -Action $Action `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Checks flight prices and emails a digest to schaar000@gmail.com" | Out-Null

Write-Host "Task '$TaskName' registered. It will run Mon & Thu at 08:00."
Write-Host "To run immediately: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "To check status:    (Get-ScheduledTask -TaskName '$TaskName').State"
