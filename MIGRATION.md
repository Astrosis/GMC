# Content API for Shopping → Merchant API — Migration Reference

Reference for the GMC → BigQuery pipelines in this repo. Covers what differs
between the old **Content API for Shopping** and the new **Merchant API**, why
Google built the new one, and the migration-specific gotchas we hit.

---

## TL;DR

- The **Content API for Shopping** (`content` v2.1) is being **sunset in 2026**.
  Anything built on it — including our product pull and the
  `MerchantPerformanceView` aggregate table — must move to the **Merchant API**.
- Data and metric definitions largely carry over. The one real data change is
  `program` → `marketing_method` (`SHOPPING_ADS`/`FREE_PRODUCT_LISTING` become
  `ADS`/`ORGANIC`).
- The big new operational hurdle is **mandatory developer registration**
  (`registerGcp`), which links the GCP project to the Merchant Center account
  and must be done **once by a human account with Merchant Center Admin**.

---

## 1. Timeline & why we're migrating

- Google announced deprecation of the Content API for Shopping; it is being
  **turned down through 2026**. Calls will eventually stop working.
- The **Merchant API** is the strategic replacement and the only place new
  Merchant Center capabilities are being added.
- Practical consequence: every pipeline on `content` v2.1 in this repo
  (`GMC_report`, the aggregate table) needs a Merchant API equivalent before
  the cutover. The `*_mapi` files are those equivalents.

---

## 2. Architectural differences

| Dimension | Content API for Shopping | Merchant API |
|---|---|---|
| Overall shape | **One monolithic API** (`content` v2.1) | **A suite of sub-APIs**: `reports`, `accounts`, `products`, `inventories`, `datasources`, `promotions`, `lfp`, … |
| Versioning | Single version for everything | **Each sub-API versioned independently** (`reports_v1`, `accounts_v1`, some still `_v1beta`) — features can go GA on their own timeline |
| API style | RPC-flavoured; `merchantId` passed as a parameter | **Resource-oriented REST**; resources addressed by name, e.g. `accounts/{account}/reports` |
| Endpoint host | `content.googleapis.com` | `merchantapi.googleapis.com` |
| Python discovery build | `build("content", "v2.1")` | `build("merchantapi", "reports_v1")` (per sub-API) |
| Client libraries | One `content` library | **Separate library per sub-API** |
| Resource naming | Numeric IDs in params | **Hierarchical resource names**: `accounts/123`, `accounts/123/products/…` |

### Method call shape
```text
# Old (Content API)
service.reports().search(merchantId=123, body={...})

# New (Merchant API)
service.accounts().reports().search(parent="accounts/123", body={...})
```

---

## 3. Authentication & access — the biggest change

| | Content API | Merchant API |
|---|---|---|
| OAuth scope | `https://www.googleapis.com/auth/content` | **same** scope |
| Service account access | Add SA as a Merchant Center user; done | **same**, still required |
| **Developer registration** | Not required | **Required** — `accounts.developerRegistration.registerGcp` must link the GCP project to the Merchant Center account, once per project |
| Who may register | n/a | A **human account** (service accounts are rejected: *"gcp reg is not allowed for SA"*) that holds the **Merchant Center ADMIN** role |
| Failure mode if skipped | n/a | **401 UNAUTHENTICATED** — *"project … is not registered with the merchant account"* |

Key nuances:
- Registration is **once per GCP project**. A project can be registered to
  **exactly one** Merchant Center account.
- For **advanced (multi-client) accounts**, register the **parent** account —
  it automatically covers all sub-accounts. Don't register each sub-account.
- Only the **one-time registration** needs a human. The **daily report reads
  continue to run as the service account**.
- The registering human needs the `content` scope on their token. In a locked
  down Google Workspace org this can be blocked ("app blocked"); the workaround
  is to authorize with an OAuth client owned by your own project (Internal, or
  External + test user) — or to register with an unmanaged Google account that
  holds Merchant Center Admin.

---

## 4. Reporting differences (what our pipelines actually use)

| Old (`MerchantPerformanceView`) | New (`product_performance_view`) |
|---|---|
| `FROM MerchantPerformanceView` | `FROM product_performance_view` (snake_case) |
| `segments.date`, `metrics.clicks` (prefixed) | `date`, `clicks` — **flat field names, no prefixes** |
| `segments.program` | **`marketing_method`** |
| `segments.offerId` | `offer_id` |
| `segments.customerCountryCode` | `customer_country_code` |
| Response: `row["segments"]` / `row["metrics"]` | Response: `row["productPerformanceView"]` (camelCase view name) |
| int64 metrics as numbers | int64 metrics as **JSON strings** (cast with `int()`) |

