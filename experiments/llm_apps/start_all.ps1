# Start the eight local test apps (A1-A4 LLM-backed, A5-A8 deterministic) and remember only their PIDs.
# Local test subjects only: 127.0.0.1 by default; never expose them to the internet.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$mode = if ($env:APP_MODE) { $env:APP_MODE } else { "guarded" }
$bind = if ($env:LLM_APPS_HOST) { $env:LLM_APPS_HOST } else { "127.0.0.1" }
$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$venv = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$runDir = Join-Path $PSScriptRoot ".run"
New-Item -ItemType Directory -Force $runDir | Out-Null
$pidFile = Join-Path $runDir "pids.txt"

foreach ($port in 9111, 9112, 9113, 9114, 9115, 9116, 9117, 9118) {
  $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
  try { $listener.Start() } catch { throw "port $port is already in use; refusing to start" }
  $listener.Stop()
}
if (-not (Test-Path $venv)) { throw "A4 needs the app's own virtualenv (.venv with mcp<2)" }

Set-Content $pidFile ""
function Start-App($name, $exe, $arguments) {
  $process = Start-Process -FilePath $exe -ArgumentList $arguments -PassThru `
    -RedirectStandardOutput (Join-Path $runDir "$name.log") `
    -RedirectStandardError (Join-Path $runDir "$name.err.log")
  Add-Content $pidFile "$name $($process.Id)"
}
Start-App "support-bot" $py @("support_bot/app.py", "--host", $bind, "--port", "9111")
Start-App "docs-rag" $py @("docs_rag/app.py", "--host", $bind, "--port", "9112")
Start-App "stream-bot" $py @("stream_bot/app.py", "--host", $bind, "--port", "9113")
Start-App "tool-agent" $venv @("tool_agent/server.py", "--host", $bind, "--port", "9114")
$solverMode = if ($env:DEMO_MODE) { $env:DEMO_MODE } else { "correct" }
Start-App "math-solver" $py @("math_solver/app.py", "--host", $bind, "--port", "9115", "--mode", $solverMode)
$labMode = if ($env:LAB_MODE) { $env:LAB_MODE } else { "ok" }
$vaultMode = if ($env:VAULT_MODE) { $env:VAULT_MODE } else { "vulnerable" }
$siteMode = if ($env:SITE_MODE) { $env:SITE_MODE } else { "normal" }
Start-App "reliability-lab" $py @("reliability_lab/app.py", "--host", $bind, "--port", "9116", "--mode", $labMode)
Start-App "vault-bot" $py @("vault_bot/app.py", "--host", $bind, "--port", "9117", "--mode", $vaultMode)
Start-App "site-bot" $py @("site_bot/app.py", "--host", $bind, "--port", "9118", "--mode", $siteMode)

Write-Host "mode=$mode provider=$($env:LLM_PROVIDER) bind=$bind"
Write-Host "A1 support-bot  http://${bind}:9111/"
Write-Host "A2 docs-rag     http://${bind}:9112/"
Write-Host "A3 stream-bot   http://${bind}:9113/  /sse  /ndjson  /text"
Write-Host "A4 tool-agent   http://${bind}:9114/mcp"
Write-Host "A5 math-solver  http://${bind}:9115/  (deterministic, mode $solverMode; POST /_control/mode needs DEMO_CONTROL=1)"
Write-Host "A6 reliability  http://${bind}:9116/  (deterministic, mode $labMode: ok|flaky_20|slow|rate_limited)"
Write-Host "A7 vault-bot    http://${bind}:9117/  (deterministic, mode $vaultMode: vulnerable|hardened)"
Write-Host "A8 site-bot     http://${bind}:9118/chat-page  /api/chat  (deterministic, mode $siteMode: normal|csrf_off)"
Write-Host "PIDs in $pidFile; stop with .\stop_all.ps1"
