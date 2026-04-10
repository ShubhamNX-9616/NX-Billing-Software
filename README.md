# SHUBHAM NX — Billing App

## What is this app?

This is a billing and invoice management app for **SHUBHAM NX**, a cloth shop located at Krishna Chowk, New Sangvi, Pune.

It lets you:
- Create professional bills for customers (Shirting, Suiting, Readymade)
- Auto-search existing customers by mobile number
- Apply discounts per item and calculate totals automatically
- Accept payments by Cash, Card, UPI, or a combination
- Print or save invoices as PDF directly from the browser
- View full bill history with search by bill number, name, or mobile
- Track all customers and their purchase history

Everything runs locally on your computer. No internet required after setup.

---

## Requirements

- **Python 3.8 or higher** — that's it. No database setup, no Node.js, no extra tools.

**How to check if Python is installed:**
1. Press `Windows + R`, type `cmd`, press Enter
2. Type: `python --version`
3. If you see something like `Python 3.11.2` — you're good to go!

**If Python is not installed:**
1. Go to: https://www.python.org/downloads/
2. Click the big yellow "Download Python" button
3. Run the installer
4. **Important:** On the first screen, check the box that says **"Add Python to PATH"** before clicking Install
5. Click "Install Now" and wait for it to finish

---

## Setup — Step by Step

### Step 1: Get the project files

**If you have a ZIP file:**
1. Right-click the ZIP file
2. Click "Extract All"
3. Extract to your Desktop or `C:\Projects`

You should now have a folder called `shubham-nx-billing` with files inside it.

### Step 2: Open Command Prompt

**Option A:**
1. Press `Windows + R`
2. Type `cmd`
3. Press Enter

**Option B:**
1. Click the Start menu (Windows button)
2. Search for "Command Prompt"
3. Click to open it

### Step 3: Navigate to the project folder

In the Command Prompt window, type the following (adjust the path if your folder is somewhere else):

```
cd Desktop\shubham-nx-billing
```

If you extracted to `C:\Projects`, type:
```
cd C:\Projects\shubham-nx-billing
```

Press Enter. You should see the path change in the prompt.

### Step 4: Install Flask

Type this and press Enter:
```
pip install -r requirements.txt
```

Wait for it to download and finish. You'll see messages like `Successfully installed flask flask-bcrypt`.

> If you see `pip is not recognized`, see the Troubleshooting section below.

### Step 5: Start the app

Type this and press Enter:
```
python app.py
```

You should see output like:
```
 * Running on http://127.0.0.1:8081
 * Debug mode: on
```

**Do not close this Command Prompt window** — the app runs inside it.

### Step 6: Open in your browser

1. Open **Chrome** or **Edge**
2. In the address bar, type: `http://localhost:8081`
3. Press Enter

The SHUBHAM NX billing app will load. It's ready to use!

---

## Remote Access via Cloudflare Tunnel

### What is Cloudflare Tunnel?

- **Free** — no account, no signup required
- Gives a temporary public URL like `https://xyz.trycloudflare.com`
- Anyone with the URL can open the billing app on any device (phone, tablet, another laptop)
- The URL changes every time you restart — that is normal
- Your data stays on your laptop — Cloudflare only forwards the connection, nothing is stored

### Setup (one time only)

**Step 1:** Go to:
```
https://github.com/cloudflare/cloudflared/releases/latest
```

**Step 2:** Download the file named **`cloudflared-windows-amd64.exe`**

**Step 3:** Rename it to **`cloudflared.exe`**

**Step 4:** Place it inside the **`shubham-nx-billing`** folder (same folder as `app.py`)

That's it — no installation, no account, no configuration needed.

### Starting the app with remote access

1. Double-click **`start.bat`** (or run it from Command Prompt)
2. Two windows will open automatically:
   - **Flask Server window** — shows the local server running
   - **Cloudflare Tunnel window** — shows the public URL
3. In the Cloudflare window, look for a line like:
   ```
   https://abc-def-ghi-123.trycloudflare.com
   ```
4. Open that URL on your phone, tablet, or any device
5. Share it with anyone who needs access (shop staff, owner)

> The URL appears within 5–10 seconds of the Cloudflare window opening.

### Stopping the app

Double-click **`stop.bat`** — both the Flask server and the tunnel will stop cleanly.

### Important notes

- Keep **both** windows open while using the app — closing either stops that part
- The public URL is temporary — it changes every time you run `start.bat`
- For a permanent URL you would need a paid Cloudflare account (not needed for single-shop use)

### Security note

- Anyone with the URL can access your billing data
- **Do not** share the URL publicly (WhatsApp groups, social media, etc.)
- Only share with trusted people (shop staff, family)
- Run `stop.bat` when the app is not in use to close the tunnel

---

## Login & User Management

### Default credentials

The app creates two accounts automatically on first run:

| Role  | Username | Password    |
|-------|----------|-------------|
| Admin | `admin`  | `Admin@1234` |
| Staff | `staff`  | `Staff@1234` |

> **Change these passwords immediately after first login.** See instructions below.

---

### What each role can access

