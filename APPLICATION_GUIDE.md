# Shubham NX — Complete Application Guide

This document explains the entire Shubham NX billing, inventory, and tailoring
management system — first in plain business language (what it does and how
each part is used day to day), then as a full technical reference (database
schema, API routes, deployment) for anyone who needs to maintain or extend
the code.

---

## How to use this document

- **New to the business / not a developer?** Read **Part 1** only. It explains
  every feature in plain language with no code or jargon.
- **Maintaining or extending the code?** Skim Part 1 for context, then use
  **Part 2** as your reference.

---

## Table of Contents

### Part 1: Business Overview
1. [What This Application Is](#1-what-this-application-is)
2. [Who Uses It](#2-who-uses-it)
3. [The Modules, Explained](#3-the-modules-explained)
   - [3.1 Retail Billing](#31-retail-billing)
   - [3.2 Institution (Bulk) Billing](#32-institution-bulk-billing)
   - [3.3 Inventory Management](#33-inventory-management)
   - [3.4 Customers and Loyalty Rewards](#34-customers-and-loyalty-rewards)
   - [3.5 Tailoring Delivery Tracking](#35-tailoring-delivery-tracking)
   - [3.6 Analytics and Reports](#36-analytics-and-reports)
4. [A Day in the Life](#4-a-day-in-the-life)
5. [Where Everything Lives](#5-where-everything-lives)
6. [Data Safety and Backups](#6-data-safety-and-backups)

### Part 2: Technical Reference
7. [Tech Stack](#7-tech-stack)
8. [Project Structure](#8-project-structure)
9. [Setup and Running](#9-setup-and-running)
10. [Authentication and Roles](#10-authentication-and-roles)
11. [Billing Database Schema](#11-billing-database-schema)
12. [Tailoring Database Schema](#12-tailoring-database-schema)
13. [API Reference](#13-api-reference)
14. [Page Routes](#14-page-routes)
15. [Core Billing Workflows and Calculations](#15-core-billing-workflows-and-calculations)
16. [Inventory System and AI Invoice Scanning](#16-inventory-system-and-ai-invoice-scanning)
17. [QR Code System](#17-qr-code-system)
18. [Tailoring Delivery System In Depth](#18-tailoring-delivery-system-in-depth)
19. [Loyalty Program In Depth](#19-loyalty-program-in-depth)
20. [Institution Billing In Depth](#20-institution-billing-in-depth)
21. [Frontend Architecture](#21-frontend-architecture)
22. [Security](#22-security)
23. [Environment Variables](#23-environment-variables)
24. [Deployment (PythonAnywhere)](#24-deployment-pythonanywhere)
25. [Default Credentials](#25-default-credentials)

---
---

# PART 1 — BUSINESS OVERVIEW

## 1. What This Application Is

Shubham NX is a custom-built management system for a fabric and tailoring
business. It replaces paper bill books, paper tailoring receipt books, and
manual stock registers with one application that runs in a web browser —
on the shop's computer, a phone, or a tablet.

It covers six connected areas of the business:

1. **Retail billing** — selling fabric/garments to walk-in customers.
2. **Institution billing** — bulk orders for schools, colleges, or companies.
3. **Inventory** — tracking how much stock of each fabric is on the shelf.
4. **Customers & loyalty** — who buys, how much, and automatic reward gifts.
5. **Tailoring delivery tracking** — the separate stitching/order business,
   from taking measurements to handing over the finished garment.
6. **Analytics** — sales trends, reports, and Excel exports for accounting.

It is used every day by shop staff at the billing counter and by the owner
for oversight, reporting, and decisions (stock reorders, gift fulfillment,
staff accounts).

## 2. Who Uses It

There are two account types:

| Role | Can do |
|---|---|
| **Admin** (owner/manager) | Everything: billing, institution billing, inventory, customers, loyalty settings, analytics, tailoring, user management, deleting/cancelling records |
| **Staff** (counter/sales) | Create new retail bills and institution bills, use the tailoring system, change their own password |

A staff account cannot view analytics, manage inventory, see the customer
list, touch loyalty settings, or manage other user accounts — only an admin
can do those. This keeps sensitive business data (totals, customer lists,
staff accounts) restricted to the owner/manager.

## 3. The Modules, Explained

### 3.1 Retail Billing

The core of the system: creating a bill for a walk-in customer buying fabric
or ready-made garments.

- Staff search the customer by mobile number — if they've bought before,
  their name auto-fills; if not, a new customer record is created
  automatically.
- Each item on the bill (e.g., "2.5 metres of Monti Shirting") can either be
  picked from the shop's tracked **inventory** (which reduces stock
  automatically) or entered as a one-off item that isn't tracked.
- Discounts, quantity, and price are entered per item; the bill total,
  savings, and balance are calculated automatically.
- Payment can be split across Cash / Card / UPI, or marked as pending.
- Once saved, the bill can be **printed**, **shared via WhatsApp** (a link
  the customer can open to see their own receipt), or copied as a link.
- Bills can be edited or deleted later by an admin — deleting one
  automatically renumbers every bill after it so the bill number sequence
  never has gaps.

### 3.2 Institution (Bulk) Billing

A **separate billing flow**, used specifically for bulk institutional
orders — for example, a school or college ordering uniform fabric for many
students at once, with a stitching charge per piece.

Key differences from retail billing:
- It is not tied to the regular customer list — you type the institution's
  name, address, and a contact person's name/mobile directly on the bill,
  and it never affects retail customer records or loyalty.
- Line items describe *quantity per piece × rate per metre × number of
  pieces*, plus a stitching charge per piece — matching how bulk uniform
  orders are actually priced.
- It supports an advance payment up front and additional payments recorded
  later as the institution pays off the balance (much like a purchase order
  arrangement).
- Two documents can be printed from one bill: a normal **Invoice** and a
  **Performa Invoice** (a quotation-style document often needed for an
  institution's internal approval process before the final invoice).
- Institution orders use their own separate bill numbering
  (`INST-0001/26-27`) so they never mix with regular retail bill numbers.
- **Institution billing does not touch shop stock at all.** It is a
  financial record of a bulk deal, not a sale against tracked inventory —
  useful to know, since it means stock counts are unaffected by these bills.

### 3.3 Inventory Management

Tracks how much of each fabric/company/quality is physically in stock, so
staff always know what's available and get warned before running out.

- Every tracked item gets an auto-generated code (e.g., `SHT-001` for the
  first Shirting item, `SUT-003` for the third Suiting item).
- Stock goes up on purchase/restock and opening stock entry, and goes down
  automatically the moment it's sold on a bill — no manual subtraction
  needed.
- Items dropping to or below a set "low stock" threshold are flagged in
  yellow; anything oversold into negative stock is flagged in red.
- Every stock movement (sale, purchase, manual correction) is logged with a
  timestamp and reason, so stock discrepancies can always be traced back.
- **AI Invoice Scanning**: instead of typing in a new delivery from a
  supplier by hand, an admin can photograph the paper invoice the supplier
  hands over. The photo is read automatically (using Anthropic's Claude AI)
  and the form pre-fills — supplier name, invoice number/date, fabric type,
  brand, and every line item (design, quality number, shade, quantity).
  Staff review each item, correct anything misread, and save them all in
  one go. **Nothing is added to stock until a human reviews and confirms
  it** — the AI only suggests values, it never writes to the database on
  its own. This feature needs an Anthropic API key configured by the owner;
  if that's not set up, everything else in the app still works fine — items
  just need to be typed in manually.
- Every item can also generate a printable **QR code sticker**, so staff can
  scan an item at billing time instead of searching for it (see §3.3
  QR Codes below, or the technical section for detail).

### 3.4 Customers and Loyalty Rewards

Every retail customer who's ever bought something is stored, searchable by
name or mobile number, with their full bill history visible to an admin.

The **Loyalty Program** rewards a customer's biggest spenders automatically:
- As a customer's total retail spend crosses set milestones — ₹10,000
  (Silver), ₹20,000 (Gold), ₹30,000 (Platinum), ₹50,000 (Diamond) — within
  a running 12-month cycle, they're automatically bumped to that tier the
  moment a qualifying bill is saved.
- There are no "points" to track or redeem — it's a straightforward
  "spend this much, unlock this gift" system.
- When a customer crosses a milestone, staff see a celebratory banner on
  screen right after saving the bill.
- The owner manages the program from a dedicated Loyalty page: turning it
  on/off, setting the date the yearly cycle starts, and — most
  importantly — a running list of **gifts owed but not yet handed over**.
  Staff/owner mark a gift as "given" once it's physically handed to the
  customer, which records who gave it and when.
- Only retail bills count toward loyalty spend — institution bills and
  tailoring orders don't contribute, since they're separate businesses
  within the same shop.
- The loyalty program (both the settings page and viewing a customer's
  tier/progress) is restricted to admin accounts.

### 3.5 Tailoring Delivery Tracking

A separate system for the shop's stitching/tailoring side of the business —
distinct from retail billing, with its own dashboard built for the daily
question: *"What needs to be delivered, and is it ready?"*

- Every order is entered with the **order number written in the shop's
  paper receipt book** (typed in manually and required — the system never
  invents its own numbers, so it always matches what's written on the
  customer's paper receipt).
- Each order lists the garments being stitched, with a quantity, rate, and
  its own progress: **In Stitching → Trial Ready → Full Stitched →
  Delivered**. An order's overall status is always its *least* finished
  garment — so an order isn't "done" until every piece in it is.
- **Cloth sample photos** can be attached per garment (so staff remember
  exactly which fabric was used), and **measurement photos** can be
  attached to the whole order — kept strictly internal and never shown on
  the customer's receipt link.
- **Payments** are recorded one at a time with a running history (amount,
  method, date/time) — exactly like a bank passbook — rather than typing
  in a "new total," so nothing gets miscounted.
- A **Dashboard tab** shows, at a glance:
  - The next 15 days' delivery load — how many orders and how many of each
    garment type (e.g., "Shirt – 5, Trouser – 6") are due each day, so
    staff can promise a realistic delivery date to a new customer.
  - **Overdue work** — orders whose delivery date has passed and stitching
    still isn't finished.
  - **Ready & waiting pickup** — orders that are fully stitched and the
    delivery date has arrived, so it's time to call the customer, not
    chase the tailor.
  - Trials and deliveries due today and tomorrow.
- A **Customers tab** groups every tailoring order by customer, showing
  their order history, total business, and any pending balance.
- Every night (the shop closes at 10pm, and the tailor works after that), a
  **Tailor Work Report** can be generated with one tap — everything
  overdue plus everything due tomorrow, including cloth sample and
  measurement photos — and sent to the tailor over WhatsApp as a single
  link (works even without the tailor logging in), or printed as a paper
  slip for the workbench.
- A shareable **receipt link** can be sent to the customer via WhatsApp so
  they can check their order (garments, dates, balance, cloth photos —
  never measurement photos) without calling the shop.

### 3.6 Analytics and Reports

For the owner: dashboards and exports covering the retail billing side of
the business.

- Summary cards: total bills, total revenue, unique customers, today's and
  this month's sales.
- Breakdowns by day, month, year, or a custom date range, with a chart
  comparing Cash / Card / UPI / Combination payment methods.
- Per-salesperson performance (bill count and total sales).
- One-click **Excel export** of bills for any period — formatted with
  totals, ready to hand to an accountant.

## 4. A Day in the Life

**Morning, retail counter:** A customer walks in wanting fabric. Staff
search their mobile number — they've bought before, so their name auto-
fills. Staff add two items, apply a small discount, take payment split
between Cash and UPI, save, and print the bill. If this purchase crosses a
loyalty milestone, a banner appears — the gift gets added to the owner's
"to hand over" list automatically.

**Midday, a school calls in** wanting 200 metres of uniform fabric stitched
into 100 shirts. Staff open a new Institution Bill, type in the school's
name and contact, enter the fabric/rate/stitching charge, and take a
partial advance payment — the balance gets settled later as the school
pays it off.

**Afternoon, tailoring:** A customer drops off cloth for a kurta. Staff open
the Tailoring page, create a new order using the number from the paper
receipt book, photograph the cloth sample, and set a trial date. As
stitching progresses over the coming days, staff move the garment through
its stages; when it's fully stitched and the delivery date arrives, it
shows up on the dashboard's "Ready & waiting pickup" list — time to call
the customer.

**Night, 10pm, shop closing:** The owner opens the Tailoring dashboard, taps
"Tailor Report," and sends it to the tailor over WhatsApp — a clear list of
what's overdue and what's due tomorrow, with photos, so the tailor knows
exactly what to work on overnight.

**End of month:** The owner opens Analytics, reviews the month's sales
trend and salesperson performance, and exports an Excel sheet for the
accountant. Separately, they check the Loyalty page for any gifts still
owed and the Inventory page for anything running low before the next
restock.

## 5. Where Everything Lives

- The application is hosted on **PythonAnywhere**, a service that keeps it
  running online continuously — no need to leave a shop computer switched
  on. Staff and the owner access it from a normal web browser, from any
  device (computer, phone, tablet).
- The retail/institution billing data lives in one database file, and the
  tailoring system keeps its own **completely separate** database file — a
  deliberate design choice so the two businesses' data never mix or
  interfere with each other, even though they're accessed from the same
  application.
- Photos (cloth samples, measurements, invoice scans) are saved as image
  files. By default, they're stored directly on the PythonAnywhere server.
  Optionally, they can instead be stored on **Cloudflare R2** — a free
  cloud storage service — which keeps the server's own limited storage
  space free for the app and its databases as photo volume grows over
  time. This is entirely optional and can be turned on later without
  losing any existing photos.

## 6. Data Safety and Backups

- Passwords are never stored in plain text — they're scrambled
  (hashed) in a way that can't be reversed, even by someone with direct
  database access.
- Five wrong login attempts locks an account out for 15 minutes,
  protecting against someone guessing passwords.
- **Backing up the business's data means backing up more than one file**:
  the billing database, the tailoring database, and — if photos are stored
  locally rather than on Cloudflare R2 — the folder containing all
  uploaded photos. A backup of only one of these leaves data behind.

---
---

# PART 2 — TECHNICAL REFERENCE

## 7. Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask |
| Databases | SQLite (WAL mode) — **two separate files**: `billing.db` (retail/institution/loyalty) and `tailoring.db` (tailoring system) |
| Auth | Flask sessions + bcrypt |
| Frontend | Vanilla JS, HTML/CSS (no framework/build step) |
| Charts | Chart.js |
| QR Codes | `qrcode[pil]` (server-side generation), `Html5Qrcode` (browser camera scanning) |
| Excel Export | openpyxl |
| AI Invoice Scanning | Anthropic API (`claude-haiku-4-5`, vision) |
| Photo Storage | Local disk, or optionally Cloudflare R2 (S3-compatible, via `boto3`) |
| Deployment | PythonAnywhere |

## 8. Project Structure

```
shubham-nx-billing/
├── app.py                    # App factory, blueprint registration, context processors
├── requirements.txt
├── .env.example               # Template for environment variables (never commit real .env)
│
├── db/
│   ├── connection.py          # SQLite connection (WAL mode, row_factory) — billing.db
│   ├── schema.py               # CREATE TABLE statements + migrations — billing.db
│   ├── tailoring.py            # Fully separate connection + schema — tailoring.db
│   └── __init__.py             # get_db(), close_db(), init_db(), seed_default_users()
│
├── routes/
│   ├── bills.py                 # Retail bill CRUD
│   ├── institution_bills.py     # Institution (bulk) bill CRUD — own numbering, no inventory link
│   ├── customers.py             # Customer lookup
│   ├── companies.py             # Company dropdown management
│   ├── cloth_types.py           # Cloth type management
│   ├── salespersons.py          # Salesperson management
│   ├── suppliers.py             # Supplier management
│   ├── inventory.py             # Inventory CRUD + stock ops + QR + AI invoice scanning
│   ├── analytics.py             # Sales analytics endpoints
│   ├── export.py                # Excel export
│   ├── loyalty.py                # Loyalty settings, gifts, per-customer status
│   ├── tailoring.py              # Tailoring orders, dashboard, customers, payments, report
│   └── pages.py                  # HTML page routes for all of the above
│
├── services/
│   ├── billing.py               # Bill + institution-bill calculation & validation logic
│   ├── inventory.py              # Stock deduction & restoration
│   ├── loyalty.py                 # Tier thresholds, cycle rollover, gift unlocking
│   ├── customers.py               # Customer lookup/stats helpers
│   ├── auth.py                    # Login decorators (page + API, admin + login)
│   └── r2_storage.py               # Optional Cloudflare R2 client for tailoring photos
│
├── static/
│   ├── css/
│   └── js/
│       ├── common.js             # Shared helpers loaded on every page (escapeHtml, date-input fix, loyalty tier maps)
│       ├── bill-state.js         # Shared state, constants & utilities for retail bill pages
│       ├── bill-items.js         # Item rows, cloth types, inventory links
│       ├── bill-payments.js      # Payment tabs, combo split, summary totals
│       ├── bill-modals.js        # Add cloth type / company / salesperson modals
│       ├── bill-qr.js            # QR / barcode scanner logic
│       ├── bill-share.js         # WhatsApp message builder & share-link helpers
│       ├── bill-form.js          # Retail bill form init, validation, save, mobile search
│       ├── dashboard.js          # Analytics dashboard
│       ├── inventory.js          # Inventory page + AI invoice scanning UI
│       ├── customers.js          # Customers page (+ loyalty status card)
│       ├── loyalty.js             # Loyalty settings page
│       ├── tailoring.js           # Entire tailoring UI: dashboard, orders, customers, payments, photos
│       └── history.js            # Bill history page
│
├── uploads/
│   └── tailoring/                # Locally-stored tailoring photos (if R2 not configured)
│
└── templates/
    ├── base.html
    ├── login.html
    ├── dashboard.html
    ├── new_bill.html / edit_bill.html / bill_detail.html / bill_history.html / _bill_form.html
    ├── new_institution_bill.html / edit_institution_bill.html / institution_bill_detail.html
    ├── shared_bill.html / shared_bill_not_found.html
    ├── customers.html / customer_detail.html
    ├── inventory.html
    ├── loyalty.html
    ├── tailoring.html / tailoring_receipt.html / tailoring_receipt_not_found.html / tailoring_report.html
    ├── admin_users.html / profile.html / unauthorized.html
```

## 9. Setup and Running

### Install dependencies
```bash
pip install -r requirements.txt
```

### Run the app
```bash
python app.py
```
Runs on `http://0.0.0.0:8081`. Both databases (`billing.db`, `tailoring.db`)
are created automatically on first run with all tables and seed data.

### Run the test suite
```bash
python -m pytest tests/ -q
```

## 10. Authentication and Roles

### Roles

| Role | Access |
|---|---|
| `admin` | Everything — billing, institution billing, inventory, customers, loyalty, analytics, tailoring, user management |
| `staff` | New retail/institution bill creation, full tailoring system access, own password change |

### Login Security
- Passwords hashed with bcrypt.
- **5 failed attempts** triggers a **15-minute lockout**.
- Sessions expire on browser close (non-persistent).
- HTTPOnly + SameSite=Lax cookies.

### Auth Decorators

| Decorator | Layer | Behavior on Failure |
|---|---|---|
| `@login_required` | Page | Redirect to `/login` |
| `@admin_required` | Page | Redirect to `/unauthorized` |
| `@staff_or_admin_required` | Page | Allows both roles |
| `@api_login_required` | API | `401 JSON` |
| `@api_admin_required` | API | `403 JSON` |

## 11. Billing Database Schema

`billing.db` — covers retail billing, institution billing, inventory,
customers, and loyalty.

### `customers`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT NOT NULL | |
| `mobile` | TEXT NOT NULL | Raw input |
| `normalized_mobile` | TEXT UNIQUE | 10-digit, strips +91/0 |
| `created_at`, `updated_at` | TEXT | |

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

### `bills` (retail)
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `bill_number` | TEXT UNIQUE | Format: `SHN-0001/26-27` |
| `customer_id` | INTEGER | FK → customers |
| `customer_name_snapshot`, `customer_mobile_snapshot` | TEXT | Snapshot at billing time |
| `bill_date` | TEXT | YYYY-MM-DD |
| `subtotal`, `total_discount`, `final_total`, `total_savings` | REAL | See §15 calculation logic |
| `advance_paid`, `remaining` | REAL | |
| `salesperson_name` | TEXT | |
| `payment_mode_type` | TEXT | Cash / Card / UPI / Combination |
| `status` | TEXT | `"active"` (default) |

### `bill_items`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `bill_id` | INTEGER | FK → bills (CASCADE DELETE) |
| `cloth_type`, `company_name`, `quality_number` | TEXT | |
| `quantity` | REAL NOT NULL | |
| `unit_label` | TEXT | `"m"` or `"pcs"` |
| `mrp`, `line_total`, `discount_percent`, `discount_amount`, `rate_after_disc`, `final_amount` | REAL | See §15 |
| `inventory_item_id` | INTEGER | FK → inventory_items (nullable — null if not stock-tracked) |

### `bill_payments`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `bill_id` | INTEGER | FK → bills (CASCADE DELETE) |
| `payment_method` | TEXT | Cash / Card / UPI |
| `amount` | REAL NOT NULL | |

### `bill_number_seq`
Singleton table (`id = 1`, enforced via CHECK constraint). `next_val`
increments atomically per financial year — prevents duplicate bill numbers
under concurrent requests.

### `inventory_items`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `item_code` | TEXT UNIQUE | Auto-generated: `SHT-001`, `SUT-002`, etc. |
| `cloth_type`, `company_name`, `quality_number` | TEXT | |
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
| `notes`, `created_by` | TEXT | |

### `institution_bills`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `bill_number` | TEXT UNIQUE | Format: `INST-0001/26-27` |
| `company_name`, `company_address` | TEXT | Free text — **no link to `customers` table** |
| `contact_person_name`, `contact_person_mobile` | TEXT | |
| `bill_date` | TEXT | |
| `subtotal`, `final_total`, `advance_paid`, `remaining` | REAL | |
| `salesperson_name` | TEXT | |
| `payment_mode_type` | TEXT | Cash / Card / UPI / Cheque / NEFT / Combination |
| `status` | TEXT | `active` / `cancelled` |
| `created_at`, `updated_at` | TEXT | |

### `institution_bill_items`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `bill_id` | INTEGER | FK → institution_bills (CASCADE DELETE) |
| `cloth_type`, `company_name`, `quality_number` | TEXT | **Free text — not linked to `inventory_items`** |
| `quantity_per_pc`, `rate_per_m`, `no_of_pcs`, `stitching_per_unit` | REAL | See §20 for total formula |
| `total` | REAL | |

### `institution_bill_payments`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `bill_id` | INTEGER | FK → institution_bills |
| `payment_method` | TEXT | |
| `amount` | REAL NOT NULL | |
| `paid_at` | TEXT | |

### `inst_bill_number_seq`
Same singleton pattern as `bill_number_seq`, kept entirely separate so
institution bill numbers never collide with retail bill numbers.

### `loyalty_settings`
Single row (`id = 1`): `enabled` (0/1), `activation_date` (seeds the next
upcoming cycle).

### `loyalty_cycles`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `cycle_number` | INTEGER | |
| `start_date`, `end_date` | TEXT | Exactly 1 year apart, leap-year safe |
| `created_at` | TEXT | |
| UNIQUE | | `cycle_number`, and `start_date` |

Rows are immutable once created; unique constraints protect against a race
where two concurrent requests both try to roll the cycle over at once.

### `loyalty_gifts`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `customer_id` | INTEGER | FK → customers |
| `tier` | TEXT | silver / gold / platinum / diamond |
| `cycle_id` | INTEGER | FK → loyalty_cycles |
| `bill_id` | INTEGER | FK → bills — the bill that triggered the unlock |
| `given_at`, `given_by` | TEXT | Null until physically handed over |
| UNIQUE | | `(customer_id, tier, cycle_id)` — one unlock per tier per cycle |

## 12. Tailoring Database Schema

`tailoring.db` — **entirely separate file and connection** from
`billing.db`. Deliberately isolated so the tailoring business's data can
never mix with or corrupt retail/institution billing data.

### `tailoring_orders`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `order_number` | INTEGER UNIQUE | **Manually typed by staff from the paper receipt book — required, not auto-generated** |
| `order_date` | TEXT NOT NULL | |
| `customer_name`, `mobile`, `address` | TEXT | |
| `trial_date`, `delivery_date` | TEXT | Nullable |
| `total`, `advance`, `balance` | REAL | `advance` is kept in sync with the sum of `tailoring_payments` rows |
| `payment_mode`, `notes` | TEXT | |
| `created_at`, `updated_at` | TEXT | |

### `tailoring_items` (garments within an order)
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `order_id` | INTEGER | FK → tailoring_orders (CASCADE DELETE) |
| `garment_type` | TEXT NOT NULL | |
| `qty`, `rate`, `amount` | NUMERIC | |
| `stage` | TEXT | `In Stitching` → `Trial Ready` → `Full Stitched` → `Delivered` |
| `notes` | TEXT | |

An order's overall stage (shown as its badge) is always the **earliest**
stage among its garments — an order is only as "done" as its least-finished
piece.

### `tailoring_photos`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `order_id` | INTEGER | FK → tailoring_orders (CASCADE DELETE) |
| `item_id` | INTEGER | FK → tailoring_items (nullable) — null means a whole-order "measurement photo"; set means a per-garment "cloth sample photo" |
| `filename` | TEXT NOT NULL | Random UUID-based name; may live on local disk or Cloudflare R2 |
| `created_at` | TEXT | |

### `tailoring_payments`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `order_id` | INTEGER | FK → tailoring_orders (CASCADE DELETE) |
| `amount` | REAL NOT NULL | |
| `mode`, `note` | TEXT | e.g. note = `"Advance"` for the initial payment at order creation |
| `paid_at` | TEXT | |

Every payment (including the initial advance) is one row here — a running
history, not a single overwritable "total paid" field.

## 13. API Reference

All API routes are prefixed with `/api`. Auth levels: **Login** = any
logged-in user, **Admin** = admin role only.

### Retail Bills
| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/bills` | Admin | List bills; search via `?search=`, `?billNumber=`, `?mobile=`, `?name=` |
| `POST` | `/bills` | Login | Create bill |
| `GET` | `/bills/<id>` | Admin | Full bill detail with items & payments |
| `PUT` | `/bills/<id>` | Admin | Edit bill (restores old inventory, applies new) |
| `DELETE` | `/bills/<id>` | Admin | Delete bill + renumber all higher bills |

### Institution Bills
| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/institution-bills` | Login | Create bill |
| `GET` | `/institution-bills` | Login | List all (with item count) |
| `GET` | `/institution-bills/search` | Login | Filter by `?billNumber=`, `?name=`, `?mobile=` |
| `GET` | `/institution-bills/<id>` | Login | Full detail |
| `PUT` | `/institution-bills/<id>` | Login | Update (blocked if cancelled) |
| `PUT` | `/institution-bills/<id>/cancel` | Login | Soft-cancel |
| `PUT` | `/institution-bills/<id>/restore` | Admin | Un-cancel |
| `DELETE` | `/institution-bills/<id>` | Admin | Hard delete + renumber same-FY bills above it |
| `POST` | `/institution-bills/<id>/record-payment` | Login | Record an additional payment |

### Customers
| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/customers` | Admin | List all; search via `?search=` |
| `GET` | `/customers/search` | Login | Lookup by mobile (for bill form) |
| `GET` | `/customers/<id>` | Admin | Customer detail |
| `GET` | `/customers/<id>/bills` | Admin | All bills for a customer |

### Loyalty
| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/loyalty/settings` | Admin | `enabled`, `activation_date`, `current_cycle` (rolls cycle forward if due) |
| `POST` | `/loyalty/settings/toggle` | Admin | Pause/resume the program |
| `POST` | `/loyalty/settings/activation-date` | Admin | Set/change the cycle start date |
| `GET` | `/loyalty/pending-gifts` | Admin | Unclaimed gifts, newest first |
| `POST` | `/loyalty/gifts/<gift_id>/mark-given` | Admin | Mark a gift delivered |
| `GET` | `/loyalty/customer/<customer_id>` | Admin | Tier, cycle spend, progress to next tier |

### Cloth Types / Companies / Salespersons / Suppliers
| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/cloth-types` | Login | All cloth types |
| `POST` | `/cloth-types` | Login | Add new `{ "type_name": "..." }` |
| `GET` | `/companies?clothType=Shirting` | Login | Companies for a cloth type |
| `POST` | `/companies` | Login | Add `{ "cloth_type": "...", "company_name": "..." }` |
| `GET` | `/salespersons` | Login | All salespersons |
| `POST` | `/salespersons` | Admin | Add `{ "name": "..." }` |
| `GET` | `/suppliers` | Login | All suppliers |
| `POST` | `/suppliers` | Admin | Add `{ "name": "..." }` |

### Inventory
| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/inventory` | Admin | All items |
| `GET` | `/inventory/<id>` | Login | Single item |
| `POST` | `/inventory` | Admin | Create item (auto-generates item_code) |
| `POST` | `/inventory/batch` | Admin | Bulk-create items (used by AI scan "Save All") |
| `PUT` | `/inventory/<id>` | Admin | Update MRP, min_stock_alert, notes |
| `DELETE` | `/inventory/<id>` | Admin | Delete (blocked if referenced in bills) |
| `POST` | `/inventory/<id>/restock` | Admin | Add stock |
| `POST` | `/inventory/<id>/adjust` | Admin | Adjust `{ "quantity": -3, "notes": "..." }` |
| `GET` | `/inventory/<id>/transactions` | Admin | Transaction history |
| `GET` | `/inventory/low-stock` | Admin | Items at/below alert threshold |
| `GET` | `/inventory/<id>/qr` | Admin | PNG QR for a tracked item |
| `POST` | `/inventory/current-stock-qr` | Admin | PNG QR for an untracked item |
| `POST` | `/inventory/scan-invoice` | Admin | AI-read a photographed supplier invoice (see §16) |

### Analytics and Export
| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/analytics/summary` | Admin | KPIs: total bills, sales, customers, payment breakdown |
| `GET` | `/analytics` | Admin | Period breakdown |
| `GET` | `/analytics/salespersons` | Admin | Per-salesperson performance |
| `GET` | `/export/bills` | Admin | Download XLSX for a period |

### Auth / Users
| Method | Path | Auth | Description |
|---|---|---|---|
| `GET/POST` | `/login` | None | Login form |
| `GET` | `/logout` | Any | Clear session |
| `PUT` | `/api/users/me/password` | Login | Change own password |
| `GET` | `/api/users` | Admin | List users |
| `POST` | `/api/users` | Admin | Create user |
| `PUT` | `/api/users/<id>/password` | Admin | Reset user password |
| `PUT` | `/api/users/<id>/toggle-status` | Admin | Activate/deactivate user |

### Tailoring
| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/tailoring/meta` | Login | Stage list + garment type list |
| `POST` | `/tailoring/orders` | Login | Create order (manual order number required) |
| `GET` | `/tailoring/orders` | Login | List/filter/search orders + dashboard counts |
| `GET` | `/tailoring/orders/<id>` | Login | Full order detail |
| `PUT` | `/tailoring/orders/<id>` | Login | Edit order |
| `DELETE` | `/tailoring/orders/<id>` | Login | Delete order (+ its photos) |
| `PATCH` | `/tailoring/items/<id>/stage` | Login | Change one garment's stage |
| `PATCH` | `/tailoring/orders/<id>/stage` | Login | Set every garment's stage at once |
| `POST` | `/tailoring/orders/<id>/payments` | Login | Record one payment (with history) |
| `DELETE` | `/tailoring/payments/<id>` | Login | Undo a payment entry |
| `PATCH` | `/tailoring/orders/<id>/payment` | Login | *(legacy)* set the running total directly |
| `POST` | `/tailoring/orders/<id>/photos` | Login | Upload a photo (goes to R2 if configured, else local disk) |
| `DELETE` | `/tailoring/photos/<id>` | Login | Delete a photo (from wherever it's stored) |
| `GET` | `/tailoring/customers` | Login | Customer list derived from orders |
| `GET` | `/tailoring/dashboard` | Login | 15-day load, overdue, ready-for-pickup, today/tomorrow lists |

## 14. Page Routes

| Path | Auth | Purpose |
|---|---|---|
| `/` | Admin | Analytics dashboard |
| `/new-bill` | Staff+ | Create a retail bill |
| `/bill-history` | Admin | Search & browse all bills |
| `/bills/<id>` | Admin | Bill detail & print |
| `/edit-bill/<id>` | Admin | Edit existing bill |
| `/new-institution-bill` | Staff+ | Create an institution bill |
| `/institution-bills/<id>` | Admin | Institution bill detail |
| `/edit-institution-bill/<id>` | Admin | Edit institution bill |
| `/customers` | Admin | Customer list |
| `/customers/<id>` | Admin | Customer profile, bill history, loyalty status |
| `/inventory` | Admin | Inventory management + AI invoice scanning |
| `/loyalty` | Admin | Loyalty settings + pending gifts |
| `/tailoring` | Login | Tailoring dashboard / orders / customers |
| `/tailoring/report` | Login | Tailor work report (printable + WhatsApp) |
| `/tailoring/report/share/<token>` | None | Public tailor-facing report link (expires in ~2 days) |
| `/tailoring/share/<order_number>` | None | Public customer receipt link |
| `/admin/users` | Admin | User management |
| `/profile` | Login | Change own password |
| `/bill/share/<bill_number>` | None | Public bill view (shareable link) |

## 15. Core Billing Workflows and Calculations

### Creating a Retail Bill
1. Open `/new-bill`.
2. Search customer by mobile → name auto-fills (or creates new customer).
3. Add items: select cloth type → company loads → enter qty, MRP, discount.
4. System computes per-item: `line_total`, `discount_amount`,
   `rate_after_disc`, `final_amount`.
5. Select payment mode: Cash / Card / UPI / Combination.
6. Enter advance paid → remaining balance computed.
7. Submit → server validates, saves bill, deducts linked inventory, logs
   transactions, checks loyalty milestones.
8. Success: Print, WhatsApp share, copy link buttons appear.

### Editing / Deleting a Bill
- Editing restores old inventory quantities, then applies new ones; bill
  number stays the same.
- Deleting is a hard delete — bill and all items/payments removed, and all
  bills with higher numbers are renumbered down to keep the sequence
  gapless; inventory is restored for any linked items.

### Retail Bill Calculation
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
All rounding uses `ROUND_HALF_UP` to 2 decimal places (matches JS
`Math.round` behaviour).

## 16. Inventory System and AI Invoice Scanning

### Item Codes
Auto-generated from the cloth type when an item is created:
`SHT-001` (Shirting, first item), `SUT-003` (Suiting, third item),
`OTH-001` (Stitching or any other type). Sequential per prefix.

### Stock Operations
| Operation | When | Transaction Type |
|---|---|---|
| Opening Stock | Item created with stock > 0 | `opening` |
| Purchase / Restock | Manual restock button | `purchase` |
| Adjustment | Manual +/− correction | `adjustment` |
| Sale | Bill saved with linked item | `sale` |
| Sale Reversal | Bill edited or deleted | `sale_reversal` |

### Low Stock Alerts
Highlighted when `current_stock <= min_stock_alert` (yellow/LOW); negative
stock shows red/NEG.

### AI Invoice Scanning
`POST /api/inventory/scan-invoice` (admin only) accepts a photographed
supplier invoice as `multipart/form-data`.

- Requires `ANTHROPIC_API_KEY` in the environment; if missing, returns a
  clear JSON error rather than failing silently.
- Sends the image to Anthropic's **`claude-haiku-4-5`** model (hardcoded,
  not configurable) with a fabric-industry-specific extraction prompt,
  requesting a strict JSON object: invoice-level fields (supplier name,
  invoice number/date, cloth type, company) plus a list of line items
  (item name, quality number, shade number, opening stock, unit, notes).
- Robust parsing: strips markdown code fences, attempts to salvage a
  truncated response (if the model hits its 2048-token limit on a long
  invoice) by trimming the incomplete trailing item and re-closing the
  JSON array; falls back to regex-extracting complete objects; if nothing
  can be salvaged, returns the raw model text with a 422 so the frontend
  can show the user what was actually returned.
- The frontend (`inventory.js`) fuzzy-matches invoice-level fields against
  existing dropdown options, walks through each scanned line item one at a
  time for review/correction, and only writes to the database once the
  user clicks "Save All" (`POST /api/inventory/batch`) — **the AI never
  writes directly to inventory**.

## 17. QR Code System

### Tracked Item QR (`inv:`)
Generated from the inventory page for any tracked item. QR content:
`inv:42` (the item's database ID). When scanned on the bill form: fetches
`/api/inventory/42`, auto-fills cloth type/company/quality/MRP, links the
bill item to inventory (stock is deducted on save), shows an **INV** badge.

### Current Stock QR (`cs:`)
Generated for physical stock **not tracked** in inventory. QR content is a
JSON blob (cloth type, company, quality, MRP, unit). When scanned: parses
and auto-fills the row but does **not** link to inventory — no stock
deduction; user only enters quantity.

### Scanner Modes
- **USB / manual input** — works anywhere (HTTP or HTTPS).
- **Browser camera** — requires HTTPS; uses `Html5Qrcode`; defaults to
  back camera.

## 18. Tailoring Delivery System In Depth

### Order Numbering
`order_number` is **required and typed by the user** on both create and
edit — there is no auto-incrementing sequence. The server enforces
uniqueness with a check-then-insert, backed by the database's own UNIQUE
constraint (caught via `sqlite3.IntegrityError`) so a same-instant race
between two devices still returns a friendly "already exists" error rather
than a raw 500.

### Stages and Derived Status
Garment stages: `In Stitching → Trial Ready → Full Stitched → Delivered`.
An order's stage = the *earliest* stage among its items
(`_derived_stage`). Several statuses are **computed, not stored**:

- **Overdue** (`_is_overdue`): delivery date has passed **and** the order's
  stage is not yet `Full Stitched`/`Delivered`. Once every garment is fully
  stitched, a late pickup is the customer's responsibility, not the shop's
  — it drops out of "overdue" permanently at that point.
- **Ready & waiting pickup**: stage is `Full Stitched` and the delivery
  date has arrived or passed (or was never set).

### Dashboard (`GET /tailoring/dashboard`)
Builds, from all open (non-Delivered) orders:
- `days`: next 15 days, each with order count and a per-garment-type
  pending count (e.g. `{"Shirt": 5, "Trouser": 6}`), plus that day's trial
  count.
- `overdue`, `ready_waiting`, `deliveries_today`, `deliveries_tomorrow`,
  `trials_today`, `trials_tomorrow` — each a list of compact order
  summaries (`_order_brief`).

### Photos and Cloudflare R2 (`services/r2_storage.py`)
- Uploaded photos are resized (max 1400px longest side) and re-encoded as
  JPEG (quality 82) before storage — regardless of destination.
- **Optional R2 offload**: if all five `R2_*` environment variables are
  set, new photos upload directly to the Cloudflare R2 bucket via
  `boto3`'s S3-compatible client; if not configured, or if the R2 upload
  fails for any reason, photos fall back to local disk automatically — a
  photo is never silently lost.
- **Serving** (`GET /tailoring/photos/<filename>`): checks local disk
  first (so every photo uploaded before R2 was configured keeps working
  unchanged), and only redirects (302) to the R2 public URL if the file
  isn't found locally. No migration of old photos is needed.
- **Deletion** removes the file from wherever it actually lives (local
  disk and/or R2, best-effort).
- Whole-order photos (`item_id IS NULL`) are "measurement photos" and are
  **never rendered on the customer receipt template** — only per-garment
  cloth sample photos are. (Caveat: photos uploaded before the per-garment
  photo feature existed are all stored as whole-order photos, so they are
  also treated as measurement photos and won't appear on old receipt
  links.)

### Payments
`tailoring_payments` is an append-only history table. Recording a payment
(`POST /tailoring/orders/<id>/payments`) adds one row and updates the
order's `advance`/`balance`; deleting a payment entry reverses both. The
order's `advance` column is also (still) directly editable via the order
edit form and the legacy PATCH endpoint — **these do not create or adjust
payment history rows**, so an order edited this way can accumulate an
`unrecorded_paid` difference between its stored `advance` and the sum of
its logged payments. This is surfaced back to the UI (an "earlier
payments — no details recorded" line) rather than hidden, but is a known
inconsistency to be aware of if extending this code.

### Tailor Work Report (`/tailoring/report`, `/tailoring/report/share/<token>`)
- Staff-facing page (`login_required`) computes: overdue orders, and
  tomorrow's deliveries/trials still needing work (garments already
  Full Stitched are excluded from "needs work" so the tailor isn't shown
  finished pieces).
- A **public share link** is generated with a token = HMAC-SHA256 of the
  date, keyed with the Flask app's `SECRET_KEY` — no separate secret
  storage needed. The token is accepted for **today's and yesterday's**
  date, so a link sent at 10pm still works after midnight; it 404s
  automatically after that window. No login is required to view it.
  **This means `SECRET_KEY` must be a stable, explicitly configured value**
  in production — if left to the framework's per-process random default,
  every app restart invalidates all outstanding report links.
- The WhatsApp message is a short summary (counts only) plus the one
  share link, rather than the full report inline — the full report
  (with photos) only loads when the link is opened, and it correctly uses
  the app's configured `SHARE_BASE_URL` rather than whatever host happens
  to be serving the page.

## 19. Loyalty Program In Depth

### Tier Thresholds (`services/loyalty.py`)
| Tier | Cumulative spend in current cycle |
|---|---|
| Silver | ₹10,000 |
| Gold | ₹20,000 |
| Platinum | ₹30,000 |
| Diamond | ₹50,000 |

Not a points system — pure "cumulative rupee spend within the current
1-year cycle unlocks a one-time gift per tier per cycle."

### Cycles
- A cycle runs exactly 1 year (leap-year safe) from an admin-set
  `activation_date` — **independent of the Apr–Mar financial year** used
  everywhere else in the app. This is a deliberate design choice.
- `get_current_cycle` lazily rolls forward, chaining through multiple
  elapsed cycles if the shop/app was inactive past several boundaries;
  each new cycle row is created on demand and is immutable once created.
- Changing the activation date only affects the *next* cycle — a
  `ValueError` blocks any change that would overlap or rewrite an
  already-started/ended cycle (prevents double-counting spend or
  double-unlocking gifts).

### Spend Calculation
`get_cycle_spent`: `SUM(final_total)` from `bills` where `customer_id`
matches, `status != 'cancelled'`, and `bill_date` falls within
`[cycle.start_date, cycle.end_date)`. Only retail bills count —
institution bills have no `customer_id` to link, and tailoring is a
separate database entirely.

### Gift Unlocking
`check_and_unlock_gifts(db, customer_id, bill_id)` runs in
`routes/bills.py` **after** a bill create/update is committed, in its own
follow-up transaction — a loyalty failure is logged and rolled back but
never fails the underlying bill save. It unlocks every newly-crossed tier
at once (e.g., one large bill can unlock Silver, Gold, and Platinum
simultaneously). The bill-creation response includes
`loyalty_unlocked: [...]`, which the frontend uses to show the milestone
banner.

### Access
Every loyalty API route, and the `/loyalty` and `/customers/<id>` pages
that surface loyalty data, are **admin-only** — there is no staff-level
loyalty visibility anywhere in the app.

## 20. Institution Billing In Depth

### Item Total Formula (`services/billing.py: calculate_inst_items`)
```
total = (quantity_per_pc × rate_per_m × no_of_pcs) + (no_of_pcs × stitching_per_unit)
```

### Key Technical Facts
- **No `customer_id`, no link to the `customers` table** — the
  "customer" is free-text company/contact fields only. Institution
  customers never appear in customer search, loyalty, or the regular
  Customers page.
- **No `inventory_item_id` on `institution_bill_items`, and no stock
  deduction anywhere in `routes/institution_bills.py`** — confirmed by
  code inspection. Institution billing is a pure financial record,
  entirely decoupled from the Inventory subsystem.
- **Own numbering sequence** (`inst_bill_number_seq`), format
  `INST-0001/26-27`, resets each financial year exactly like the retail
  sequence but tracked completely independently.
- Deleting an institution bill renumbers every subsequent bill in the
  same financial year (identical pattern to retail bill deletion).
- `status` field guards state: cannot edit or record a payment on a
  `cancelled` bill; cannot `restore` a non-cancelled one; `restore` and
  hard `delete` are admin-only, while create/edit/cancel/record-payment
  are available to any logged-in staff member.
- Two print formats generated from the same bill: a standard Invoice and
  a Performa Invoice.

## 21. Frontend Architecture

### JavaScript Modules

| File | Responsibility |
|---|---|
| `common.js` | Shared helpers loaded on every page: `escapeHtml`, the global date-input year-length fix, loyalty tier CSS/label maps |
| `bill-state.js` | Shared state, constants & utilities (fmt, round2, debounce, normalizeMobile) |
| `bill-items.js` | Item rows, cloth types, inventory links |
| `bill-payments.js` | Payment tabs, combo split, summary totals |
| `bill-modals.js` | Add cloth type / company / salesperson modals |
| `bill-qr.js` | QR / barcode scanner logic |
| `bill-share.js` | WhatsApp message builder & share-link helpers |
| `bill-form.js` | Retail bill form init, validation, save, mobile search, loyalty milestone banner |
| `dashboard.js` | Chart.js charts, summary cards, analytics period switching |
| `inventory.js` | Section-grouped list, add/edit/restock modals, QR generation, AI invoice scan review flow |
| `customers.js` | Customer list search/display, loyalty status card |
| `loyalty.js` | Loyalty settings page: toggle, activation date, pending gifts |
| `tailoring.js` | The entire tailoring UI: dashboard tab, orders tab, customers tab, order/detail modals, photo capture + preview-confirm, payment history, report link |
| `history.js` | Bill history search, export trigger |

### Responsive Bill Form
`bill-form.js` renders items in two layouts simultaneously — a `<table>`
on desktop (≥768px), a card stack on mobile (<768px) — both kept in sync
against the same underlying `itemDataStore`.

### Dropdown Caching
Company lists are cached in memory on the bill form per cloth type
(`companyCache` map); repeated selects of the same cloth type don't re-fetch.

### Inline Add for Dropdowns
On "Add Inventory Item" and "Current Stock QR" modals, selecting
`+ Add new…` reveals an inline text input + Add/Cancel; on save, the API
is called, the dropdown refreshes, and the new option is pre-selected.

### Modal Stacking
Modals opened from within another modal (e.g., the Edit Order dialog or
the photo-save confirmation, both launched from inside the Tailoring
order-detail modal) are given a higher `z-index` (210 vs. the default
200) via a page-local CSS override, so they never render hidden behind
their parent modal.

## 22. Security

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
| Tailor report links | HMAC-signed, date-scoped tokens (~2-day validity), no separate secret store |
| Photo access | Random UUID-based filenames — not enumerable |
| AI scanning safety | Model output is never written to the database automatically; a human must review and confirm every item |

## 23. Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | `'dev-only-change-in-production'` | Flask session signing key **and** the key behind tailor report share tokens — must be a stable explicit value in production |
| `SHARE_BASE_URL` | `'https://shubhamnxtailoring.pythonanywhere.com'` | Base URL for WhatsApp bill/tailor-report share links |
| `ANTHROPIC_API_KEY` | unset | Required only for AI invoice scanning; everything else works without it |
| `R2_ACCOUNT_ID` | unset | Cloudflare account ID for R2 photo storage (optional) |
| `R2_ACCESS_KEY_ID` | unset | R2 API token access key (optional) |
| `R2_SECRET_ACCESS_KEY` | unset | R2 API token secret (optional) |
| `R2_BUCKET_NAME` | unset | R2 bucket that holds tailoring photos (optional) |
| `R2_PUBLIC_URL` | unset | Public URL of that bucket, e.g. `https://pub-xxxx.r2.dev` (optional) |

Generate a strong secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Cloudflare R2 photo storage (optional)
Tailoring photos are saved to local disk by default. To offload new
uploads to Cloudflare R2 instead (free up to 10 GB, keeping the server's
own disk quota for the app and databases), set all five `R2_*` variables
and restart the app. Leave them blank to keep local-disk behavior
unchanged.

Setup, in the [Cloudflare dashboard](https://dash.cloudflare.com/):
1. **R2 → Create bucket** — name it (e.g. `tailoring-photos`). This is `R2_BUCKET_NAME`.
2. Open the bucket → **Settings → Public Access** → enable the `r2.dev`
   subdomain (or connect a custom domain). Copy that URL as `R2_PUBLIC_URL`.
3. **R2 → Manage API Tokens → Create API Token**, with **Object Read & Write**
   permission scoped to that bucket. Copy the Access Key ID, Secret Access
   Key, and the Account ID shown on the R2 overview page.
4. Cloudflare requires a payment method on file to activate R2, but you
   are not charged while staying under the free tier (10 GB storage,
   1M writes/month, 10M reads/month, $0 egress).

Photos already on local disk keep working after this is turned on — only
new uploads go to R2. Deleting a photo removes it from wherever it's
actually stored.

## 24. Deployment (PythonAnywhere)

- Deployed by pulling from GitHub directly on the PythonAnywhere server
  (`git pull`), then reloading the web app from the **Web** tab.
- `.env` (not `.env.example`) holds the real secrets on the server and is
  git-ignored — it is never committed. `.env.example` is only the
  checked-in template with blank placeholders.
- After pulling code that adds a new dependency (e.g., `boto3` for R2),
  run `pip install -r requirements.txt` inside the app's virtualenv before
  reloading, or the app will fail to start with an `ImportError`.
- PythonAnywhere's **free tier restricts outbound internet access** to a
  whitelist of approved domains — `r2.cloudflarestorage.com` is on that
  whitelist, so Cloudflare R2 works from a free PythonAnywhere account
  without upgrading.
- Free-tier disk quota is 512 MB — a key reason Cloudflare R2 photo
  offload exists as an option.

## 25. Default Credentials

> **Change these immediately after first login.**

| Username | Password | Role |
|---|---|---|
| `admin` | `Admin@1234` | Admin |
| `staff` | `Staff@1234` | Staff |

Passwords can be changed from `/profile` (own password) or
`/admin/users` (admin resets any user).
