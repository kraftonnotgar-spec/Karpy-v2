$ErrorActionPreference = "Stop"

if (-not $env:KARPY_CONNECTOR_HOST) {
    $env:KARPY_CONNECTOR_HOST = "0.0.0.0"
}

if (-not $env:KARPY_CONNECTOR_PORT) {
    $env:KARPY_CONNECTOR_PORT = "8795"
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Virtual environment not found. Run: py -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
    exit 1
}

.\.venv\Scripts\python.exe -m uvicorn karpy_connector:app --host $env:KARPY_CONNECTOR_HOST --port $env:KARPY_CONNECTOR_PORT
