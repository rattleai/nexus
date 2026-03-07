# Mobile-First Production Implementation Plan

**Date:** 2026-03-07
**Scope:** All layers — Frontend, Backend, Database, Infrastructure, DevOps
**Baseline Score:** 5/10 (mobile-first readiness)
**Target Score:** 9/10

---

## Table of Contents

1. [Phase 1 — Foundation & Quick Wins (Weeks 1–2)](#phase-1--foundation--quick-wins-weeks-12)
2. [Phase 2 — Mobile-Optimized UI (Weeks 3–5)](#phase-2--mobile-optimized-ui-weeks-35)
3. [Phase 3 — API & Backend Mobile Optimization (Weeks 4–6)](#phase-3--api--backend-mobile-optimization-weeks-46)
4. [Phase 4 — Offline-First & Real-Time (Weeks 6–9)](#phase-4--offline-first--real-time-weeks-69)
5. [Phase 5 — Infrastructure & Performance (Weeks 7–10)](#phase-5--infrastructure--performance-weeks-710)
6. [Phase 6 — Native-Ready & Production Hardening (Weeks 10–14)](#phase-6--native-ready--production-hardening-weeks-1014)
7. [Cross-Cutting Concerns](#cross-cutting-concerns)
8. [Success Criteria](#success-criteria)
9. [Risk Register](#risk-register)

---

## Phase 1 — Foundation & Quick Wins (Weeks 1–2)

### 1.1 PWA Support

**Problem:** No service worker, no web app manifest — the app cannot be installed on mobile home screens or work offline.

**Implementation:**

1. **Install `vite-plugin-pwa`**
   - File: `frontend/package.json`
   - Add `vite-plugin-pwa` as a dev dependency
   - This integrates Workbox for service worker generation

2. **Configure PWA plugin in Vite**
   - File: `frontend/vite.config.ts`
   - Add `VitePWA()` plugin with:
     ```ts
     VitePWA({
       registerType: 'autoUpdate',
       includeAssets: ['favicon.ico'],
       manifest: {
         name: 'CAD Price',
         short_name: 'CADPrice',
         description: 'CAD pricing and job management platform',
         theme_color: '#4f46e5',
         background_color: '#ffffff',
         display: 'standalone',
         orientation: 'portrait-primary',
         start_url: '/',
         scope: '/',
         icons: [
           { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
           { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
           { src: '/icons/icon-512-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' }
         ]
       },
       workbox: {
         globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
         runtimeCaching: [
           {
             urlPattern: /^https:\/\/.*\/api\/v1\//,
             handler: 'NetworkFirst',
             options: {
               cacheName: 'api-cache',
               expiration: { maxEntries: 100, maxAgeSeconds: 300 },
               networkTimeoutSeconds: 3
             }
           }
         ]
       }
     })
     ```

3. **Create PWA icons**
   - Directory: `frontend/public/icons/`
   - Generate icon set: 192x192, 512x512, 512x512 maskable
   - Use the existing `#4f46e5` brand color

4. **Add Apple-specific meta tags**
   - File: `frontend/index.html`
   - Add:
     ```html
     <link rel="apple-touch-icon" href="/icons/icon-192.png" />
     <meta name="apple-mobile-web-app-capable" content="yes" />
     <meta name="apple-mobile-web-app-status-bar-style" content="default" />
     ```

### 1.2 Safe Area Handling for Notched Devices

**Problem:** No `env(safe-area-inset-*)` padding — content is obscured by notches, rounded corners, and home indicators on modern phones.

**Implementation:**

1. **Update viewport meta**
   - File: `frontend/index.html`
   - Change: `content="width=device-width, initial-scale=1.0"` → `content="width=device-width, initial-scale=1.0, viewport-fit=cover"`

2. **Add safe area CSS custom properties**
   - File: `frontend/src/styles/globals.css`
   - Add to `:root`:
     ```css
     --safe-area-top: env(safe-area-inset-top, 0px);
     --safe-area-bottom: env(safe-area-inset-bottom, 0px);
     --safe-area-left: env(safe-area-inset-left, 0px);
     --safe-area-right: env(safe-area-inset-right, 0px);
     ```

3. **Apply safe area to shell layout**
   - File: `frontend/src/components/layout/app-shell.tsx` (or equivalent root layout)
   - Add `padding-top: var(--safe-area-top)` to the top bar
   - Add `padding-bottom: var(--safe-area-bottom)` to the bottom nav (Phase 2)

### 1.3 Enable HTTP/2 in Nginx

**Problem:** Only HTTP/1.1 configured — mobile browsers benefit significantly from HTTP/2 multiplexing.

**Implementation:**

1. **Update Nginx listen directive**
   - File: `infra/nginx/default.conf`
   - Change `listen 80;` to `listen 80 http2;` for development
   - For TLS block (production): `listen 443 ssl http2;`

2. **Tune HTTP/2 settings**
   - File: `infra/nginx/common.conf`
   - Add:
     ```nginx
     http2_max_concurrent_streams 128;
     http2_idle_timeout 3m;
     ```

### 1.4 ETag Support for API Responses

**Problem:** No conditional request support — mobile clients re-download unchanged data on every request.

**Implementation:**

1. **Create ETag middleware**
   - File: `app/api/middleware.py` (extend existing)
   - New class `ETagMiddleware`:
     - On GET responses, compute `ETag` from response body hash (MD5 or xxhash for speed)
     - Compare incoming `If-None-Match` header with computed ETag
     - Return `304 Not Modified` with empty body when matched
     - Skip for streaming responses and non-GET methods

2. **Register middleware**
   - File: `app/main.py`
   - Add `app.add_middleware(ETagMiddleware)` after GZip middleware (ETag should compute on uncompressed body)

3. **Add cache-control headers**
   - For list endpoints: `Cache-Control: private, max-age=0, must-revalidate`
   - For static resources (models list, etc.): `Cache-Control: public, max-age=300`

### 1.5 Responsive Toast Position

**Problem:** Toast at `position="top-right"` is not thumb-friendly on mobile.

**Implementation:**

1. **Make toast position responsive**
   - File: Where `<Toaster>` is rendered (likely `frontend/src/routes/__root.tsx` or app layout)
   - Use the existing `useIsMobile()` hook:
     ```tsx
     const isMobile = useIsMobile()
     <Toaster position={isMobile ? "bottom-center" : "top-right"} />
     ```

---

## Phase 2 — Mobile-Optimized UI (Weeks 3–5)

### 2.1 Bottom Navigation Bar

**Problem:** Sidebar navigation is a desktop pattern — mobile users expect thumb-reachable bottom navigation.

**Implementation:**

1. **Create `BottomNav` component**
   - File: `frontend/src/components/layout/bottom-nav.tsx`
   - Fixed to bottom of viewport with safe area padding
   - 4-5 primary navigation items with icons (from Lucide) and labels
   - Active state indicator (filled icon or underline)
   - Hide on scroll-down, show on scroll-up (save screen space)
   - CSS: `position: fixed; bottom: 0; padding-bottom: var(--safe-area-bottom);`

2. **Conditional rendering in app shell**
   - File: `frontend/src/components/layout/app-shell.tsx`
   - Show `<BottomNav>` when `useIsMobile()` returns true
   - Hide sidebar trigger on mobile (already partially handled)
   - Add bottom padding to main content area to prevent overlap: `pb-16 md:pb-0`

3. **Navigation items mapping** (suggested):
   - Home (dashboard) → `Home` icon
   - Jobs → `Briefcase` icon
   - AI / Chat → `MessageSquare` icon
   - Notifications → `Bell` icon (with badge)
   - More / Menu → `Menu` icon (opens sidebar as drawer)

### 2.2 Mobile-Adaptive Data Tables

**Problem:** `@tanstack/react-table` renders horizontal tables that are unusable on narrow screens.

**Implementation:**

1. **Create `ResponsiveDataView` wrapper**
   - File: `frontend/src/components/ui/responsive-data-view.tsx`
   - Props: accepts the same column/data config as current `DataTable`
   - At `md+`: render standard `<DataTable>` (existing component)
   - At `<md`: render a `<CardList>` view

2. **`CardList` component**
   - File: `frontend/src/components/ui/card-list.tsx`
   - Each row becomes a card with:
     - Primary field as card title
     - Key-value pairs for other visible columns
     - Actions as a trailing icon button or swipe actions
   - Support for infinite scroll via `@tanstack/react-virtual`
   - Pull-to-refresh gesture (see Phase 2.3)

3. **Migrate existing table usages**
   - Find all `<DataTable>` usages across routes
   - Replace with `<ResponsiveDataView>` — zero behavior change on desktop

### 2.3 Touch Gesture Support

**Problem:** No gesture handling beyond carousel swipe — missing pull-to-refresh, swipe actions, pinch-to-zoom.

**Implementation:**

1. **Install `@use-gesture/react`**
   - File: `frontend/package.json`
   - This is a lightweight gesture hook library (~3KB gzipped)

2. **Pull-to-refresh hook**
   - File: `frontend/src/hooks/use-pull-to-refresh.ts`
   - Uses `useDrag` from `@use-gesture/react`
   - Triggers TanStack Query refetch on pull-down when at scroll top
   - Visual indicator: spinner or progress bar at top of content area
   - Threshold: 80px pull distance before triggering

3. **Swipe-to-action on list items**
   - File: `frontend/src/components/ui/swipeable-row.tsx`
   - Reveal action buttons (delete, archive, etc.) on horizontal swipe
   - Uses `useDrag` with velocity-based snap
   - Integrate with `CardList` from 2.2

4. **Dismiss gestures for modals/drawers**
   - The existing Vaul drawer already supports drag-to-dismiss
   - Add swipe-to-dismiss to Sheet component for consistency

### 2.4 Responsive Images

**Problem:** No `srcset`, `<picture>`, or image optimization — users download full-size images on mobile networks.

**Implementation:**

1. **Create `<ResponsiveImage>` component**
   - File: `frontend/src/components/ui/responsive-image.tsx`
   - Props: `src`, `alt`, `sizes`, `widths` (array of breakpoint widths)
   - Renders `<picture>` with:
     - WebP `<source>` with `srcset` at multiple widths
     - Fallback `<img>` with `loading="lazy"` and `decoding="async"`
   - Aspect ratio container to prevent CLS

2. **Backend image processing endpoint** (optional — can also use CDN transform)
   - File: `app/api/v1/files.py` (extend)
   - Add query params: `?w=400&format=webp&q=80`
   - Use Pillow for on-the-fly resize (cache result in Redis or S3)
   - Return proper `Vary: Accept` header

3. **Alternatively: integrate an image CDN**
   - If using Cloudflare R2 (already configured in `.env.example`):
     - Enable Cloudflare Image Resizing or use `cdn-cgi/image/` transform URLs
   - Component generates transform URLs based on viewport

### 2.5 Dark Mode Toggle UI

**Problem:** Dark mode CSS exists (`.dark` class) but no toggle UI is exposed to users.

**Implementation:**

1. **Create theme store**
   - File: `frontend/src/stores/theme-store.ts`
   - Zustand store with `theme: 'light' | 'dark' | 'system'`
   - Persist to `localStorage` key `cadprice-theme`
   - Apply `.dark` class to `<html>` element
   - Listen to `prefers-color-scheme` media query when theme is `system`

2. **Create theme toggle component**
   - File: `frontend/src/components/layout/theme-toggle.tsx`
   - Three-way toggle: Light / Dark / System
   - Use Sun/Moon/Monitor icons from Lucide
   - Place in both sidebar footer and bottom-nav "More" menu

---

## Phase 3 — API & Backend Mobile Optimization (Weeks 4–6)

### 3.1 Sparse Field Selection

**Problem:** API returns full resource payloads — wasteful for mobile clients that only need a subset of fields.

**Implementation:**

1. **Create field selection utility**
   - File: `app/core/field_selection.py`
   - Parse `?fields=id,name,status` query parameter
   - Return a `FieldSelector` object that can filter Pydantic model output
   - Support nested fields: `?fields=id,owner.name,settings.theme`
   - Validate requested fields against response schema — return 400 for unknown fields

2. **Create FastAPI dependency**
   - File: `app/api/deps.py` (extend)
   - Add `get_field_selector(fields: str | None = Query(None)) -> FieldSelector`
   - Inject into endpoints that return resource objects

3. **Apply to response serialization**
   - File: `app/core/field_selection.py`
   - `filter_response(data: BaseModel, selector: FieldSelector) -> dict` — strips unselected fields
   - Integrate with `CursorPage` to filter items in paginated responses

4. **Apply to key endpoints**
   - `GET /api/v1/jobs` — jobs list (most frequent mobile call)
   - `GET /api/v1/notifications` — notification feed
   - `GET /api/v1/team` — team members list

### 3.2 Batch API Endpoints

**Problem:** Mobile clients make many sequential API calls — each round trip costs latency and battery.

**Implementation:**

1. **Create batch endpoint**
   - File: `app/api/v1/batch.py`
   - `POST /api/v1/batch` — accepts an array of sub-requests:
     ```json
     {
       "requests": [
         { "method": "GET", "path": "/api/v1/jobs?limit=5" },
         { "method": "GET", "path": "/api/v1/notifications?limit=10" }
       ]
     }
     ```
   - Execute sub-requests internally (via ASGI app routing, not HTTP)
   - Return array of responses with status codes
   - Limit: max 10 sub-requests per batch
   - All sub-requests share the same auth context

2. **Register route**
   - File: `app/api/v1/__init__.py`
   - Add batch router to v1 API prefix

3. **Rate limiting for batch**
   - File: `app/api/rate_limit.py`
   - Each sub-request counts individually toward rate limits
   - The batch endpoint itself has a stricter rate: 10 req/60s

### 3.3 WebSocket Support

**Problem:** Only SSE streaming for AI completions — no bidirectional real-time communication for notifications, presence, or live updates.

**Implementation:**

1. **WebSocket manager**
   - File: `app/core/websocket.py`
   - `ConnectionManager` class:
     - Track active connections per user/tenant
     - `connect(ws, user_id, tenant_id)` — authenticate and register
     - `disconnect(ws)` — clean up
     - `broadcast(tenant_id, event)` — send to all tenant connections
     - `send_personal(user_id, event)` — send to specific user
   - Event format: `{ "type": "notification" | "job_update" | "presence", "data": {...} }`

2. **WebSocket endpoint**
   - File: `app/api/v1/ws.py`
   - `GET /api/v1/ws` — upgrade to WebSocket
   - Authenticate via query param token: `/api/v1/ws?token=<jwt>` (WebSocket can't use Authorization header)
   - Heartbeat: server sends ping every 30s, client must respond within 10s

3. **Nginx WebSocket proxy**
   - File: `infra/nginx/common.conf`
   - Add to `/api/v1/ws` location:
     ```nginx
     location /api/v1/ws {
         proxy_pass http://api;
         proxy_http_version 1.1;
         proxy_set_header Upgrade $http_upgrade;
         proxy_set_header Connection "upgrade";
         proxy_read_timeout 3600s;
         proxy_send_timeout 3600s;
     }
     ```

4. **Frontend WebSocket client**
   - File: `frontend/src/lib/websocket-client.ts`
   - Auto-reconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s)
   - Integrate with TanStack Query: invalidate queries on relevant WebSocket events
   - Connection state exposed via Zustand store

5. **Publish events from backend**
   - Integrate with existing Celery tasks and API endpoints
   - When a job status changes → publish `job_update` event
   - When a notification is created → publish `notification` event

### 3.4 Push Notification Infrastructure

**Problem:** No push notification support — mobile users miss important events when the app is backgrounded.

**Implementation:**

1. **Database model for push subscriptions**
   - File: `app/db/models/notifications.py` (extend or create)
   - New model `PushSubscription`:
     - `id`, `user_id`, `tenant_id`
     - `platform: enum('web', 'fcm', 'apns')`
     - `subscription_data: JSONB` — stores Web Push subscription or device token
     - `active: bool`, `created_at`, `updated_at`
   - Alembic migration to add table

2. **Push subscription API**
   - File: `app/api/v1/push.py`
   - `POST /api/v1/push/subscribe` — register a push subscription
   - `DELETE /api/v1/push/subscribe/{id}` — unregister
   - `GET /api/v1/push/subscriptions` — list user's subscriptions

3. **Web Push integration**
   - File: `app/services/push.py`
   - Use `pywebpush` library for Web Push Protocol (VAPID keys)
   - Add `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_MAILTO` to `.env.example`
   - Integrate with service worker from Phase 1.1 to receive push events

4. **FCM integration (for future native apps)**
   - File: `app/services/push.py` (extend)
   - Use `firebase-admin` SDK
   - Add `FIREBASE_SERVICE_ACCOUNT_JSON` to `.env.example`
   - Abstract behind a `PushProvider` interface for multi-platform support

5. **Celery task for sending push notifications**
   - File: `app/workers/tasks/push.py`
   - `send_push_notification.delay(user_id, title, body, data)`
   - Batch sends for tenant-wide notifications
   - Handle subscription expiry: mark inactive on 410 response

6. **Frontend service worker push handler**
   - File: Generated by `vite-plugin-pwa` custom service worker
   - Listen for `push` event → show native notification
   - Listen for `notificationclick` → focus/open app at relevant route

### 3.5 API Versioning Strategy

**Problem:** No version negotiation — breaking changes force all clients to update simultaneously.

**Implementation:**

1. **Add `Accept-Version` header support**
   - File: `app/api/middleware.py` (extend)
   - Parse `Accept-Version: v1` or `Accept-Version: v2` header
   - Default to latest stable version when header absent
   - Store version in `request.state.api_version`

2. **Version-aware response serialization**
   - File: `app/core/versioning.py`
   - Decorator `@api_version(introduced="v1", deprecated="v2")`
   - Different Pydantic response models per version where needed
   - Return `Deprecation` header when client uses deprecated version

3. **Scaffold v2 router**
   - File: `app/api/v2/__init__.py`
   - Initially re-export v1 endpoints — diverge only when breaking changes are needed
   - Mount at `/api/v2/` prefix in `app/main.py`

---

## Phase 4 — Offline-First & Real-Time (Weeks 6–9)

### 4.1 Offline-First Data Synchronization Model

**Problem:** No sync metadata — mobile clients cannot work offline and sync changes when reconnected.

**Implementation:**

1. **Add sync columns to key models**
   - File: `app/db/base.py`
   - New `SyncMixin`:
     ```python
     class SyncMixin:
         sync_version = Column(BigInteger, server_default="0", nullable=False)
         sync_checksum = Column(String(64), nullable=True)
     ```
   - Apply to: `Job`, `Notification`, `TeamMembership`, `User` (profile)

2. **Change log table**
   - File: `app/db/models/sync.py`
   - New model `ChangeLog`:
     - `id: BigInteger` (auto-increment, monotonic)
     - `tenant_id`, `entity_type`, `entity_id`
     - `operation: enum('create', 'update', 'delete')`
     - `changed_fields: JSONB` — which fields changed
     - `sync_version: BigInteger`
     - `created_at`
   - Index: `(tenant_id, entity_type, sync_version)` — for efficient "changes since" queries

3. **Sync API endpoints**
   - File: `app/api/v1/sync.py`
   - `GET /api/v1/sync/changes?since_version={version}&entity_types=jobs,notifications&limit=100`
     - Returns changes since given version, ordered by sync_version
     - Response includes `latest_version` for next poll
   - `POST /api/v1/sync/push` — client pushes offline-created/modified records
     - Server applies conflict resolution (last-write-wins by default)
     - Returns `{ accepted: [...], conflicts: [...] }` with server versions of conflicted records

4. **Database triggers for change tracking**
   - File: `app/db/migrations/versions/xxx_add_change_tracking.py`
   - PostgreSQL trigger function: on INSERT/UPDATE/DELETE of synced tables → insert into `change_log`
   - Use `pg_notify` to broadcast changes for WebSocket delivery

5. **Frontend sync engine**
   - File: `frontend/src/lib/sync-engine.ts`
   - Uses IndexedDB (via `idb` library) for local storage
   - Background sync on reconnection (via `navigator.onLine` + `online` event)
   - Conflict resolution UI: show diff and let user choose
   - Integrate with TanStack Query: serve from IndexedDB when offline, sync on reconnect

6. **Install IndexedDB wrapper**
   - File: `frontend/package.json`
   - Add `idb` (tiny Promise-based IndexedDB wrapper, ~1KB)

### 4.2 Service Worker Offline Strategies

**Problem:** Phase 1.1 adds a basic service worker — this phase makes it intelligent.

**Implementation:**

1. **Extend Workbox configuration**
   - File: `frontend/vite.config.ts` (update PWA plugin config)
   - Strategy per route:
     - `NetworkFirst` for API calls (serve cached when offline)
     - `CacheFirst` for static assets (JS, CSS, fonts)
     - `StaleWhileRevalidate` for images
   - Background sync for failed POST/PUT/DELETE requests:
     ```ts
     workbox: {
       runtimeCaching: [
         {
           urlPattern: /\/api\/v1\/(?!sync|ws|auth)/,
           handler: 'NetworkFirst',
           options: { cacheName: 'api-v1', networkTimeoutSeconds: 5 }
         }
       ]
     }
     ```

2. **Offline indicator UI**
   - File: `frontend/src/components/layout/offline-banner.tsx`
   - Fixed banner at top: "You're offline — changes will sync when reconnected"
   - Uses `navigator.onLine` + `online`/`offline` events
   - Animate in/out with motion library

3. **Queue failed mutations**
   - Workbox Background Sync plugin for failed POST/PUT/DELETE
   - On reconnect, replay queued mutations in order
   - Show pending sync count in UI

### 4.3 Optimistic UI Updates

**Problem:** Mobile network latency makes UI feel sluggish when waiting for server confirmation.

**Implementation:**

1. **Leverage TanStack Query's optimistic updates**
   - File: `frontend/src/lib/mutations/` (create directory for mutation hooks)
   - Pattern for each mutation:
     ```ts
     useMutation({
       mutationFn: updateJob,
       onMutate: async (newData) => {
         await queryClient.cancelQueries({ queryKey: ['jobs', id] })
         const previous = queryClient.getQueryData(['jobs', id])
         queryClient.setQueryData(['jobs', id], (old) => ({ ...old, ...newData }))
         return { previous }
       },
       onError: (err, newData, context) => {
         queryClient.setQueryData(['jobs', id], context.previous)
         toast.error('Update failed — reverted')
       },
       onSettled: () => {
         queryClient.invalidateQueries({ queryKey: ['jobs', id] })
       }
     })
     ```

2. **Apply to high-frequency mutations**
   - Job status updates
   - Notification mark-as-read
   - Team member role changes
   - Settings updates

---

## Phase 5 — Infrastructure & Performance (Weeks 7–10)

### 5.1 CDN Integration

**Problem:** Static assets served directly from Nginx — no edge caching for global mobile users.

**Implementation:**

1. **Cloudflare CDN setup** (preferred — already using Cloudflare R2 for storage)
   - DNS: proxy through Cloudflare (orange cloud)
   - Page Rules:
     - `/assets/*` → Cache Level: Cache Everything, Edge TTL: 1 month
     - `/icons/*` → Cache Level: Cache Everything, Edge TTL: 1 month
     - `/api/*` → Cache Level: Bypass

2. **Update Nginx headers for CDN**
   - File: `infra/nginx/common.conf`
   - Add `Vary: Accept-Encoding` to all responses
   - Add `CDN-Cache-Control: public, max-age=2592000` for static assets
   - Add `CDN-Cache-Control: no-store` for API responses

3. **Terraform CDN configuration** (if IaC is adopted from SaaS gap analysis)
   - File: `infra/terraform/cloudflare.tf`
   - Define zone, DNS records, page rules, WAF rules

### 5.2 Brotli Compression

**Problem:** Only GZip — Brotli provides 15-20% better compression ratios.

**Implementation:**

1. **Pre-compress static assets at build time**
   - File: `frontend/vite.config.ts`
   - Add `vite-plugin-compression` with Brotli:
     ```ts
     import compression from 'vite-plugin-compression'
     // ...
     plugins: [
       compression({ algorithm: 'brotliCompress', ext: '.br' }),
       compression({ algorithm: 'gzip', ext: '.gz' })
     ]
     ```

2. **Serve pre-compressed files from Nginx**
   - File: `infra/nginx/common.conf`
   - In `/assets/` location:
     ```nginx
     location /assets/ {
         gzip_static on;
         brotli_static on;   # requires ngx_brotli module
         # ...existing config...
     }
     ```

3. **Update Dockerfile to include ngx_brotli**
   - File: `infra/nginx/Dockerfile` (create if using custom Nginx image)
   - Or use `fholzer/nginx-brotli` base image in `docker-compose.prod.yml`

### 5.3 Core Web Vitals Monitoring

**Problem:** No performance monitoring — can't measure or improve mobile load performance.

**Implementation:**

1. **Install `web-vitals` library**
   - File: `frontend/package.json`
   - Add `web-vitals` (~1KB)

2. **Report CWV metrics**
   - File: `frontend/src/lib/analytics.ts`
   - Report LCP, FID, CLS, TTFB, INP:
     ```ts
     import { onLCP, onFID, onCLS, onTTFB, onINP } from 'web-vitals'

     function reportMetric(metric: Metric) {
       // Send to analytics endpoint
       navigator.sendBeacon('/api/v1/analytics/cwv', JSON.stringify({
         name: metric.name,
         value: metric.value,
         rating: metric.rating,
         navigationType: metric.navigationType
       }))
     }

     onLCP(reportMetric)
     onFID(reportMetric)
     onCLS(reportMetric)
     onTTFB(reportMetric)
     onINP(reportMetric)
     ```

3. **Backend analytics endpoint**
   - File: `app/api/v1/analytics.py`
   - `POST /api/v1/analytics/cwv` — unauthenticated, fire-and-forget
   - Store in Redis sorted set by metric name for real-time dashboards
   - Periodically flush to PostgreSQL for historical analysis
   - Rate limit: 5 req/60s per IP

4. **CI performance budget**
   - File: `.github/workflows/ci.yml` (extend frontend job)
   - Add Lighthouse CI with budgets:
     - LCP < 2.5s, FID < 100ms, CLS < 0.1
     - Performance score > 90, Accessibility score > 90
   - Use `@lhci/cli` in GitHub Actions

### 5.4 Image Optimization Pipeline

**Problem:** No WebP/AVIF conversion or responsive image generation.

**Implementation:**

1. **Build-time image optimization**
   - File: `frontend/vite.config.ts`
   - Add `vite-plugin-image-optimizer`:
     ```ts
     import { ViteImageOptimizer } from 'vite-plugin-image-optimizer'
     plugins: [
       ViteImageOptimizer({
         png: { quality: 80 },
         jpeg: { quality: 80 },
         webp: { quality: 80 },
         avif: { quality: 65 }
       })
     ]
     ```

2. **Runtime image transforms via S3/CDN**
   - If using Cloudflare: use Image Resizing (`/cdn-cgi/image/width=400,format=auto/`)
   - Integrate URL generation into `<ResponsiveImage>` component from Phase 2.4

### 5.5 Font Optimization

**Problem:** Inter font loaded but no subsetting or optimization for mobile.

**Implementation:**

1. **Self-host and subset Inter font**
   - File: `frontend/src/styles/globals.css`
   - Use `@fontsource-variable/inter` package (tree-shakeable, subset per weight)
   - Load only Latin subset initially: `unicode-range: U+0000-00FF`
   - Use `font-display: swap` to prevent FOIT

2. **Preload critical font files**
   - File: `frontend/index.html`
   - Add: `<link rel="preload" href="/fonts/inter-latin-variable.woff2" as="font" type="font/woff2" crossorigin />`

---

## Phase 6 — Native-Ready & Production Hardening (Weeks 10–14)

### 6.1 Native App Shell (Capacitor)

**Problem:** The web app needs to work as a native mobile app for app store distribution.

**Implementation:**

1. **Initialize Capacitor**
   - Directory: `frontend/` (Capacitor lives alongside the web app)
   - Commands:
     ```bash
     npm install @capacitor/core @capacitor/cli
     npx cap init "CAD Price" "com.cadprice.app" --web-dir dist
     npm install @capacitor/ios @capacitor/android
     npx cap add ios
     npx cap add android
     ```

2. **Capacitor plugins for native features**
   - File: `frontend/package.json`
   - Add:
     - `@capacitor/push-notifications` — native push (uses FCM/APNs from Phase 3.4)
     - `@capacitor/haptics` — tactile feedback on actions
     - `@capacitor/keyboard` — handle virtual keyboard events
     - `@capacitor/status-bar` — style status bar
     - `@capacitor/splash-screen` — app launch screen
     - `@capacitor/camera` — (if needed) photo capture
     - `@capacitor/filesystem` — local file access

3. **Platform detection utility**
   - File: `frontend/src/lib/platform.ts`
   - Detect: web browser, iOS app, Android app, PWA installed
   - Conditionally use native APIs when available, fall back to web APIs

4. **Native build CI/CD**
   - File: `.github/workflows/mobile.yml`
   - iOS: Build on macOS runner, sign with App Store credentials, upload to TestFlight
   - Android: Build APK/AAB, sign with keystore, upload to Google Play Console
   - Trigger: manual dispatch or tag push (`v*-mobile`)

### 6.2 Biometric Authentication

**Problem:** JWT login requires username/password — mobile users expect fingerprint/face unlock.

**Implementation:**

1. **WebAuthn/FIDO2 backend**
   - File: `app/api/v1/webauthn.py`
   - `POST /api/v1/auth/webauthn/register/begin` — generate registration challenge
   - `POST /api/v1/auth/webauthn/register/complete` — verify and store credential
   - `POST /api/v1/auth/webauthn/authenticate/begin` — generate auth challenge
   - `POST /api/v1/auth/webauthn/authenticate/complete` — verify and issue JWT
   - Use `py_webauthn` library

2. **Database model for credentials**
   - File: `app/db/models/auth.py` (extend)
   - New model `WebAuthnCredential`:
     - `id`, `user_id`, `credential_id`, `public_key`, `sign_count`, `device_name`
     - `created_at`, `last_used_at`

3. **Frontend WebAuthn integration**
   - File: `frontend/src/lib/webauthn.ts`
   - Wrap `navigator.credentials.create()` and `navigator.credentials.get()`
   - Offer biometric login on supported devices after initial password login
   - Store `credential_id` in `localStorage` to auto-suggest biometric on return visits

4. **Capacitor biometrics** (for native app)
   - Use `@capacitor/biometrics` plugin
   - Falls through to WebAuthn on web

### 6.3 Performance Optimization Audit

**Problem:** No systematic performance review for mobile devices.

**Implementation:**

1. **Bundle size analysis**
   - File: `frontend/vite.config.ts`
   - Add `rollup-plugin-visualizer` for build-time bundle analysis
   - Set budgets: main chunk < 150KB gzipped, total JS < 400KB gzipped
   - Add to CI: fail if budgets exceeded

2. **Code splitting audit**
   - Review all `.lazy.tsx` routes — ensure heavy dependencies are only in lazy chunks
   - Move Tiptap editor, Recharts, and other large libraries to dynamic imports
   - Verify: `import()` for all route-level components

3. **React rendering optimization**
   - Audit with React DevTools Profiler
   - Add `React.memo()` to list item components
   - Use `useDeferredValue` for search inputs on slow devices
   - Ensure TanStack Query `staleTime` is set appropriately per query

4. **Network waterfall optimization**
   - Preload critical API calls in route loaders (TanStack Router supports `loader`)
   - Prefetch likely next-page data on hover/touch start
   - Add `<link rel="dns-prefetch">` for external API domains

### 6.4 Accessibility for Mobile

**Problem:** Desktop-focused accessibility — mobile screen readers have different patterns.

**Implementation:**

1. **Touch target sizes**
   - Audit all interactive elements: minimum 44x44px touch targets (WCAG 2.5.8)
   - File: `frontend/src/styles/globals.css`
   - Add utility: `.touch-target { min-width: 44px; min-height: 44px; }`

2. **Focus management for mobile**
   - File: Across all modal/drawer/sheet components
   - Ensure focus trap works correctly with mobile screen readers
   - Test with VoiceOver (iOS) and TalkBack (Android)

3. **Semantic landmarks**
   - Ensure `<nav>`, `<main>`, `<header>`, `<footer>` are used correctly
   - Bottom nav should have `role="navigation"` and `aria-label="Primary"`

4. **Reduced motion support**
   - File: `frontend/src/styles/globals.css`
   - Add:
     ```css
     @media (prefers-reduced-motion: reduce) {
       *, *::before, *::after {
         animation-duration: 0.01ms !important;
         transition-duration: 0.01ms !important;
       }
     }
     ```
   - Respect this in motion library animations

---

## Cross-Cutting Concerns

### C.1 Testing Strategy for Mobile

| Layer | Tool | What to Test |
|-------|------|--------------|
| **Unit** | Vitest | Hooks (`useIsMobile`, `usePullToRefresh`, `useSyncEngine`), utility functions |
| **Component** | Vitest + Testing Library | Responsive rendering at different viewports, touch event handlers |
| **Integration** | Playwright | Full user flows on mobile viewport (375x812 iPhone, 360x800 Android) |
| **E2E Mobile** | Playwright + device emulation | PWA install flow, offline mode, push notifications |
| **Performance** | Lighthouse CI | CWV budgets in CI pipeline |
| **Visual Regression** | Playwright screenshots | Compare mobile layouts across PRs |

**Playwright mobile config:**
- File: `frontend/playwright.config.ts`
- Add mobile projects:
  ```ts
  projects: [
    { name: 'Mobile Chrome', use: { ...devices['Pixel 7'] } },
    { name: 'Mobile Safari', use: { ...devices['iPhone 14'] } },
    // ...existing desktop projects
  ]
  ```

### C.2 Feature Flags for Gradual Rollout

Each major feature should be gated behind a feature flag (from SaaS gap analysis):

| Feature | Flag Name | Default |
|---------|-----------|---------|
| PWA Install Prompt | `pwa_enabled` | `true` |
| Bottom Navigation | `mobile_bottom_nav` | `true` |
| Offline Sync | `offline_sync_enabled` | `false` |
| Push Notifications | `push_notifications_enabled` | `false` |
| WebSocket Real-Time | `websocket_enabled` | `false` |
| Biometric Auth | `webauthn_enabled` | `false` |
| Batch API | `batch_api_enabled` | `true` |

### C.3 Environment Variables to Add

File: `.env.example`

```env
# PWA / Push Notifications
VAPID_PRIVATE_KEY=
VAPID_PUBLIC_KEY=
VAPID_MAILTO=admin@cadprice.com

# Firebase (for native push)
FIREBASE_SERVICE_ACCOUNT_JSON=

# WebAuthn
WEBAUTHN_RP_ID=cadprice.com
WEBAUTHN_RP_NAME=CAD Price
WEBAUTHN_ORIGIN=https://cadprice.com

# CDN
CDN_BASE_URL=
CDN_IMAGE_TRANSFORM_PREFIX=/cdn-cgi/image/

# Performance
LIGHTHOUSE_MIN_SCORE=90
CWV_LCP_BUDGET_MS=2500
CWV_CLS_BUDGET=0.1
```

### C.4 New Dependencies Summary

**Frontend:**
| Package | Size (gzip) | Phase | Purpose |
|---------|-------------|-------|---------|
| `vite-plugin-pwa` | dev only | 1.1 | PWA generation |
| `@use-gesture/react` | ~3KB | 2.3 | Touch gestures |
| `idb` | ~1KB | 4.1 | IndexedDB wrapper |
| `web-vitals` | ~1KB | 5.3 | Performance metrics |
| `@capacitor/core` | ~8KB | 6.1 | Native bridge |
| `vite-plugin-compression` | dev only | 5.2 | Brotli pre-compression |
| `vite-plugin-image-optimizer` | dev only | 5.4 | Image optimization |
| `@fontsource-variable/inter` | ~30KB | 5.5 | Self-hosted font |

**Backend:**
| Package | Phase | Purpose |
|---------|-------|---------|
| `pywebpush` | 3.4 | Web Push Protocol |
| `py-vapid` | 3.4 | VAPID key management |
| `firebase-admin` | 3.4 | FCM push notifications |
| `py_webauthn` | 6.2 | WebAuthn/FIDO2 |
| `Pillow` | 2.4 | Image processing (if not using CDN) |
| `xxhash` | 1.4 | Fast ETag hashing |

---

## Success Criteria

### Quantitative Targets

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Mobile-First Readiness Score | 5/10 | 9/10 | Re-evaluation after Phase 6 |
| Lighthouse Performance (mobile) | ~60 (est.) | >90 | Lighthouse CI |
| Lighthouse Accessibility | ~70 (est.) | >95 | Lighthouse CI |
| LCP (mobile 4G) | unmeasured | <2.5s | web-vitals |
| CLS | unmeasured | <0.1 | web-vitals |
| INP | unmeasured | <200ms | web-vitals |
| JS Bundle (main chunk) | unmeasured | <150KB gz | Vite build |
| PWA Install Rate | 0% | measurable | Analytics |
| Offline-capable pages | 0 | 100% core flows | Manual audit |
| Touch target compliance | partial | 100% | Automated a11y audit |

### Qualitative Gates

- [ ] App installable via "Add to Home Screen" on iOS and Android
- [ ] Core workflows (view jobs, view notifications, update status) work offline
- [ ] Push notifications delivered within 5s of event
- [ ] No horizontal scroll on any page at 320px width
- [ ] All features accessible without keyboard shortcuts
- [ ] Biometric login available on supported devices
- [ ] Data tables render as cards on mobile
- [ ] Bottom navigation present on mobile viewports
- [ ] Service worker caches API responses for offline access
- [ ] WebSocket delivers real-time updates without polling

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Service worker caching stale data | Users see outdated info | Medium | NetworkFirst strategy + version-based cache busting |
| Offline sync conflicts | Data loss | Medium | Last-write-wins default + conflict resolution UI |
| PWA install prompt fatigue | Users dismiss permanently | Low | Show only after 3rd visit + engagement threshold |
| WebSocket connection on mobile networks | Dropped connections | High | Auto-reconnect + fallback to polling |
| Capacitor plugin compatibility | Build failures | Medium | Pin versions, test on CI with device emulation |
| Bundle size regression | Slow mobile load | Medium | CI budgets + bundle analyzer in PR checks |
| Push notification permission denial | Low engagement | High | Explain value before prompting, allow deferral |
| IndexedDB storage limits | Sync failure on low-storage devices | Low | Quota management + selective sync scopes |

---

## Implementation Timeline (Gantt Overview)

```
Week  1  2  3  4  5  6  7  8  9  10 11 12 13 14
      ├──┤                                         Phase 1: Foundation & Quick Wins
            ├─────┤                                Phase 2: Mobile-Optimized UI
               ├─────┤                             Phase 3: API & Backend Optimization
                        ├────────┤                 Phase 4: Offline-First & Real-Time
                           ├────────┤              Phase 5: Infrastructure & Performance
                                       ├────────┤  Phase 6: Native-Ready & Hardening
```

**Phases 3-5 overlap intentionally** — backend and infrastructure work can proceed in parallel with frontend work by different team members.

---

## Relationship to Existing Gap Analyses

This plan incorporates and extends findings from:

- **`docs/mobile-first-readiness-evaluation.md`** — All 29 gaps addressed
- **`docs/SAAS_INFRASTRUCTURE_EVALUATION.md`** — Relevant infrastructure gaps (CDN, HTTP/2, monitoring)
- **`docs/SAAS_GAP_ANALYSIS.md`** — Feature flags, event-driven architecture, and API versioning integrated
