# KARPy Terminal Pool

The terminal pool is the fully self-hosted production design for autonomous MT5 execution.

Each active customer account must run in an isolated worker:

```text
KARPy FastAPI
  -> account execution queue
  -> dedicated worker process
  -> dedicated portable MT5 terminal directory
  -> order_check/order_send
  -> audit event + WebSocket update
```

Do not share one MT5 desktop terminal across multiple automated accounts. A shared terminal can switch active accounts and is only acceptable for light read-only polling.

The current FastAPI provider interface already supports `terminal-pool` as a gateway mode. A pool implementation should expose the same connector endpoints as `tools/karpy-windows-connector`:

- `/v1/health`
- `/v1/brokers/discover`
- `/v1/brokers/servers`
- `/v1/accounts/snapshot`
- `/v1/accounts/disconnect`
- `/v1/accounts/order/check`
- `/v1/accounts/order/send`

Recommended worker rules:

- one portable terminal folder per MT5 login/server;
- one OS process lock per account;
- one execution queue per account;
- no `login()` switching inside an order-capable worker;
- heartbeat and last-error state in Redis or the KARPy database;
- exponential reconnect, never immediate hard disconnect after a single failed poll;
- order comments use the configured trading-system name plus signal id only.
