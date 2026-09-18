# Recur Security TODO

Agent↔server communication was originally unauthenticated and unauthorized: any host on
the network could register any `agent_id` (defaulting to the hostname), submit status
reports, or call admin endpoints such as `DELETE /api/v1/agents/{id}`.

This file tracks the agreed remediation. Status legend:
`[x]` done · `[ ]` open · `[~]` in progress.

| # | Mechanism | Status |
|---|-----------|--------|
| 1 | Per-agent bearer tokens | [x] |
| 2 | TLS for agent↔server traffic | [ ] |
| 3 | Separate agent vs admin authorization | [ ] |
| 4 | Request signing / replay protection | [ ] |
| 5 | Rate limiting | [ ] |
| 6 | Server hardening | [x] |
| 7 | Network-layer controls | [ ] |

---

## 1. Per-agent bearer tokens — DONE

First registration issues a random 256-bit token; the server stores only a SHA-256 hash
(`agents.token_hash`). The agent stores the plaintext in `/etc/recur/agent.token` (0600)
and sends `Authorization: Bearer <token>` on every call.

- Server: `server/app/security.py` (`authenticate_agent`, `verify_enrollment`),
  `server/app/routers/agents.py` (register issues the token once, in the response body as
  `agent_token`; heartbeat verifies it), `server/app/routers/status.py` (report
  `agent_id` must match the token owner).
- Enrollment: when `RECUR_ENROLLMENT_TOKEN` is set on the server, new registrations
  require it (sent by the agent as `X-Recur-Enrollment-Token`, from
  `RECUR_AGENT_ENROLLMENT_TOKEN`). Without it, registration is open (dev mode) and the
  server logs a warning on each open registration.
- Agent: `agent/recur_agent.py` — token load/save, auth header, and self-heal (a 401/403
  deletes the local token file and re-registers on the next cycle).
- DB migration: `init_db()` in `server/app/database.py` adds the column to existing
  databases (SQLite and PostgreSQL).

Known limitation (tracked under #3): admin endpoints (list/get/delete/trigger) are still
unauthenticated.

## 2. TLS for agent↔server traffic — OPEN

- Terminate TLS in front of uvicorn (Caddy/Traefik/nginx) or use uvicorn
  `ssl_keyfile`/`ssl_certfile`.
- Agent: pass an `ssl.SSLContext` (CA file via `RECUR_AGENT_CA_FILE`, or cert pinning for
  offline LAN) to `urlopen` in `http_request()`; reject plain `http://` by default
  (allow `http://localhost` for local dev).

## 3. Separate agent vs admin authorization — OPEN

- Split scopes: agent-scoped (register, status, own heartbeat) vs admin-scoped
  (`GET/DELETE /agents`, `GET /agents/{id}`, `GET /agents/{id}/systems`,
  `POST /agents/{id}/check`, systems CRUD).
- Admins get a separate credential (e.g. `RECUR_ADMIN_TOKEN` env var + dependency) or per-user
  tokens/roles; agents must never be able to delete or enumerate agents.

## 4. Request signing / replay protection — OPEN

- HMAC-SHA256 or Ed25519 (keypair generated at install, public key registered) over
  `method + path + timestamp + nonce + body`.
- Server rejects stale timestamps (>5 min) and replayed nonces; Redis (already in compose,
  `production` profile) is the natural nonce store.

## 5. Rate limiting — OPEN

- `slowapi` (or a small in-memory limiter) on `/agents/register`, `/status`,
  `/agents/{id}/heartbeat`; 429 with `Retry-After`. Protects SQLite from flooding.

## 6. Server hardening — DONE

- CORS: off by default (`CORS_ORIGINS` empty); only installed when configured;
  `allow_credentials` forced off when `*` is used.
- Docs: `/docs`, `/redoc`, `/openapi.json` disabled unless `DEBUG=true`.
- Bind: standalone default `HOST` is now `127.0.0.1` (put a reverse proxy in front for
  network access); docker mode explicitly sets `HOST=0.0.0.0` in compose.
- Logging: failed authentications are logged with client IP; agent registration and
  deletion are audit-logged with client IP.

## 7. Network-layer controls — OPEN

- Firewall `:8000` to known agent IPs; VLAN segmentation for the offline-LAN deployment.
- mTLS at the proxy if the LAN itself is untrusted.
