"""
Populate the database with 2 sample bills for development/testing.

Run once after starting the app for the first time (from the project root):
    python scripts/test_data.py

Do NOT run this multiple times — it will create duplicate customers.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db import init_db, get_db, generate_bill_number

# ----------------------------------------------------------------
# Sample data
# ----------------------------------------------------------------
SAMPLE_BILLS = [
    {
        "customer_name":     "Rajesh Patil",
        "customer_mobile":   "9876543210",
        "bill_date":         "2026-04-05",
        "payment_mode_type": "Cash",
        "items": [
            {
                "cloth_type":       "Shirting",
                "company_name":     "Raymonds",
                "quality_number":   "RM-42",
                "quantity":         3.5,
                "unit_label":       "m",
                "mrp":              350.00,
                "discount_percent": 10.0,
            },
            {
                "cloth_type":       "Suiting",
                "company_name":     "Raymond",
                "quality_number":   None,
                "quantity":         2.0,
                "unit_label":       "m",
                "mrp":              650.00,
                "discount_percent": 5.0,
            },
        ],
        "payments": [
            {"payment_method": "Cash", "amount": None},  # auto-filled to final_total
        ],
    },
    {
        "customer_name":     "Sunita Sharma",
        "customer_mobile":   "9123456780",
        "bill_date":         "2026-04-07",
        "payment_mode_type": "Combination",
        "items": [
            {
                "cloth_type":       "Readymade",
                "company_name":     "Shubh",
                "quality_number":   None,
                "quantity":         2,
                "unit_label":       "pcs",
                "mrp":              899.00,
                "discount_percent": 0.0,
            },
            {
                "cloth_type":       "Shirting",
                "company_name":     "Arvind",
                "quality_number":   "AV-07",
                "quantity":         4.0,
                "unit_label":       "m",
                "mrp":              280.00,
                "discount_percent": 8.0,
            },
        ],
        "payments": [
            {"payment_method": "Cash", "amount": 1000.0},
            {"payment_method": "UPI",  "amount": None},  # auto-filled to remainder
        ],
    },
]


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------
def round2(n):
    return round(n + 1e-10, 2)


def calc_item(item):
    line_total      = round2(item["quantity"] * item["mrp"])
    discount_amount = round2(line_total * item["discount_percent"] / 100)
    final_amount    = round2(line_total - discount_amount)
    return {**item, "line_total": line_total,
            "discount_amount": discount_amount, "final_amount": final_amount}


def resolve_payments(payments, final_total):
    """Fill in the one None amount as the remainder."""
    fixed_sum = sum(p["amount"] for p in payments if p["amount"] is not None)
    result = []
    none_seen = False
    for p in payments:
        if p["amount"] is None:
            if none_seen:
                raise ValueError("Only one payment amount can be auto-filled (None).")
            result.append({"payment_method": p["payment_method"],
                            "amount": round2(final_total - fixed_sum)})
            none_seen = True
        else:
            result.append(p)
    return result


# ----------------------------------------------------------------
# Insert
# ----------------------------------------------------------------
def insert_bill(db, bill_data):
    customer_name   = bill_data["customer_name"]
    customer_mobile = bill_data["customer_mobile"]
    bill_date       = bill_data["bill_date"]
    mode            = bill_data["payment_mode_type"]

    calc_items     = [calc_item(i) for i in bill_data["items"]]
    subtotal       = round2(sum(i["line_total"]      for i in calc_items))
    total_discount = round2(sum(i["discount_amount"] for i in calc_items))
    final_total    = round2(sum(i["final_amount"]    for i in calc_items))
    total_savings  = total_discount

    payments = resolve_payments(bill_data["payments"], final_total)

    row = db.execute(
        "SELECT id FROM customers WHERE normalized_mobile = ?", (customer_mobile,)
    ).fetchone()
    if row:
        customer_id = row["id"]
    else:
        cur = db.execute(
            "INSERT INTO customers (name, mobile, normalized_mobile) VALUES (?, ?, ?)",
            (customer_name, customer_mobile, customer_mobile),
        )
        customer_id = cur.lastrowid

    bill_number = generate_bill_number(db)

    bill_cur = db.execute(
        """
        INSERT INTO bills (
            bill_number, customer_id,
            customer_name_snapshot, customer_mobile_snapshot,
            bill_date, subtotal, total_discount, final_total,
            total_savings, payment_mode_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (bill_number, customer_id, customer_name, customer_mobile,
         bill_date, subtotal, total_discount, final_total, total_savings, mode),
    )
    bill_id = bill_cur.lastrowid

    db.executemany(
        """
        INSERT INTO bill_items (
            bill_id, cloth_type, company_name, quality_number,
            quantity, unit_label, mrp, line_total,
            discount_percent, discount_amount, final_amount
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(bill_id, i["cloth_type"], i["company_name"], i["quality_number"],
          i["quantity"], i["unit_label"], i["mrp"], i["line_total"],
          i["discount_percent"], i["discount_amount"], i["final_amount"])
         for i in calc_items],
    )

    db.executemany(
        "INSERT INTO bill_payments (bill_id, payment_method, amount) VALUES (?, ?, ?)",
        [(bill_id, p["payment_method"], p["amount"]) for p in payments],
    )

    db.commit()
    return bill_number, final_total


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
if __name__ == "__main__":
    print("Initialising database...")
    init_db()

    db = get_db()
    print()

    for i, bill in enumerate(SAMPLE_BILLS, 1):
        try:
            bill_number, total = insert_bill(db, bill)
            print(f"  [{i}] Created {bill_number}  |  Customer: {bill['customer_name']}"
                  f"  |  Total: Rs.{total:,.2f}")
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            print(f"  [{i}] FAILED - {e}")

    print()
    print("Done. Open http://localhost:8081 to see the sample data.")
    print("(Make sure app.py is running first.)")
