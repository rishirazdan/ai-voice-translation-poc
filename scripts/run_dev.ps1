param(
  [Alias("Host")]
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8010,
  [switch]$Reload
)

$env:APP_HOST = $BindHost
$env:APP_PORT = "$Port"
$args = @("-m", "uvicorn", "app.main:app", "--host", $BindHost, "--port", "$Port")
if ($Reload) {
  $args += "--reload"
}
python @args
