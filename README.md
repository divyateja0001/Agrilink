# AgriLink

AgriLink is a local-first B2B agricultural marketplace prototype for farmers, buyers, FPO managers, and administrators. It implements the workflow from produce listing and buyer demand through explainable matching, quotation acceptance, transactional stock reservation, partial dispatch/receipt, and clearly simulated payment tracking.

## What is implemented

- Persistent PostgreSQL records, SQLAlchemy models, and an Alembic initial migration.
- Backend-enforced roles, organization isolation, explicit FPO-to-farmer authorization, expiring opaque sessions, hashed passwords, CSRF protection, restricted CORS, rate limiting, input validation, safe uploads, audit events, and account suspension.
- Farmer listings and inventory; buyer requirements and supplier discovery; delivery-aware deterministic matching; structured negotiation; atomic multi-supplier confirmation; reservations; partial fulfillment; tracking timelines; crop-damage complaints; completed-order reviews; notifications; exports; and optional Razorpay test checkout.
- Website-camera produce capture with one-time server tokens, browser geolocation, checksums, private exact coordinates, draft-before-publish behavior, and reversible archive/restore.
- Responsive React UI with desktop sidebar, mobile bottom navigation, accessible shadcn/ui primitives, complete English, Telugu, Hindi, and Tamil interfaces, locally bundled script-specific fonts, and generated produce imagery. The selected language persists across refreshes.
- An optional role-aware Mistral assistant for buyers, farmers, and FPO managers. Conversations persist in PostgreSQL/Supabase, context is limited to authorized records, and every suggested mutation remains a reviewable draft.
- One editable, verified review per completed order and reviewed organization. FPO-coordinated orders rate the supplying farmer and coordinating FPO together; marketplace readers see an anonymous “Verified buyer” label.
- Transactional outbox worker with compatible-demand/supply alerts, negotiation/order/review updates, optional browser push, locking, deduplication, exponential retry, exhaustion state, and a seeded fail-once recovery demonstration.

Simulated: seeded payment records and Razorpay test transactions never move real money; verification badges reflect only stored demo verification. Browser push is optional and in-app notifications always remain available. Device location is recorded evidence, not certified origin.

## Native Windows setup

Hosted Supabase PostgreSQL is the primary database. The existing local PostgreSQL setup remains an explicit offline fallback. Hosted mode requires internet while AgriLink is running; no Supabase API key, Auth client, or browser-side database credential is used.

Prerequisites: Windows PowerShell 5.1+, Node.js 22 LTS or newer, Python 3.13, and a free or paid Supabase project. PostgreSQL 16–18 is required only for the offline fallback. The scripts do not install services or change the machine-wide PowerShell execution policy.

```powershell
cd C:\ITHACK
py -3.13 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt

cd .\frontend
& 'C:\Program Files\nodejs\npm.cmd' ci
cd ..
Copy-Item .\backend\.env.example .\backend\.env
Copy-Item .\frontend\.env.example .\frontend\.env
```

### Supabase primary database

1. Create a Supabase project. In its dashboard, open **Connect** and copy the **Session pooler** URL on port `5432`; do not use the transaction pooler on `6543`.
2. Create a separate random password of at least 20 characters for the `agrilink_app` role. Percent-encode it when placing it inside a URL. For example: `[uri]::EscapeDataString('your-app-password')`. If the raw value contains `#` or spaces, quote it in `.env`.
3. Edit `backend\.env`:
   - Keep `AGRILINK_DATABASE_TARGET=supabase`.
   - Set `SUPABASE_ADMIN_URL` to the session-pooler URL using the dashboard-provided `postgres.PROJECT_REF` user.
   - Set `SUPABASE_APP_PASSWORD` to the unencoded dedicated-role password.
   - Set `SUPABASE_DATABASE_URL` to the same host with user `agrilink_app.PROJECT_REF` and the percent-encoded dedicated-role password.
   - Optionally set `SUPABASE_MIGRATION_URL` to a direct IPv6 URL that authenticates as `agrilink_app`; otherwise leave it blank.
   - Replace `SECRET_KEY` with a strong random local secret.

