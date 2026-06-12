# Start Daily Doer with auto-restart on unexpected exit.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$python = "C:\Python314\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

while ($true) {
    $started = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path "dailydoer.log" -Value "$started INFO launcher starting server"
    Write-Host "Starting Daily Doer at $started"

    & $python app.py --port 8780
    $code = $LASTEXITCODE
    $ended = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    if ($code -eq 0) {
        Add-Content -Path "dailydoer.log" -Value "$ended INFO launcher clean exit"
        Write-Host "Daily Doer stopped cleanly."
        break
    }

    Add-Content -Path "dailydoer.log" -Value "$ended ERROR launcher server exited with code $code; restarting in 2s"
    Write-Host "Server exited with code $code — restarting in 2 seconds…"
    Start-Sleep -Seconds 2
}
