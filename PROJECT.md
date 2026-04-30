# Shubham NX — Billing & Inventory System

A Flask-based management system for a tailoring/clothing retail business. Handles bill generation, customer tracking, inventory management, and sales analytics. Deployed on PythonAnywhere with Cloudflare tunnel support.

---

## Table of Contents

1. [Tech Stack](#tech-stack)
2. [Project Structure](#project-structure)
3. [Setup & Running](#setup--running)
4. [Authentication & Roles](#authentication--roles)
5. [Database Schema](#database-schema)
6. [API Reference](#api-reference)
7. [Page Routes](#page-routes)
8. [Core Workflows](#core-workflows)
9. [Inventory System](#inventory-system)
10. [QR Code System](#qr-code-system)
11. [Analytics & Export](#analytics--export)
12. [Frontend Architecture](#frontend-architecture)
13. [Security](#security)
14. [Environment Variables](#environment-variables)
15. [Default Credentials](#default-credentials)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask |
| Database | SQLite (WAL mode) |
| Auth | Flask sessions + bcrypt |
| Frontend | Vanilla JS, HTML/CSS |
| Charts | Chart.js |
| QR Codes | qrcode[pil] (server), Html5Qrcode (browser camera) |
| Excel Export | openpyxl |
| Deployment | PythonAnywhere + Cloudflare Tunnel |

---

## Project Structure

```
shubham-nx-billing-inventory/
├── app.py                    # App factory, blueprint registration
├── auth.py                   # Auth decorators, login/user routes
├── utils.py                  # Mobile normalization, rounding helpers
├── extensions.py             # bcrypt instance
├── requirements.txt
│
├── db/
│   ├── connection.py         # SQLite connection (WAL mode, row_factory)
│   ├── schema.py             # CREATE TABLE statements + migrations
│   └── __init__.py           # get_db(), close_db(), init_db(), seed_default_users()
│
├── routes/
│   ├── bills.py              # Bill CRUD
│   ├── customers.py          # Customer lookup
│   ├── companies.py          # Company dropdown management
│   ├── cloth_types.py        # Cloth type management
│   ├── salespersons.py       # Salesperson management
│   ├── suppliers.py          # Supplier management
│   ├── inventory.py          # Inventory CRUD + stock operations + QR
│   ├── analytics.py          # Sales analytics endpoints
│   ├── export.py             # Excel export
│   └── pages.py              # HTML page routes
│
├── services/
│   ├── billing.py            # Bill calculation & validation logic
│   └── inventory.py          # Stock deduction & restoration
│
├── static/
│   ├── css/
│   └── js/
│       ├── api.js            # Centralised fetch wrappers
│       ├── utils.js          # Shared helpers (currency, date, toast)
│       ├── bill.js           # New/Edit bill page logic (~1600 lines)
│       ├── dashboard.js      # Analytics dashboard
│       ├── inventory.js      # Inventory page
│       ├── customers.js      # Customers page
│       └── history.js        # Bill history page
│
└── templates/
    ├── base.html
    ├── login.html
    ├── dashboard.html
    ├── new_bill.html
    ├── edit_bill.html
    ├── bill_detail.html
    ├── bill_history.html
    ├── shared_bill.html
    ├── shared_bill_not_found.html
    ├── customers.html
    ├── customer_detail.html
    ├── inventory.html
    ├── admin_users.html
    ├── profile.html
    ├── unauthorized.html
    └── _bill_form.html       # Shared partial (new + edit)
```

---

## Setup & Running

### Install dependencies

```bash
pip install -r requirements.txt
```

### Run the app

```bash
python app.py
```

Runs on `http://0.0.0.0:8081`. The database (`billing.db`) is created automatically on first run with all tables and seed data.

### Environment variables (optional)

```bash
SECRET_KEY=your-random-64-char-string
SHARE_BASE_URL=https://your-deployment-url.com
```

---

## Authentication & Roles

### Roles

| Role | Access |
|---|---|
| `admin` | Everything — billing, inventory, analytics, user management |
| `staff` | New bill creation only |

### Login Security

- Passwords hashed with bcrypt
- **5 failed attempts** triggers a **15-minute lockout**
- Sessions expire on browser close (non-persistent)
- HTTPOnly + SameSite=Lax cookies

### Auth Decorators

| Decorator | Layer | Behavior on Failure |
|---|---|---|
| `@login_required` | Page | Redirect to `/login` |
| `@admin_required` | Page | Redirect to `/unauthorized` |
| `@staff_or_admin_required` | Page | Allows both roles |
| `@api_login_required` | API | `401 JSON` |
| `@api_admin_required` | API | `403 JSON` |

---

## Database Schema

### `customers`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT NOT NULL | |
| `mobile` | TEXT NOT NULL | Raw input |
| `normalized_mobile` | TEXT UNIQUE | 10-digit, strips +91/0 |
| `created_at`, `updated_at` | TEXT | datetime('now','localtime') |

### `cloth_types`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `type_name` | TEXT NOT NULL | e.g. "Shirting", "Gift Sets" |
| `normalized_name` | TEXT UNIQUE | lowercase |
| `is_default` | INTEGER | 1 for seeded types |
| `has_company` | INTEGER | Controls company dropdown visibility |

**Seeded values:** Shirting, Suiting, Readymade, Stitching, Gift Sets, Accessories

### `companies`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `cloth_type` | TEXT NOT NULL | FK → cloth_types.type_name |
| `company_name` | TEXT NOT NULL | e.g. "Monti", "Raymonds" |
| `normalized_company_name` | TEXT NOT NULL | |
| `is_default` | INTEGER | |
| UNIQUE | | `(cloth_type, normalized_company_name)` |

### `salespersons`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT NOT NULL | |
| `normalized_name` | TEXT UNIQUE | |
| `is_default` | INTEGER | |

**Seeded values:** Self, Geetesh

### `suppliers`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT NOT NULL | |
| `normalized_name` | TEXT UNIQUE | |
| `created_at` | TEXT | |

### `users`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `username` | TEXT UNIQUE | |
| `password_hash` | TEXT NOT NULL | bcrypt |
| `role` | TEXT | `"admin"` or `"staff"` |
| `is_active` | INTEGER | 0 = deactivated |
| `created_at`, `updated_at` | TEXT | |

### `bills`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `bill_number` | TEXT UNIQUE | Format: `SHN-0001` |
| `customer_id` | INTEGER | FK → customers |
| `customer_name_snapshot` | TEXT | Snapshot at billing time |
| `customer_mobile_snapshot` | TEXT | |
| `bill_date` | TEXT | YYYY-MM-DD |
| `subtotal` | REAL | Sum of line totals (MRP × qty) |
| `total_discount` | REAL | Sum of all discounts |
| `final_total` | REAL | After round-off |
| `total_savings` | REAL | Discount + round-off |
| `advance_paid` | REAL | Amount paid upfront |
| `remaining` | REAL | final_total − advance_paid |
| `salesperson_name` | TEXT | |
| `payment_mode_type` | TEXT | Cash / Card / UPI / Combination |
| `status` | TEXT | `"active"` (default) |

### `bill_items`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `bill_id` | INTEGER | FK → bills (CASCADE DELETE) |
| `cloth_type` | TEXT NOT NULL | |
| `company_name` | TEXT NOT NULL | |
| `quality_number` | TEXT | Optional |
| `quantity` | REAL NOT NULL | |
| `unit_label` | TEXT | `"m"` or `"pcs"` |
| `mrp` | REAL NOT NULL | Price per unit |
| `line_total` | REAL | mrp × quantity |
| `discount_percent` | REAL | |
| `discount_amount` | REAL | |
| `rate_after_disc` | REAL | mrp × (1 − discount%) |
| `final_amount` | REAL | rate_after_disc × quantity |
| `inventory_item_id` | INTEGER | FK → inventory_items (nullable) |

### `bill_payments`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `bill_id` | INTEGER | FK → bills (CASCADE DELETE) |
| `payment_method` | TEXT | Cash / Card / UPI |
| `amount` | REAL NOT NULL | |

### `bill_number_seq`

Singleton table (`id = 1` enforced via CHECK constraint). `next_val` increments atomically — prevents duplicate bill numbers under concurrent requests.

### `inventory_items`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `item_code` | TEXT UNIQUE | Auto-generated: `SHT-001`, `SUT-002`, etc. |
| `cloth_type` | TEXT NOT NULL | |
| `company_name` | TEXT NOT NULL | |
| `quality_number` | TEXT | Default `""` |
| `unit_label` | TEXT | Default `"m"` |
| `current_stock` | REAL | Default 0 |
| `min_stock_alert` | REAL | Default 5 |
| `mrp` | REAL | Default 0 |
| `notes` | TEXT | Optional |
| `supplier_id` | INTEGER | FK → suppliers (nullable) |
| UNIQUE | | `(cloth_type, company_name, quality_number)` |

**Item code prefix map:**

| Cloth Type | Prefix | Example |
|---|---|---|
| Shirting | `SHT` | `SHT-001` |
| Suiting | `SUT` | `SUT-003` |
| Readymade | `RDY` | `RDY-001` |
| Gift Sets | `GFT` | `GFT-002` |
| Accessories | `ACC` | `ACC-001` |
| Anything else | `OTH` | `OTH-001` |

### `inventory_transactions`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `item_id` | INTEGER | FK → inventory_items (CASCADE DELETE) |
| `txn_type` | TEXT | `opening`, `purchase`, `sale`, `sale_reversal`, `adjustment` |
| `quantity` | REAL | Positive = in, negative = out |
| `reference_type` | TEXT | `"bill"` or `"manual"` |
| `reference_id` | INTEGER | bill_id if reference_type = bill |
| `notes` | TEXT | |
| `created_by` | TEXT | username |

---

## API Reference

All API routes are prefixed with `/api`. Auth levels: **Login** = any logged-in user, **Admin** = admin role only.

### Bills

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/bills` | Admin | List bills; search via `?search=`, `?billNumber=`, `?mobile=`, `?name=` |
| `POST` | `/bills` | Login | Create bill |
| `GET` | `/bills/<id>` | Admin | Full bill detail with items & payments |
| `PUT` | `/bills/<id>` | Admin | Edit bill (restores old inventory, applies new) |
| `DELETE` | `/bills/<id>` | Admin | Delete bill + renumber all higher bills |

**POST/PUT payload:**
```json
{
  "customer_name": "John Doe",
  "customer_mobile": "9876543210",
  "bill_date": "2026-04-30",
  "salesperson_name": "Self",
  "payment_mode_type": "Combination",
  "round_off": 0.5,
  "advance_paid": 500.0,
  "items": [
    {
      "cloth_type": "Shirting",
      "company_name": "Monti",
      "quality_number": "M22",
      "quantity": 2.5,
      "unit_label": "m",
      "mrp": 450.0,
      "discount_percent": 10,
      "inventory_item_id": 3
    }
  ],
  "payments": [
    { "payment_method": "Cash", "amount": 600.0 },
    { "payment_method": "UPI",  "amount": 412.5 }
  ]
}
```

### Customers

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/customers` | Admin | List all; search via `?search=` |
| `GET` | `/customers/search` | Login | Lookup by mobile (for bill form) |
| `GET` | `/customers/<id>` | Admin | Customer detail |
| `GET` | `/customers/<id>/bills` | Admin | All bills for a customer |

### Cloth Types

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/cloth-types` | Login | All cloth types |
| `POST` | `/cloth-types` | Login | Add new cloth type `{ "type_name": "..." }` |

### Companies

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/companies?clothType=Shirting` | Login | Companies for a cloth type |
| `POST` | `/companies` | Login | Add company `{ "cloth_type": "...", "company_name": "..." }` |

### Salespersons

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/salespersons` | Login | All salespersons |
| `POST` | `/salespersons` | Admin | Add salesperson `{ "name": "..." }` |

### Suppliers

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/suppliers` | Login | All suppliers |
| `POST` | `/suppliers` | Admin | Add supplier `{ "name": "..." }` |

### Inventory

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/inventory` | Admin | All items (LEFT JOINs suppliers for supplier_name) |
| `GET` | `/inventory/<id>` | Login | Single item |
| `POST` | `/inventory` | Admin | Create item (auto-generates item_code) |
| `PUT` | `/inventory/<id>` | Admin | Update MRP, min_stock_alert, notes |
| `DELETE` | `/inventory/<id>` | Admin | Delete (blocked if referenced in bills) |
| `POST` | `/inventory/<id>/restock` | Admin | Add stock `{ "quantity": 10, "txn_type": "purchase", "notes": "..." }` |
| `POST` | `/inventory/<id>/adjust` | Admin | Adjust `{ "quantity": -3, "notes": "..." }` |
| `GET` | `/inventory/<id>/transactions` | Admin | Transaction history |
| `GET` | `/inventory/low-stock` | Admin | Items at or below alert threshold |
| `GET` | `/inventory/<id>/qr` | Admin | PNG QR for tracked item |
| `POST` | `/inventory/current-stock-qr` | Admin | PNG QR for untracked item |

### Analytics

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/analytics/summary` | Admin | KPIs: total bills, sales, customers, payment breakdown |
| `GET` | `/analytics` | Admin | Period breakdown; `?period=daily\|monthly\|yearly\|custom&from=&to=` |
| `GET` | `/analytics/salespersons` | Admin | Per-salesperson bill count & sales for period |

### Export

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/export/bills` | Admin | Download XLSX; `?period=today\|daily\|monthly\|yearly\|custom&from=&to=` |

### Auth

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET/POST` | `/login` | None | Login form |
| `GET` | `/logout` | Any | Clear session |
| `PUT` | `/api/users/me/password` | Login | Change own password |
| `GET` | `/api/users` | Admin | List users |
| `POST` | `/api/users` | Admin | Create user |
| `PUT` | `/api/users/<id>/password` | Admin | Reset user password |
| `PUT` | `/api/users/<id>/toggle-status` | Admin | Activate/deactivate user |

---

## Page Routes

| Path | Auth | Purpose |
|---|---|---|
| `/` | Admin | Analytics dashboard |
| `/new-bill` | Staff+ | Create a bill |
| `/bill-history` | Admin | Search & browse all bills |
| `/bills/<id>` | Admin | Bill detail & print |
| `/edit-bill/<id>` | Admin | Edit existing bill |
| `/customers` | Admin | Customer list |
| `/customers/<id>` | Admin | Customer profile & bill history |
| `/inventory` | Admin | Inventory management |
| `/admin/users` | Admin | User management |
| `/profile` | Login | Change own password |
| `/bill/share/<bill_number>` | None | Public bill view (shareable link) |

---

## Core Workflows

### Creating a Bill

1. Open `/new-bill`
2. Search customer by mobile → name auto-fills (or creates new customer)
3. Add items: select cloth type → company loads → enter qty, MRP, discount
4. System computes per-item: `line_total`, `discount_amount`, `rate_after_disc`, `final_amount`
5. Select payment mode: **Cash / Card / UPI / Combination**
6. Enter advance paid → remaining balance computed
7. Submit → server validates, saves bill, deducts linked inventory, logs transactions
8. Success: **Print**, **WhatsApp share**, **copy link** buttons appear

### Editing a Bill

1. Open `/edit-bill/<id>`
2. Form pre-fills with existing data
3. On save: old inventory quantities are **restored**, new quantities are **deducted**
4. Bill number stays the same

### Deleting a Bill

- Hard delete — bill and all items/payments removed
- All bills with higher numbers are **renumbered down** to keep sequence gapless
- Inventory is restored for any linked items

### Bill Calculation Logic

```
line_total     = mrp × quantity
discount_amt   = line_total − (rate_after_disc × quantity)
final_amount   = rate_after_disc × quantity

subtotal       = Σ line_total
total_discount = Σ discount_amount
gross_total    = Σ final_amount
final_total    = gross_total − round_off
remaining      = final_total − advance_paid
```

All rounding uses `ROUND_HALF_UP` to 2 decimal places (matches JS `Math.round` behaviour).

---

## Inventory System

### Item Codes

When an item is created, a code is auto-generated from the cloth type:

```
SHT-001  →  Shirting, first item
SUT-003  →  Suiting, third item
OTH-001  →  Stitching or any other type
```

Codes are sequential per prefix and stored as a `UNIQUE` column.

### Inventory Sections (UI)

The inventory page is split into collapsible sections. Each section has its own table:

| Section | Shows Items With cloth_type |
|---|---|
| Shirting | Shirting |
| Suiting | Suiting |
| Readymade | Readymade |
| Gift Sets | Gift Sets |
| Accessories | Accessories |
| Others | Anything else (Stitching, custom, etc.) |

### Stock Operations

| Operation | When | Transaction Type |
|---|---|---|
| Opening Stock | Item created with stock > 0 | `opening` |
| Purchase / Restock | Manual restock button | `purchase` |
| Adjustment | Manual +/− correction | `adjustment` |
| Sale | Bill saved with linked item | `sale` |
| Sale Reversal | Bill edited or deleted | `sale_reversal` |

### Low Stock Alerts

Items are highlighted in the UI when `current_stock <= min_stock_alert`:
- **Yellow / LOW** — at or below threshold
- **Red / NEG** — negative stock (over-sold)

---

## QR Code System

### Tracked Item QR (`inv:`)

Generated from the inventory page for any tracked item.

**QR content:** `inv:42` (the item's database ID)

**When scanned on the bill form:**
- Fetches item details from `/api/inventory/42`
- Auto-fills: cloth type, company, quality number, MRP
- Links the bill item to inventory → stock is deducted on save
- Shows an **INV** badge on the bill row

### Current Stock QR (`cs:`)

Generated for physical stock that is **not tracked** in inventory (e.g. old stock, one-off pieces).

**QR content:**
```
cs:{"cloth_type":"Shirting","company_name":"Monti","quality_number":"M22","mrp":450,"unit_label":"m"}
```

**When scanned on the bill form:**
- Parses the JSON and auto-fills the bill row
- Does **not** link to inventory — no stock deduction
- User only needs to enter quantity

### Scanner Modes

- **USB / manual input** — works anywhere (HTTP or HTTPS)
- **Browser camera** — requires HTTPS; uses `Html5Qrcode` library; defaults to back camera

---

## Analytics & Export

### Dashboard Summary Cards

- Total bills (all time)
- Total revenue (all time)
- Unique customers
- Today's sales / This month's sales

### Period Analytics

Select period: **Daily** (last 30 days) · **Monthly** (last 12 months) · **Yearly** (last 5 years) · **Custom range**

- Stacked bar chart: Cash / Card / UPI / Combination breakdown per period
- Payment method totals + % of period revenue
- Salesperson performance table: bill count & total per person

### Excel Export

Download a formatted `.xlsx` file for any period:
- Headers with period info
- Bill rows: number, date, customer, salesperson, payment mode, amounts
- Totals row
- Frozen header pane
- Currency-formatted amount columns

---

## Frontend Architecture

### JavaScript Modules

| File | Responsibility |
|---|---|
| `api.js` | Centralised fetch wrappers — all HTTP calls go through here |
| `utils.js` | `formatCurrency()`, `formatDate()`, `debounce()`, toast alerts, spinner |
| `bill.js` | Full bill form logic: item rows, payment tabs, QR scanner, WhatsApp |
| `dashboard.js` | Chart.js charts, summary cards, analytics period switching |
| `inventory.js` | Section-grouped list, add/edit/restock modals, QR generation |
| `customers.js` | Customer list search and display |
| `history.js` | Bill history search, export trigger |

### Responsive Bill Form

`bill.js` renders items in two layouts simultaneously:

- **Desktop (≥768px):** `<table>` with one row per item
- **Mobile (<768px):** Card stack, one card per item

Both stay in sync — changes in either view update the same underlying `itemDataStore`.

### Dropdown Caching

Company lists are cached in memory on the bill form per cloth type (`companyCache` map). Subsequent selects of the same cloth type do not re-fetch.

### Inline Add for Dropdowns

On both the **Add Inventory Item** and **Current Stock QR** modals, selecting `+ Add new…` from a dropdown reveals an inline text input + Add/Cancel buttons. On save, the API is called, the dropdown refreshes, and the new option is pre-selected.

---

## Security

| Area | Implementation |
|---|---|
| Passwords | bcrypt, never stored plaintext |
| Sessions | HTTPOnly cookie, non-persistent, Lax CSRF |
| Login throttle | 5 attempts → 15-min lockout (server-side) |
| Role enforcement | Decorator on every route, both page & API |
| Last admin guard | Cannot deactivate or demote the last active admin |
| Mobile deduplication | Normalized 10-digit storage; prevents phantom duplicates |
| SQL injection | Parameterized queries throughout (no string concatenation) |
| Bill number integrity | Atomic DB update on singleton row — no race condition |

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | `'dev-only-change-in-production'` | Flask session signing key |
| `SHARE_BASE_URL` | `'https://shubhamnxtailoring.pythonanywhere.com'` | Base URL for WhatsApp bill share links |

Generate a strong secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Default Credentials

> **Change these immediately after first login.**

| Username | Password | Role |
|---|---|---|
| `admin` | `Admin@1234` | Admin |
| `staff` | `Staff@1234` | Staff |

Passwords can be changed from `/profile` (own password) or `/admin/users` (admin resets any user).
