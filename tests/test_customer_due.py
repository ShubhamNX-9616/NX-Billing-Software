"""The customer summary on the billing screen also shows the customer's previous due.

Total spent and last bill were already shown when an existing customer is picked; the
unpaid balance on their earlier bills is now shown with them (total_due / due_bills).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

from test_money import client  # noqa: E402,F401  (temp-DB app with bills + customers routes)


def _bill(c, amount, paid=0, mobile="9876543210", name="Ravi"):
    body = {"customer_name": name, "customer_mobile": mobile, "bill_date": "2026-11-10",
            "salesperson_name": "Self", "payment_mode_type": "Cash", "advance_paid": paid,
            "items": [{"cloth_type": "Accessories", "company_name": "X", "quantity": 1, "mrp": amount}]}
    if paid:
        body["payments"] = [{"payment_method": "Cash", "amount": paid}]
    r = c.post("/api/bills", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _summary(c, mobile="9876543210", **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    r = c.get(f"/api/customers/summary?mobile={mobile}" + (f"&{qs}" if qs else ""))
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def test_customer_with_no_bills_has_no_due(client):  # noqa: F811
    got = _summary(client)
    assert got["total_bills"] == 0 and got["total_due"] == 0 and got["due_bills"] == 0


def test_fully_paid_bills_leave_no_due(client):  # noqa: F811
    _bill(client, 1000, paid=1000)
    got = _summary(client)
    assert got["total_bills"] == 1 and got["total_spent"] == 1000
    assert got["total_due"] == 0 and got["due_bills"] == 0


def test_due_is_the_sum_of_the_balances_on_earlier_bills(client):  # noqa: F811
    _bill(client, 1000, paid=1000)           # settled
    _bill(client, 500, paid=200)             # 300 due
    _bill(client, 700)                       # 700 due
    got = _summary(client)
    assert got["total_due"] == 1000 and got["due_bills"] == 2
    assert got["total_spent"] == 2200 and got["total_bills"] == 3      # the existing figures are unchanged
    assert got["last_bill_amount"] == 700


def test_a_cancelled_bill_is_not_a_due_and_coming_back_counts_again(client):  # noqa: F811
    keep = _bill(client, 400)
    gone = _bill(client, 600)
    assert _summary(client)["total_due"] == 1000
    assert client.put(f"/api/bills/{gone['id']}/cancel").status_code == 200
    got = _summary(client)
    assert got["total_due"] == 400 and got["due_bills"] == 1
    assert client.put(f"/api/bills/{gone['id']}/restore").status_code == 200
    assert _summary(client)["total_due"] == 1000
    assert keep["id"] != gone["id"]


def test_paying_off_a_balance_reduces_the_due(client):  # noqa: F811
    bill = _bill(client, 800, paid=300)
    assert _summary(client)["total_due"] == 500
    r = client.post(f"/api/bills/{bill['id']}/record-payment", json={"payment_method": "Cash", "amount": 200})
    assert r.status_code == 200
    assert _summary(client)["total_due"] == 300
    client.post(f"/api/bills/{bill['id']}/record-payment", json={"payment_method": "Cash", "amount": 300})
    got = _summary(client)
    assert got["total_due"] == 0 and got["due_bills"] == 0


def test_editing_a_bill_does_not_count_its_own_balance_as_previous_due(client):  # noqa: F811
    older = _bill(client, 500, paid=200)      # 300 due
    editing = _bill(client, 700)              # 700 due - the bill being edited
    assert _summary(client)["total_due"] == 1000
    got = _summary(client, exclude_bill_id=editing["id"])
    assert got["total_due"] == 300 and got["due_bills"] == 1
    assert got["total_spent"] == 1200 and got["total_bills"] == 2       # totals still include it, as before
    assert _summary(client, exclude_bill_id=older["id"])["total_due"] == 700
    assert _summary(client, exclude_bill_id=99999)["total_due"] == 1000  # unknown id: nothing excluded
    assert _summary(client, exclude_bill_id="abc")["total_due"] == 1000  # garbage is ignored


def test_one_customers_due_is_not_another_customers(client):  # noqa: F811
    _bill(client, 900, mobile="9876543210", name="Ravi")
    _bill(client, 250, mobile="9123456789", name="Sunil")
    assert _summary(client, "9876543210")["total_due"] == 900
    assert _summary(client, "9123456789")["total_due"] == 250


def test_the_mobile_can_be_typed_in_any_usual_form(client):  # noqa: F811
    _bill(client, 600)
    for typed in ("9876543210", "+919876543210", "09876543210", "98765 43210"):
        assert _summary(client, mobile=typed.replace("+", "%2B").replace(" ", "%20"))["total_due"] == 600, typed


def test_due_is_an_exact_paise_figure_not_float_noise(client):  # noqa: F811
    for _ in range(3):
        _bill(client, 33.33)
    assert _summary(client)["total_due"] == 99.99


def test_the_screen_shows_previous_due_and_edit_mode_excludes_its_own_bill():
    js = open(os.path.join(PROJECT_ROOT, "static", "js", "bill-form.js"), encoding="utf-8-sig").read()
    assert "Previous Due" in js and "data.total_due" in js and "data.due_bills" in js
    assert "exclude_bill_id" in js and "EDIT_MODE" in js
