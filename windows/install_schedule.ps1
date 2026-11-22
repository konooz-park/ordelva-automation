# Registers the daily ORDELVA production run in Windows Task Scheduler (current user, no admin).
# Only run this AFTER you approved quality and set "production_enabled": true in config.json.
# The batch never publishes publicly; it stops at the human review gate.
param([string]$At = "09:00")
$root = Split-Path -Parent $PSScriptRoot
$action  = New-ScheduledTaskAction -Execute "$root\ordelva.bat" -Argument "batch" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$set     = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 6)
Register-ScheduledTask -TaskName "ORDELVA daily production" -Action $action -Trigger $trigger -Settings $set -Description "ORDELVA: draft, render and QA videos (review required before upload)" -Force
Write-Host "Scheduled daily at $At. Remove with: Unregister-ScheduledTask -TaskName 'ORDELVA daily production'"