### `program` → `marketing_method` value mapping
| Old `program` value | New `marketing_method` |
|---|---|
| `SHOPPING_ADS` | `ADS` |
| `FREE_PRODUCT_LISTING` | `ORGANIC` |
| `FREE_LOCAL_PRODUCT_LISTING` | `ORGANIC` |
| `BUY_ON_GOOGLE_LISTING` | (folded into the above) |

This is the **one genuine data discontinuity**: historical rows use the old
vocabulary, new rows use `ADS`/`ORGANIC`. We keep the BigQuery column named
`program` and normalize via `map_program()`.

### Aggregate vs product-level (important)
- `product_performance_view` **is** the reporting view. You control granularity
  by **which dimensions you SELECT** — include `offer_id` for product-level,
  omit it for aggregate totals.
- **You cannot rebuild the aggregate by summing the product-level table.**
  Low-volume product rows are **withheld for privacy**, so `SUM(product)` is
  systematically lower than the true aggregate. To match the legacy
  `MerchantPerformanceView` aggregate query, **query without `offer_id`** so the
  API aggregates server-side (this is what `GMC_report_agg_mapi` does).

### Query-language notes
- A query selecting segment fields **must also select ≥1 metric**, else it errors.
- Wildcards (`SELECT *`) are not allowed — list fields explicitly.
- `WHERE date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'` still works; you can also
  filter on segments like `customer_country_code`.

---

## 5. Benefits of the Merchant API

1. **Long-term support.** The Content API is deprecated; the Merchant API is
   where Google invests going forward. Migrating now is future-proofing.
2. **Independent, faster versioning.** Each sub-API (reports, products,
   accounts…) ships and stabilizes on its own schedule instead of being gated
   by one monolithic version — new report views and fields arrive sooner.
3. **Cleaner, resource-oriented REST.** Hierarchical resource names
   (`accounts/{id}/…`) are more predictable, easier to reason about, and align
   with the rest of Google Cloud's API design.
4. **First-class multi-account (advanced account) model.** Sub-accounts are
   addressed uniformly via the `accounts/{id}` parent, and one registration on
   the parent covers them all — cleaner than the old MCA handling.
5. **Stronger security / governance.** Mandatory developer registration ties a
   specific GCP project to a specific merchant account and records a developer
   contact — more auditable and controllable than the old open model.
6. **Data source–centric product management.** Products are managed through
   explicit data sources, giving clearer separation between feeds, supplemental
   data, and API-supplied data (relevant if we later write products, not just
   read reports).
7. **Broader surface area.** New and expanding capabilities (promotions, local
   feeds/LFP, quotas, issues/diagnostics) are exposed as dedicated sub-APIs
   rather than bolted onto one endpoint.
8. **Consistent auth story.** Same `content` scope, standard ADC / service
   account / OAuth patterns, and standard Google Cloud IAM around the project.

Trade-off to be honest about: **more upfront setup friction** (the registration
step, and getting a content-scoped human token past org policy). Once
registered, day-to-day operation is no harder than before.

---

## 6. How this maps to the repo

| File / table | Granularity | Replaces | Notes |
|---|---|---|---|
| `GMC_report_mapi` | product-level (`offer_id`) | product-level Content API pull | product breakdown; subject to low-volume withholding |
| `GMC_report_agg_mapi` | aggregate (date/program/country) | `MerchantPerformanceView` table | true server-side totals; use for exact aggregate parity |
| `register_gcp.py` | — | (new requirement) | one-time developer registration helper |
| `GMC_report` (old) | product-level, Content API | — | retire after parity is confirmed |

Both `*_mapi` pipelines: Merchant API `reports_v1`, `product_performance_view`,
per-sub-account via `merchant_id`, optional `location` (country) filter,
chunked backfill, and MERGE-into-BigQuery with an `account_id` column so `.com`
and `.jp` share one table without collisions.

---

## 7. Gotchas we hit (so future-you doesn't relearn them)

- **Registration requires a human with MC Admin** — not the service account,
  not just any GCP admin. Merchant Center admin ≠ GCP IAM admin ≠ Google
  Workspace admin; they're three separate systems.
- **`reports_v1beta` was discontinued** — use `reports_v1`.
- **Org "app blocked"** on the content scope → use an OAuth client owned by your
  own project (Internal, or External + add yourself as a test user), or an
  unmanaged Google account.
- **Windows shell quoting** (`$(...)`, `{}` in curl) is a recurring trap — the
  Python helpers and file-based payloads avoid it.
- **Setting an env var to `""` on Windows deletes it** — use explicit flags.
- **Cloud Functions entry file** defaults to `main.py`; point at another file
  with `--set-build-env-vars GOOGLE_FUNCTION_SOURCE=<file>.py`. `requirements.txt`
  must keep that exact name.
