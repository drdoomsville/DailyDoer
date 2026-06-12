# Gracefully stop Daily Doer (avoids force-kill crash exit codes).
$ErrorActionPreference = "SilentlyContinue"

try {
    Invoke-WebRequest -Uri "http://127.0.0.1:8780/api/shutdown" -Method POST -UseBasicParsing -TimeoutSec 3 | Out-Null
    Write-Host "Shutdown signal sent."
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Milliseconds 500
        $listen = Get-NetTCPConnection -LocalPort 8780 -State Listen -ErrorAction SilentlyContinue
        if (-not $listen) {
            Write-Host "Server stopped cleanly."
            exit 0
        }
    }
    Write-Host "Server still listening after graceful shutdown."
} catch {
    Write-Host "Server not responding to shutdown API."
}

$listen = Get-NetTCPConnection -LocalPort 8780 -State Listen -ErrorAction SilentlyContinue
if ($listen) {
    $listen | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        Write-Host "Force-stopped PID $($_.OwningProcess)"
    }
} else {
    Write-Host "No server listening on port 8780."
}