Run the one-time role/schema bootstrap, Alembic migration, and fresh fictional seed:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup-supabase.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-dev.ps1 -Database supabase
```

AgriLink uses TLS and a private `agrilink` schema owned by the restricted `agrilink_app` role. The frontend continues to access data only through Flask.

### Offline local fallback

Set `LOCAL_DATABASE_URL` in `backend\.env`, then provision and start the local database explicitly:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup-db.ps1 -AdminUser postgres -AppPassword 'your-long-local-app-password'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-dev.ps1 -Database local
```

Docker remains an optional local-database fallback: `docker compose up -d postgres`. It is never selected automatically.

Open **http://localhost:5173**. Database-aware readiness is available at **http://localhost:5000/api/health**. The launcher validates the selected target, runs migrations, starts Waitress, Vite, and the outbox worker directly, and writes logs under `logs\`. It refuses port conflicts and stale duplicate processes. Ctrl+C stops only its children; from another terminal use `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\stop-dev.ps1`.

### Optional Mistral assistant

Core marketplace workflows do not need Mistral. To enable the assistant for buyers, farmers, and FPO managers, edit `backend\.env` and add:

```dotenv
AI_ENABLED=true
MISTRAL_API_KEY=replace-with-your-mistral-api-key
MISTRAL_MODEL=mistral-small-latest
MISTRAL_TIMEOUT_SECONDS=20
MISTRAL_MAX_TOKENS=700
```

Restart `start-dev.ps1` after changing the file. Keep the key only in `backend\.env`; never place it in `frontend\.env`, source control, screenshots, or chat. The browser calls Flask, and Flask calls Mistral with a short timeout and structured output. Conversation ownership and role context are enforced by Flask; messages persist in the configured Supabase/local PostgreSQL database. If Mistral is disabled, rate-limited, or unavailable, AgriLink preserves the prompt and returns a clearly labelled rule-based fallback.

### Optional browser push alerts

In-app notifications work without push. To also receive system notifications while the tab is in the background, generate a local VAPID key pair:

```powershell
cd C:\ITHACK
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\generate-vapid.ps1
```

Copy the four printed values into `backend\.env`, replace `VAPID_SUBJECT` with your contact email, restart all services, then open Notifications and select **Enable browser alerts**. A backup private PEM is created under `backend\instance` and ignored by source control; the printed private value is a single-line deployment-safe encoding and must still be treated as a secret. Production hosting must provide the same VAPID public/private pair to both the web and worker services. Denied browser permission does not disable in-app alerts.

### Optional Razorpay test checkout

Add test credentials to `backend\.env`, restart AgriLink, and configure the Razorpay dashboard webhook as `/api/payments/razorpay-webhook`:

```dotenv
RAZORPAY_ENABLED=true
RAZORPAY_KEY_ID=rzp_test_replace_me
RAZORPAY_KEY_SECRET=replace_me
RAZORPAY_WEBHOOK_SECRET=replace_me
```

Flask creates the Razorpay order, verifies its signature, fetches its status, captures an authorized test payment when needed, and deduplicates signed webhook events. The payable amount uses received produce, deductions, the flat delivery charge, and prior verified payments. Live keys are intentionally rejected. The **Pay test** action appears only after at least some produce has been recorded as received and a positive amount is payable. Razorpay Checkout requires internet access; for a judge demo, choose a test payment method such as Netbanking and use the mock bank page's Success or Failure action. No real funds move in test mode.

### Website camera and location

New produce is saved as a draft. Publishing requires a photo taken through AgriLink plus browser location with 500 m accuracy or better. Camera/geolocation require `localhost` or HTTPS. Public buyers see locality and a recorded-location badge; device coordinates are not independent proof and may be spoofed on a compromised device.

## Render deployment

`Dockerfile` builds the Vite application and serves it from Flask on the same origin as `/api`. `render.yaml` defines one Gunicorn web service, one outbox worker, an Alembic pre-deploy migration, a database health check, and a 1 GB persistent upload disk. The disk and worker require paid Render resources; the disk limits the web service to one instance and causes brief downtime during a redeploy.

