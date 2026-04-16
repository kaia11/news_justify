param(
    [string]$HostName = "0.0.0.0",
    [int]$Port = 8080
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

python -m uvicorn demo_backend.app:app --reload --host $HostName --port $Port
