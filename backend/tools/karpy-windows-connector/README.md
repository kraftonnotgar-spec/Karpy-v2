# KARPy Windows MT5 Connector

This optional connector runs on a Windows/RDP machine where MetaTrader 5 is installed. KARPy FastAPI calls it through the same MT5 provider interface used by future terminal-pool and MetaApi gateways.

Use it when:

- the customer or operator has a Windows machine with MT5 installed;
- you want a direct MetaTrader5 Python bridge for one active terminal session;
- you need read-only snapshots, broker discovery, order checks, and controlled order submission.

Important production note: one connector process controls one MT5 terminal session. For many always-on customers or autonomous trading, run one isolated connector/terminal worker per account, or use a managed provider such as MetaApi.

## Install

Open PowerShell on the Windows VPS/RDP account that can launch MT5:

```powershell
cd C:\karpy\tools\karpy-windows-connector
py -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Run

```powershell
$env:KARPY_CONNECTOR_TOKEN="change-this-long-random-token"
$env:KARPY_MT5_PATH="C:\Program Files\MetaTrader 5\terminal64.exe"
.\Start-KARPyConnector.ps1
```

KARPy admin settings:

- Mode: `Windows Connector`
- Gateway base URL: `http://YOUR-WINDOWS-IP:8795`
- Gateway token: the same `KARPY_CONNECTOR_TOKEN`
- Verify TLS certificates: off only for private HTTP testing; on for HTTPS production.

## Endpoints

- `GET /v1/health`
- `GET /v1/brokers/discover?query=deriv`
- `GET /v1/brokers/servers?broker=Deriv%20(SVG)%20LLC`
- `POST /v1/accounts/snapshot`
- `POST /v1/accounts/disconnect`
- `POST /v1/accounts/order/check`
- `POST /v1/accounts/order/send`

All account passwords are accepted per request and are not stored by this connector.