1. Complete `setup-supabase.ps1` once so the restricted `agrilink_app` role and `agrilink` schema exist.
2. Push this repository to a private Git provider repository. Confirm that `backend/.env` is not tracked.
3. In Render, create a **Blueprint** from the repository. Render reads `render.yaml` from the root.
4. Enter the prompted secrets:
   - Web: `SUPABASE_DATABASE_URL`, a new `DEMO_PASSWORD`, and a rotated `MISTRAL_API_KEY`.
   - Worker: the same `SUPABASE_DATABASE_URL`.
5. Confirm the first deploy passes `/api/health`, then open the generated `agrilink-web.onrender.com` URL.

Do not paste local `.env` files into source control. The provided Blueprint disables preview environments, uses secure cookies and proxy handling, and seeds fictional accounts only because `DEMO_MODE=true` is explicit for the hackathon web service. For a real marketplace, set `DEMO_MODE=false`, remove the initial demo seed hook, rotate all secrets, and provision the first administrator separately.

Useful deployment checks:

```powershell
docker build -t agrilink:local .
```

The image build is a dependency and static-bundle check. To run it locally, supply a container-reachable Supabase URL (or use `host.docker.internal` for a separately configured local PostgreSQL server); a Windows `127.0.0.1` database URL points back into the container and will not reach the host database.

The Render disk is mounted at `/var/data/agrilink/uploads`; local Windows uploads remain in `backend\instance\uploads`.

## Demo accounts

All sample data and prices are fictional. Every account uses password `AgriLinkDemo!2026`.

| Role | Email |
|---|---|
| Buyer | `buyer@agrilink.demo` |
| Farmer A/B/C | `farmer.a@agrilink.demo`, `farmer.b@agrilink.demo`, `farmer.c@agrilink.demo` |
| FPO manager | `fpo@agrilink.demo` |
| Driver 1/2 | `driver@agrilink.demo`, `driver.two@agrilink.demo` |
| Unrelated buyer | `outsider@agrilink.demo` |
| Admin | `admin@agrilink.demo` |

Reset and credential repair are deliberately restricted to demo mode:

```powershell
$env:AGRILINK_ENV='demo'
cd C:\ITHACK\backend
& ..\.venv\Scripts\python.exe .\seed.py --reset --confirm-demo-reset
& ..\.venv\Scripts\python.exe .\seed.py --repair-demo-accounts --confirm-demo-repair
```

The repair command preserves marketplace records, restores only the seven known fictional accounts, refreshes their password hashes, and revokes old sessions. In the admin UI, a visible Active/Suspended badge and confirmed Restore action handle individual accounts.

## Five-minute demonstration

1. Sign in as the buyer and open Requirements. The date-relative request is 1,000 kg Arka Rakshak tomatoes.
2. Open Matches. Explain the deterministic 50/30/20 formula and the 400 + 350 + 250 kg preview; point out that preview reserves nothing.
3. Open Negotiations. Compare the three tomato proposals, send a private message or structured counteroffer, and inspect the immutable offer history. Select agreed proposals and confirm. One database transaction creates separate supplier orders and reservations. Repeating the same API confirmation key returns its stored result rather than duplicating stock.
4. Sign in as Farmers A and B in separate sessions. Their tomato available stock is zero after confirmation; Farmer C retains 250 kg. Record partial dispatches from Orders.
5. In a phone-sized browser, sign in as `driver@agrilink.demo`, open **My deliveries**, choose **Simulated tracking**, and select **Start Delivery**. In a separate buyer session, open **Track vehicles**, select that dispatch, and show the moving recorded marker, simulated label, vehicle, pickup, destination, and last-update time. Select **Stop Sharing** to demonstrate the disconnected state; **Mark Arrival** remains separate from buyer receipt.
6. Return as the buyer and record a partial receipt. Show the outstanding balance, delivery timeline, crop-damage report, and optional Razorpay test checkout for the received net amount.
7. Sign in as the FPO manager to show explicitly authorized member supply. Sign in as the unrelated buyer to demonstrate that private orders are absent/forbidden. Sign in as admin to show participants, suspension, disputes, and audit history.
8. Open Notifications after the worker runs: compatible new supply, requirements, and quotation updates are targeted to the relevant users. The seeded job intentionally fails once and then succeeds without duplicate effects. Optionally enable browser alerts.
9. Complete a delivery, open Review & Feedback as the buyer, rate the supplier, then show the anonymous aggregate on the supplier card and the farmer’s Ratings & Reviews page.
10. Open the assistant as a buyer, farmer, or FPO manager and ask, “How does AgriLink prevent overselling?” Refresh to show persistent history. Mistral answers when the provider is available; the grounded local fallback keeps core AgriLink judge questions answerable during provider outages. The assistant cannot reserve inventory or execute marketplace actions.

