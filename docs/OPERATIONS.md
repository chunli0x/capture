# Capture — Operations runbook (restart + health)

Owner: operator (PM + Lisa). Applies to the live devnet deployment on the VPS.

## Services (systemd)

| Unit | Repo | What it runs | Port |
|---|---|---|---|
| `capture-seeker-usdc` | `/home/hermes/capture-usdc` (chunli0x/capture) | FastAPI backend, **USDC (Colosseum)** | `172.18.0.1:8102` |
| `capture-seeker-usdc-worker` | `/home/hermes/capture-usdc` | Settlement worker (mint/slash/anchor) | — |
| `capture-seeker` | `/home/hermes/capture-clock-in` | FastAPI backend, SKR variant | `172.18.0.1:8101` |
| `capture-seeker-worker` | `/home/hermes/capture-clock-in` | Settlement worker (SKR) | — |

Both backends read `backend/.env` via `EnvironmentFile`. Both workers load the
verifier + treasury keypairs from the key files pointed to by that env.

## Restart the USDC (Colosseum) backend

```bash
# backend only
sudo systemctl restart capture-seeker-usdc

# worker only
sudo systemctl restart capture-seeker-usdc-worker

# both (full restart)
sudo systemctl restart capture-seeker-usdc capture-seeker-usdc-worker
```

`Restart=always` and `RestartSec=3` are set, so a crash self-heals; the above is
for a deliberate code/config deploy.

## Verify after restart

```bash
# service is active
systemctl is-active capture-seeker-usdc          # -> active

# readiness probe (200 = green)
curl -s http://172.18.0.1:8102/health
```

A green response has `"production_ready": true` with
`"checks":{"database":"ok","schema":"applied","chain":"reachable"}`. Any 503 means
the named check failed (DB down / schema not applied / chain unreachable).

**Verified 2026-10-29:** restart → `active` → `/health` returned
`production_ready: true` (database ok, schema applied, chain reachable).

## Deploy a code change

1. Edit files in `/home/hermes/capture-usdc`.
2. `cd /home/hermes/capture-usdc/backend && .venv/bin/python -m pytest -q` (green).
3. `sudo systemctl restart capture-seeker-usdc capture-seeker-usdc-worker`.
4. `curl -s http://172.18.0.1:8102/health` → confirm `production_ready: true`.

## Logs

```bash
sudo journalctl -u capture-seeker-usdc -n 50 --no-pager
sudo journalctl -u capture-seeker-usdc-worker -n 50 --no-pager
```

The worker logs `Worker signer readiness: {'verifier': 'ready', 'treasury': 'ready'}`
on startup — if either is not `ready`, the corresponding keypair file is missing
or does not match the configured public key.

## Known gap (blocked on Lisa)

The public `usdc.capture.magnumopus.ai` subdomain has **no DNS record**, so the
USDC backend is reachable only on the host (`172.18.0.1:8102`) / through the
Caddy route that references it. The main `capture.magnumopus.ai` domain currently
proxies to the **SKR** backend on `8101`. DNS + the planned domain move are
documented in `capture-infra/DOMAIN-MOVE-RUNBOOK.md` and need registrar/Hetzner
access.
