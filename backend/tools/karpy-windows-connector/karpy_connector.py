from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr

try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover - only happens when imported away from Windows/MT5
    mt5 = None


APP_STARTED_AT = time.time()
TOKEN = os.getenv("KARPY_CONNECTOR_TOKEN", "").strip()
MT5_PATH = os.getenv("KARPY_MT5_PATH", "").strip() or None
DEFAULT_TIMEOUT_MS = int(os.getenv("KARPY_MT5_TIMEOUT_MS", "60000"))

DERIV_COMPANIES = [
    {"broker": "Deriv (FX) Ltd", "directoryId": "DerivFX-Server"},
    {"broker": "Deriv (Mauritius) Ltd", "directoryId": "DerivMU-Server"},
    {"broker": "Deriv (SVG) LLC", "directoryId": "DerivSVG-Server"},
    {"broker": "Deriv (V) Ltd", "directoryId": "DerivVU-Server"},
    {"broker": "Deriv (BVI) Ltd.", "directoryId": "DerivBVI-Server"},
    {"broker": "Deriv Capital Contracts and Currencies L.L.C", "directoryId": "DerivUAE-Server"},
    {"broker": "Deriv Investments (Cayman) Limited", "directoryId": "DerivKY-Server"},
    {"broker": "Deriv Investments (Europe) Limited", "directoryId": "DerivMT-Server"},
    {"broker": "Deriv.com Limited", "directoryId": "Deriv"},
]


app = FastAPI(title="KARPy Windows MT5 Connector", version="0.1.0")


class SnapshotRequest(BaseModel):
    login: int
    password: SecretStr
    server: str = Field(min_length=2, max_length=160)
    broker: str = ""


class DisconnectRequest(BaseModel):
    login: int
    server: str