## Dispatch vehicle tracking

Tracking belongs to an individual dispatch, so an order fulfilled by several suppliers or vehicles has separate position histories. Suppliers select an active driver account while recording a dispatch. Drivers have a dedicated role and can access only their assigned dispatches; driver membership does not satisfy farmer, buyer, FPO, or admin authorization checks.

The driver chooses one of two visibly separate modes:

- **Real GPS tracking** requests browser geolocation only after **Start Delivery** is selected. While the driver page is visible, the browser captures and sends a coordinate about every seven seconds. **Stop Sharing**, **Mark Arrival**, leaving the page, or completing the delivery stops local collection.
- **Simulated tracking** follows a sample straight path and is always labelled as simulated in both driver and buyer views. It is enabled by default only for development/demo environments.

Buyer tracking polls only while the tracking page is open. A position older than 20 seconds is shown as stale/disconnected, and the vehicle remains at its last recorded point; AgriLink does not extrapolate movement. Arrival is not a receipt and never changes received quantities. No traffic ETA is claimed.

The prototype uses locally bundled [Leaflet 1.9.4](https://leafletjs.com/reference.html) with the public OpenStreetMap standard tile endpoint through `frontend/src/lib/mapProvider.ts`. OpenStreetMap's standard service has no usage fee, API key, or SLA, but its [tile usage policy](https://operations.osmfoundation.org/policies/tiles/) requires the exact HTTPS endpoint, visible `© OpenStreetMap contributors` attribution, normal browser caching, and prohibits bulk/offline prefetching. The app displays attribution on-map and performs no prefetching. Before production traffic, configure a commercial provider or operated tile service in `frontend\.env`; restrict any public browser token by allowed web origin. Never expose a provider's private/server key to Vite or client code.

For an existing demo database after applying migration `20260911_0005`, add the driver-only accounts and assign existing dispatches without resetting other data:

```powershell
$env:AGRILINK_ENV='demo'
cd C:\ITHACK\backend
& ..\.venv\Scripts\python.exe .\seed.py --ensure-tracking-demo --confirm-demo-tracking
```

### Phone GPS over HTTPS

Phone browsers require a secure context for geolocation. AgriLink does not generate or trust certificates automatically. For a local judge demo, place the laptop and phone on the same private Wi-Fi, install `mkcert` yourself, and explicitly create a trusted development certificate:

```powershell
cd C:\ITHACK
New-Item -ItemType Directory -Force .\certs
$wifiIp = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } | Select-Object -First 1).IPAddress
mkcert -install
mkcert -cert-file .\certs\agrilink-local.pem -key-file .\certs\agrilink-local-key.pem localhost 127.0.0.1 $wifiIp
.\start-dev.ps1 -Database supabase -PhoneHttps -LanAddress $wifiIp
```

Open `https://<laptop-Wi-Fi-IP>:5173` on the phone and sign in with `driver@agrilink.demo`. The phone must trust the mkcert local root; `mkcert -CAROOT` shows its location so you can transfer only `rootCA.pem` to your own test phone and install it as a user CA. Keep `rootCA-key.pem` private and never transfer it. Windows Firewall may require you to explicitly allow Node.js on the private network. These steps change trust settings only when you run `mkcert -install` or install the CA yourself; AgriLink scripts do not change firewall rules, certificate stores, or PowerShell policy.

Mobile browsers can suspend timers and geolocation when the screen locks, another app opens, or the browser is backgrounded. This prototype therefore promises active-page tracking only. Production background tracking requires a consented native mobile implementation and platform-specific location permissions.

## Architecture and integrity rules

`frontend/` is a single Vite SPA. `backend/app/routes/` contains modular Flask APIs, `services/` contains matching, auditing, order transaction, and outbox logic, and `worker.py` is the only background process. SQLAlchemy connects to hosted Supabase PostgreSQL by default or local PostgreSQL when explicitly selected. Images use `backend/instance/uploads` locally and the configured Render disk in deployment; only their references are stored in PostgreSQL.

Amounts are integer paise and quantities are PostgreSQL numeric kilograms. Confirmation locks the requirement and sorted lot rows, revalidates accepted revisions and remaining demand, then writes order snapshots, reservations, audits, and outbox jobs atomically. Idempotency is scoped to actor + operation + key and conflicting payload reuse returns 409. Available stock is on-hand minus active unshipped reservations; dispatch lowers both physical on-hand and reservation remainder; cancellation may release only unshipped stock. Receipt totals cannot exceed dispatch totals. Optimistic version fields reject stale listing/requirement edits. Fulfillment and payment states are independent.

Matching first filters crop, optional variety, minimum grade, availability dates, stock, delivery mode, and supported delivery area. It ranks eligible lots using quantity coverage (50 points), asking-price fit (30), and delivery fit (20). It is deterministic rules—not a trained AI model. Distance is used only with both coordinate sets and is labelled as a straight-line estimate.

## Tests

Use a disposable local PostgreSQL database owned by `agrilink_app` for destructive integration tests. Supabase receives a non-destructive migration, connection, and workflow smoke test after local tests pass.

```powershell
cd C:\ITHACK\backend
$env:TEST_DATABASE_URL='postgresql+psycopg://agrilink_app:password@127.0.0.1:5432/agrilink_test'
& ..\.venv\Scripts\python.exe -m pytest --cov=app

cd ..\frontend
& 'C:\Program Files\nodejs\npm.cmd' run lint
& 'C:\Program Files\nodejs\npm.cmd' run build
& 'C:\Program Files\nodejs\npx.cmd' playwright install chromium
& 'C:\Program Files\nodejs\npm.cmd' run test:e2e
```

On Windows, installed Microsoft Edge can be used without downloading Playwright Chromium:

```powershell
$env:PLAYWRIGHT_CHANNEL='msedge'
& 'C:\Program Files\nodejs\npm.cmd' run test:e2e
```

Playwright defines 360, 390, 768, 1280, and 1536 px projects and uses separate authenticated browser contexts for buyer, farmer, FPO, and admin. Backend integration tests intentionally refuse to substitute SQLite.

Latest local verification on Windows with PostgreSQL and Playwright Chromium: **30 backend integration tests passed** and **12 targeted Playwright scenarios passed**. The browser run includes a 390 px driver session, a separate 1280 px buyer tracking session, and a mocked-provider Razorpay Checkout/verification browser flow, plus the nine established buyer/farmer/FPO/admin, sign-out, negotiation, delivery, complaint, review, and listing scenarios. New backend coverage verifies two dispatches per order, assigned-driver isolation, unrelated-buyer denial, invalid and delayed coordinates, duplicate prevention, stop behavior, disconnected status, arrival without receipt, Razorpay order creation, signature verification, and authorized-payment capture. Frontend lint completed with only existing shadcn fast-refresh export warnings, and the production TypeScript/Vite build passed. Screenshots of the mobile driver and desktop buyer tracking views were inspected without horizontal overflow or overlapping controls. The Mistral key is loaded and requests use the current SDK, but the provider was unavailable/rate-limited during local runs; AgriLink persisted the questions and the expanded grounded fallback answered the judge-style workflow question successfully. Physical phone GPS, phone certificate trust, public browser push, hosted Supabase connectivity, live map-tile availability, Razorpay's external sandbox, and a public Razorpay webhook require external network/hardware and were not executed in this run.

## Troubleshooting

- `npm.ps1 cannot be loaded`: use `npm.cmd` exactly as shown; do not change system execution policy.
- `pg_isready ... no response`: verify the PostgreSQL Windows service, its actual data directory, `listen_addresses`, and port. The service registered on this machine referenced `C:\Program Files\PostgreSQL\18\data`, which was absent during inspection.
- `Supabase is unreachable`: confirm the project is active, internet access works, the copied host and `PROJECT_REF` are exact, the password is percent-encoded in URLs, and the session pooler uses port 5432.
- `transaction pooling on port 6543`: copy the Session pooler URL from Supabase Connect. AgriLink deliberately rejects transaction mode because its persistent worker and API use long-lived SQLAlchemy sessions.
- `password authentication failed`: confirm `SUPABASE_APP_PASSWORD` is unencoded while the same password is percent-encoded inside `SUPABASE_DATABASE_URL`.
- Port 5000/5173 conflict: stop the owning application yourself. AgriLink reports the conflict and will not terminate unrelated processes.
- `401`: sign in again; sessions expire after eight hours. `403 csrf_failed`: refresh once to obtain a new synchronizer token.
- Correct demo password still reports a login failure: the account may be suspended. Sign in as admin, check the participant status badge, and use Restore; for demo-wide recovery use the guarded repair command above.
- Farmer offer does not submit: wait for compatible lots to load and read the inline error. If an offer is already waiting for the buyer, use **View negotiation**; a second supplier offer is intentionally blocked until the buyer responds.
- Sign-out appears stuck: refresh once, then verify the API at `/api/auth/session`. The client now clears private query caches immediately and the server invalidates the opaque session before redirecting to `/login`.
- Procurement assistant says it is not configured: set all `AI_*`/`MISTRAL_*` values above in `backend\.env` and restart all three development processes. A Mistral 401 means the key is invalid; 402 means account credits/billing; 429 means provider rate limiting.
- Browser alert button says push is not configured: run `generate-vapid.ps1`, copy its output into `backend\.env`, and restart both Flask and the worker. If permission was denied, reset Notifications permissions for `localhost` in the browser; in-app alerts still work.
- `409 stock_unavailable` or `stale_update`: refresh the relevant requirement/listing; another accepted order or edit won the race.
- Worker failures: inspect `logs\worker.err.log` and `outbox_jobs`. Temporary jobs retry up to five attempts; exhausted jobs remain visible for operational recovery.
- Camera does not open: use `http://localhost:5173` or HTTPS, allow both camera and location, close other camera applications, and retry. Failed capture keeps the listing as a draft.
- Razorpay button is absent: first record a partial or complete receipt; only received value can become payable. If disabled, add valid `rzp_test_` credentials and restart AgriLink. If Checkout reports unavailable, allow `checkout.razorpay.com` in browser privacy/ad-blocking tools and confirm internet access. Live credentials are rejected.
- Uploaded image missing: confirm the referenced file exists in `backend\instance\uploads` and is JPEG, PNG, or WebP within the configured size limit.

## Known prototype limitations

The in-memory rate limiter is single-process. Browser GPS/camera evidence is not tamper-proof. Mistral advice is not autonomous procurement, and persistent history has no semantic search or provider-side moderation console. Browser push depends on browser/vendor push infrastructure and HTTPS outside localhost. Razorpay is test-only; no real payment, tax invoice, carrier, email/SMS, certification, or quality-inspection integration is present. Complaint images use the application upload disk; production should add object storage and malware scanning. FPO authorization remains seeded/admin-controlled. Deadline alerts are request-time calculations rather than a distributed scheduler. Voice entry, offline drafts, and QR history remain deferred.
