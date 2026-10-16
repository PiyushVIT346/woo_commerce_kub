# WooCommerce hosting + Team MCP Gateway

Everything runs on Kubernetes and is deployed with one Helm chart (`charts/platform`).
Local and production differ only in `values-local.yaml` / `values-prod.yaml`.

```
Browser ──► Ingress ─┬─ shop.<domain>  ──► WordPress + WooCommerce ◄── MariaDB (PVC)
                     └─ admin.<domain> ─┬─ /      ► Dashboard (React, nginx)
                                        ├─ /api   ► Gateway ──► Postgres (PVC)
                                        └─ /mcp   ► Gateway (MCP server)
Gateway (MCP client) ──► woo-mcp ──REST──► WordPress     (ClusterIP only, NetworkPolicy: gateway only)
                     ├─► demo-notes                    (ClusterIP only)
                     └─► demo-clock                    (ClusterIP only)
```


## Start locally (about 5-10 minutes the first time)
```bash
make up LLM_API_KEY=<your-key>            # Linux/macOS
```
```powershell
.\scripts\up.ps1 -LlmApiKey <your-key>   # Windows (add -LlmBaseUrl/-LlmModel for Gemini or Ollama)
```
Both: cluster + build images + import + helm install + print credentials.
`make up` runs: `k3d cluster create` (host port 8080 -> ingress port 80), `docker build` for 4 images,
`k3d image import`, `helm upgrade --install ... -f values-local.yaml --wait`. A post-install Job installs WordPress,
WooCommerce, enables Cash on Delivery, adds a shipping method and a sample product, and installs the REST key.

| What | URL |
|---|---|
| Storefront | http://shop.localtest.me:8080 |
| WP admin | http://shop.localtest.me:8080/wp-admin (user `admin`) |
| Dashboard | http://admin.localtest.me:8080 (user `admin@example.com`) |
| MCP endpoint | http://admin.localtest.me:8080/mcp |

Passwords are generated into the `platform-secrets` Secret; `make creds` prints them.

**Local domain approach:** `*.localtest.me` resolves to 127.0.0.1 in public DNS, so no `/etc/hosts` edits.
If your DNS blocks that (DNS-rebinding protection), add `127.0.0.1 shop.localtest.me admin.localtest.me` to your hosts file.

**LLM choices** (any OpenAI-compatible API). Override at deploy: `--set gateway.llm.baseUrl=... --set gateway.llm.model=...`
- Groq (default): `https://api.groq.com/openai/v1`, `llama-3.3-70b-versatile`
- Gemini: `https://generativelanguage.googleapis.com/v1beta/openai`, `gemini-2.0-flash`
- Ollama on your machine: `http://host.k3d.internal:11434/v1`, e.g. `qwen2.5:7b` (no key needed; pick a model with tool support)

## Demo script (maps to the definition of done)
1. **Store:** open the storefront, add "Sample T-Shirt" to the cart, check out with Cash on delivery. Open WP admin > WooCommerce > Orders and confirm it.
2. **Users:** sign in to the dashboard as admin. *Members* > create an invite link for `a@example.com` and `b@example.com`; open each link (private window) and set passwords.
3. **User A, chat:** *Chat*: "Create a product called Travel Mug priced 12.50". Check the storefront. Buy it by hand. Ask "What orders came in today?".
4. **User B, external client:** as B, *API keys* > Generate; the page shows ready-made config.
   `claude mcp add --transport http team-gateway http://admin.localtest.me:8080/mcp --header "Authorization: Bearer gw_..."`
   or MCP Inspector (`npx @modelcontextprotocol/inspector`, transport Streamable HTTP, same URL and header). Quick check: `scripts/smoke.sh gw_...`.
   Ask "what orders came in today?". Two-server prompt: "Get the current time in Asia/Kolkata and save it as a note, then list notes" (`clock__get_time` + `notes__add_note`; the time tool takes `timezone_name`).
