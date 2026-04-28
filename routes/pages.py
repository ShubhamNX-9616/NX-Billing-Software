from flask import Blueprint, render_template
from auth import login_required, admin_required, staff_or_admin_required
from services.billing import get_bill_by_number

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/")
@admin_required
def dashboard():
    return render_template("dashboard.html")


@pages_bp.route("/new-bill")
@staff_or_admin_required
def new_bill():
    return render_template("new_bill.html")


@pages_bp.route("/bill-history")
@admin_required
def bill_history():
    return render_template("bill_history.html")


@pages_bp.route("/bills/<int:bill_id>")
@admin_required
def bill_detail(bill_id):
    return render_template("bill_detail.html", bill_id=bill_id)


@pages_bp.route("/edit-bill/<int:bill_id>")
@admin_required
def edit_bill(bill_id):
    return render_template("edit_bill.html", bill_id=bill_id)


@pages_bp.route("/customers")
@admin_required
def customers():
    return render_template("customers.html")


@pages_bp.route("/customers/<int:customer_id>")
@admin_required
def customer_detail(customer_id):
    return render_template("customer_detail.html", customer_id=customer_id)


@pages_bp.route("/admin/users")
@admin_required
def admin_users():
    return render_template("admin_users.html")


@pages_bp.route("/profile")
@login_required
def profile():
    return render_template("profile.html")


@pages_bp.route("/bill/share/<bill_number>")
def shared_bill(bill_number):
    data = get_bill_by_number(bill_number)
    if not data:
        return render_template("shared_bill_not_found.html", bill_number=bill_number), 404
    return render_template(
        "shared_bill.html",
        bill=data["bill"],
        items=data["items"],
        payments=data["payments"],
    )
