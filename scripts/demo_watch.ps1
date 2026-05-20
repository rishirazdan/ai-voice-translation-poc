Set-Location "C:\Users\RR\Test Live Translation"
while ($true) {
  $u=(Get-Content .env | Select-String '^PUBLIC_BASE_URL=').ToString().Split('=',2)[1].Trim()
  try {
    $l=(Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8010/health' -TimeoutSec 5).StatusCode
    $p=(Invoke-WebRequest -UseBasicParsing "$u/health" -TimeoutSec 8).StatusCode
    Write-Host ((Get-Date).ToString('HH:mm:ss') + " LOCAL=" + $l + " PUBLIC=" + $p + " URL=" + $u) -ForegroundColor Green
  } catch {
    Write-Host ((Get-Date).ToString('HH:mm:ss') + " HEALTH_ERR=" + $_.Exception.Message) -ForegroundColor Red
  }
  Start-Sleep -Seconds 3
}
