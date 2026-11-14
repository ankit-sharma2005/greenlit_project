# Stop only the processes this launcher started, by the PIDs it recorded.
Set-Location $PSScriptRoot
$pidFile = Join-Path $PSScriptRoot ".run\pids.txt"
if (-not (Test-Path $pidFile)) { Write-Host "nothing recorded"; exit 0 }
foreach ($line in Get-Content $pidFile) {
  if (-not $line.Trim()) { continue }
  $name, $processId = $line.Split(" ", 2)
  $process = Get-Process -Id ([int]$processId) -ErrorAction SilentlyContinue
  if ($process) { Stop-Process -Id $process.Id; Write-Host "stopped $name ($processId)" }
  else { Write-Host "$name ($processId) was not running" }
}
Remove-Item $pidFile -Force