5. **Revoke:** admin > *Members* > All API keys > Revoke B's key. B's next call returns 401.
6. **Disable a server:** *Servers* > Disable "Notes". Its tools vanish from chat and from B's `tools/list` (after reconnect/refresh).
7. **Kill a pod:** `kubectl -n platform delete pod -l app.kubernetes.io/name=demo-clock --force --grace-period=0` and quickly scale to hold it down:
   `kubectl -n platform scale deploy/demo-clock --replicas=0`. Within ~15s the dashboard shows it Unreachable while WooCommerce keeps working. Restore with `--replicas=1`.
8. **Audit:** *Audit log* shows every call with user, via (chat/mcp), server, tool, duration and outcome.

Adding a third-party server: *Servers* > Add server (name, slug, `https://.../mcp`, optional bearer/header credential).

## Production on a VPS (k3s)
```bash
curl -sfL https://get.k3s.io | sh -                      # Traefik + local-path storage + NetworkPolicy included
# cert-manager + a ClusterIssuer named letsencrypt-prod (see cert-manager docs)
# DNS: A records for shop.example.com and admin.example.com -> VPS IP
docker build/push the 4 images to your registry (tag 1.0.0), then:
helm upgrade --install platform charts/platform -n platform --create-namespace \
  -f charts/platform/values-prod.yaml --set secrets.llmApiKey=$LLM_API_KEY
```
Edit `values-prod.yaml` first (hosts, registry, tag, email, timezone). For private registries create an imagePullSecret and add it to the service account.
To manage secrets yourself, create a Secret and set `existingSecret: my-secret` with keys:
`mariadb-root-password, mariadb-password, wp-admin-password, woo-consumer-key, woo-consumer-secret, upstream-token, postgres-password, session-secret, encryption-key, dashboard-admin-password, llm-api-key`.

## Stack
Python 3.12 for all backend code: **gateway** = FastAPI + asyncpg + the official `mcp` SDK (low-level server for `/mcp`, streamable-HTTP client for upstreams); **woo-mcp** and **demo-mcp** = `FastMCP` over Streamable HTTP. Frontend = React (Vite) served by nginx. Postgres + MariaDB with persistent volumes.

## Design notes
- **Store access (woo-mcp):** WooCommerce REST API (`/wp-json/wc/v3`) over the in-cluster Service. It is the supported, stateless contract, needs no exec/RBAC into the WordPress pod (unlike WP-CLI), and is easy to test. It sends `X-Forwarded-Proto: https` on this internal hop because WooCommerce only accepts key/secret Basic auth over "SSL". WP-CLI is used once, only in the bootstrap Job.
- **Tool names:** every tool is exposed as `<server-slug>__<tool>` (e.g. `woocommerce__list_orders`). Slugs are unique, immutable and cannot contain `_`, so routing splits on the first `__`. The prefix is always applied, so adding a server never renames existing tools. `notes` and `clock` both expose `echo` to demonstrate this.
- **Resilience:** tool lists come from a per-server cache refreshed every 15s (5s timeout); unreachable servers are dropped from listings. Calls use a fresh connection with a 20s timeout and return `isError` results with a clear message. One dead upstream never blocks the others.
- **Secrets:** upstream credentials are AES-256-GCM encrypted in Postgres and never returned by any API. API keys (`gw_...`) are stored as SHA-256 hashes, shown once, and checked on every request. Passwords use bcrypt. All platform secrets live in a Kubernetes Secret (generated by Helm, kept across upgrades).
- **Upstream isolation:** upstream Services are ClusterIP with no Ingress; a NetworkPolicy allows only gateway pods; each also requires a bearer token that only the gateway holds (stored encrypted as the seeded servers' credential). k3s/k3d enforce NetworkPolicy; plain Kind does not without Calico.
- **Audit and chat:** chat and external clients both go through `core.callTool`, which writes the audit row; chat acts as the logged-in user.

## Known limits
Demo notes are in memory. Chat is non-streaming. The gateway re-lists tools on each request, so clients see changes on their next `tools/list`. Local PVCs use local-path (RWO); the bootstrap Job shares the WordPress volume, which works on a single node.