class OrderRequest(SnapshotRequest):
    symbol: str
    side: Literal["buy", "sell"]
    volume: float = Field(gt=0)
    price: float | None = None
    sl: float | None = None
    tp: float | None = None
    deviation: int = 20
    magic: int = 260723
    comment: str = Field(default="Trading system", max_length=31)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _needle(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _authorized(authorization: str | None) -> bool:
    if not TOKEN:
        return True
    return authorization == f"Bearer {TOKEN}"


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not _authorized(request.headers.get("authorization")):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await call_next(request)


def _require_mt5():
    if mt5 is None:
        raise HTTPException(status_code=503, detail={"message": "MetaTrader5 Python package is not installed."})


def _server_account_type(server: str) -> str:
    lower = server.lower()
    if "demo" in lower:
        return "demo"
    if "real" in lower or "live" in lower:
        return "real"
    return "unknown"


def _deriv_servers(broker: str) -> list[dict[str, str]]:
    target = _needle(broker)
    match = next((item for item in DERIV_COMPANIES if target in {_needle(item["broker"]), _needle(item["directoryId"])}), None)
    if not match:
        return []
    directory = match["directoryId"]
    if directory == "Deriv":
        names = ["Deriv-Demo", "Deriv-Server", "Deriv"]
    elif directory == "DerivSVG-Server":
        names = ["DerivSVG-Demo", "DerivSVG-Server", "DerivSVG-Server-02", "DerivSVG-Server-03"]
    else:
        base = directory.removesuffix("-Server")
        names = [f"{base}-Demo", directory]
    return [{"broker": match["broker"], "server": name, "accountType": _server_account_type(name)} for name in dict.fromkeys(names)]


def _initialize(login: int | None = None, password: str | None = None, server: str | None = None) -> None:
    _require_mt5()
    kwargs: dict[str, Any] = {"timeout": DEFAULT_TIMEOUT_MS}
    if MT5_PATH:
        kwargs["path"] = MT5_PATH
    if login and password and server:
        kwargs.update({"login": int(login), "password": password, "server": server})
    if not mt5.initialize(**kwargs):
        code, message = mt5.last_error()
        raise HTTPException(status_code=503, detail={"message": "MetaTrader 5 initialization failed.", "code": code, "error": message})


def _login(request: SnapshotRequest) -> None:
    _initialize()
    if not mt5.login(int(request.login), password=request.password.get_secret_value(), server=request.server, timeout=DEFAULT_TIMEOUT_MS):
        code, message = mt5.last_error()
        raise HTTPException(status_code=401, detail={"message": "MetaTrader 5 authorization failed.", "code": code, "error": message})


def _account_payload(request: SnapshotRequest) -> dict[str, Any]:
    account = mt5.account_info()
    terminal = mt5.terminal_info()
    if account is None:
        code, message = mt5.last_error()
        raise HTTPException(status_code=503, detail={"message": "Account information is unavailable.", "code": code, "error": message})
    data = account._asdict()
    positions = mt5.positions_get() or []
    deals = mt5.history_deals_get(0, int(time.time())) or []
    orders = mt5.orders_get() or []
    return {
        "account": {
            "provider": request.broker or data.get("company") or "",
            "broker": request.broker or data.get("company") or "",
            "login": str(data.get("login") or request.login),
            "server": request.server,
            "accountType": _server_account_type(request.server),
            "currency": data.get("currency") or "",
            "balance": data.get("balance") or 0,
            "equity": data.get("equity") or 0,
            "margin": data.get("margin") or 0,
            "freeMargin": data.get("margin_free") or 0,
            "profit": data.get("profit") or 0,
            "connected": True,
            "lastSynced": _now(),
            "terminalBuild": getattr(terminal, "build", None) if terminal else None,
        },
        "positions": [item._asdict() for item in positions],
        "orders": [item._asdict() for item in orders],
        "deals": [item._asdict() for item in deals[-500:]],
    }


@app.get("/v1/health")
def health() -> dict[str, Any]:
    available = mt5 is not None
    initialized = False
    terminal: dict[str, Any] | None = None
    if available:
        try:
            _initialize()
            initialized = True
            info = mt5.terminal_info()
            terminal = info._asdict() if info else None
        except Exception:
            initialized = False
        finally:
            if mt5 is not None:
                mt5.shutdown()
    return {
        "status": "connected" if initialized else "unavailable",
        "connected": initialized,
        "provider": "windows-connector",
        "mt5PackageAvailable": available,
        "terminal": terminal,
        "uptimeSeconds": int(time.time() - APP_STARTED_AT),
        "checkedAt": _now(),
    }


@app.get("/v1/brokers/discover")
def discover(query: str = "") -> dict[str, Any]:
    needle = _needle(query or "deriv")
    companies = [item for item in DERIV_COMPANIES if not needle or needle in _needle(item["broker"]) or needle in _needle(item["directoryId"])]
    return {"connected": True, "companies": companies, "source": "windows-connector"}


@app.get("/v1/brokers/servers")
def servers(broker: str) -> dict[str, Any]:
    return {"connected": True, "servers": _deriv_servers(broker), "source": "windows-connector"}


@app.post("/v1/accounts/snapshot")
def snapshot(request: SnapshotRequest) -> dict[str, Any]:
    try:
        _login(request)
        return {"connected": True, "data": _account_payload(request)}
    finally:
        if mt5 is not None:
            mt5.shutdown()


@app.post("/v1/accounts/disconnect")
def disconnect(_: DisconnectRequest) -> dict[str, Any]:
    if mt5 is not None:
        mt5.shutdown()
    return {"removed": True}


def _order_payload(request: OrderRequest, send: bool) -> dict[str, Any]:
    _login(request)
    tick = mt5.symbol_info_tick(request.symbol)
    if tick is None:
        raise HTTPException(status_code=422, detail={"message": f"Symbol {request.symbol} is unavailable."})
    order_type = mt5.ORDER_TYPE_BUY if request.side == "buy" else mt5.ORDER_TYPE_SELL
    price = request.price or (tick.ask if request.side == "buy" else tick.bid)
    body = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": request.symbol,
        "volume": request.volume,
        "type": order_type,
        "price": price,
        "sl": request.sl or 0.0,
        "tp": request.tp or 0.0,
        "deviation": request.deviation,
        "magic": request.magic,
        "comment": request.comment[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    check = mt5.order_check(body)
    check_data = check._asdict() if check else {}
    response: dict[str, Any] = {"checked": bool(check), "sent": False, "request": body, "check": check_data}
    if send:
        result = mt5.order_send(body)
        response.update({"sent": bool(result and result.retcode == mt5.TRADE_RETCODE_DONE), "result": result._asdict() if result else {}})
    return response


@app.post("/v1/accounts/order/check")
def order_check(request: OrderRequest) -> dict[str, Any]:
    try:
        return {"data": _order_payload(request, send=False)}
    finally:
        if mt5 is not None:
            mt5.shutdown()


@app.post("/v1/accounts/order/send")
def order_send(request: OrderRequest) -> dict[str, Any]:
    try:
        return {"data": _order_payload(request, send=True)}
    finally:
        if mt5 is not None:
            mt5.shutdown()