| Feature | Admin | Staff |
|---------|-------|-------|
| Dashboard (analytics, charts) | ✅ | ❌ |
| New Bill (create bills) | ✅ | ✅ |
| Bill History (view all bills) | ✅ | ❌ |
| Bill Detail & Edit | ✅ | ❌ |
| Customers list & history | ✅ | ❌ |
| Delete bills | ✅ | ❌ |
| User Management (`/admin/users`) | ✅ | ❌ |

Staff can only access the **New Bill** page — they can create bills, search customers by mobile, and use all dropdowns. They cannot view history, analytics, or customer data.

---

### How to change your own password

1. Log in with your account
2. In the sidebar footer (or topbar), click **My Profile**
3. Enter your current password and choose a new one
4. Click **Save Password**

---

### How to change another user's password (admin only)

1. Log in as admin
2. Go to **Users** in the sidebar (or `http://localhost:8081/admin/users`)
3. Find the user in the table
4. Click **Change Password** next to their name

---

### How to add a new staff account (admin only)

1. Log in as admin
2. Go to **Users** in the sidebar
3. Scroll to **Add New User**
4. Enter username, password, confirm password, and select role
5. Click **Add User**

---

### Security warnings

> ⚠️ **Change default passwords immediately** — `Admin@1234` and `Staff@1234` are public knowledge.

> ⚠️ **Set a strong `SECRET_KEY`** before deploying online. Generate one with:
> ```
> python -c "import secrets; print(secrets.token_hex(32))"
> ```
> Copy the output into a `.env` file (see `.env.example`) or set it as an environment variable.
> The default key (`dev-only-change-in-production`) must **never** be used in production.

> ⚠️ If you expose the app via Cloudflare Tunnel or deploy it online, the login page protects all data — but only if the default passwords have been changed and a strong `SECRET_KEY` is set.

---

## How to use

| Page | What it does |
|------|-------------|
| **Dashboard** | Shows total bills, customers, today's revenue, and recent bills |
| **New Bill** | Create a new bill — add items, apply discounts, record payment |
| **Bill History** | Search all past bills by bill number, customer name, or mobile |
| **Customers** | View all customers and their individual bill history |

### Creating a bill (quick guide):
1. Go to **New Bill**
2. Enter the customer's **mobile number** — if they've visited before, their name fills in automatically
3. Add items using the **+ Add Item** button
4. Select cloth type → company → enter quantity, MRP, and discount %
5. Choose payment method (Cash / Card / UPI / Combination)
6. Click **Save Bill**
7. Click **Print / Save PDF** to print the invoice

---

## Stopping the app

1. Go back to the Command Prompt window where the app is running
2. Press `Ctrl + C`
3. The app will stop

---

## Restarting the app

1. Open Command Prompt
2. Navigate to the project folder:
   ```
   cd Desktop\shubham-nx-billing
   ```
3. Run:
   ```
   python app.py
   ```
4. Open `http://localhost:8081` in your browser

---

## Your data

All your bills, customers, and data are saved in a file called **`billing.db`** inside the project folder. This file is created automatically the first time you run the app.

**To back up your data:** copy the `billing.db` file to a USB drive or Google Drive regularly.

---

## Troubleshooting

**"pip is not recognized" or "pip not found"**
- Python was not added to PATH during installation
- Uninstall Python, then reinstall it from https://www.python.org/downloads/
- On the first screen of the installer, check **"Add Python to PATH"**

**"Port 8081 is already in use"**
- Another program is using that port
- Open `app.py` in Notepad, find `port=8081`, change it to `port=8082`
- Then go to `http://localhost:8082` in your browser

**"ModuleNotFoundError: No module named 'flask'"**
- Flask was not installed, or installed for a different Python version
- Run: `pip install flask`
- If that doesn't work, try: `python -m pip install flask`

**The app opens but shows an error**
- Make sure you are running `python app.py` from inside the `shubham-nx-billing` folder
- The `billing.db` file is created automatically — do not delete it

**Bill numbers jumped or are wrong**
- This can happen if a bill was started but not saved
- Bill numbers are assigned only when a bill is successfully saved — gaps are normal

---

## Free deployment guide (run it online, accessible from anywhere)

If you want to access the app from your phone or another computer without keeping your PC on, you can deploy it for free.

### Deploy to Render.com (free)

1. Create a free account at https://github.com and upload your project folder
2. Create a free account at https://render.com
3. Click **New → Web Service** and connect your GitHub repository
4. Set the following:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `python app.py`
5. Click **Deploy** and wait a few minutes
6. Render gives you a URL like `https://shubham-nx-billing.onrender.com`

> **Note:** The free tier on Render spins down after 15 minutes of inactivity and takes ~30 seconds to wake up on the next visit. The SQLite database (`billing.db`) works fine on Render's free tier.

### Optional: Switch to a cloud database

If you want your data to survive redeployments on Render, migrate to a free cloud database:
1. Create a free PostgreSQL database at https://neon.tech
2. Update `database.py` to use the `psycopg2` library and the Neon connection string instead of SQLite
3. This is an advanced step — not needed for local use

---

*Built for SHUBHAM NX, Krishna Chowk, New Sangvi, Pune — 411061*
