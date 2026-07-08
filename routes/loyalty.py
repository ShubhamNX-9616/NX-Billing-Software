from flask import Blueprint, jsonify, request, session
from db import get_db
from services.auth import api_admin_required
from services.loyalty import (
    TIERS, get_tier_for_amount,
    is_loyalty_enabled, set_loyalty_enabled,
    get_activation_date, set_activation_date, get_current_cycle,
    get_cycle_spent,
)

loyalty_bp = Blueprint("loyalty", __name__)


def _cycle_info(cycle):
    if cycle is None:
        return None
    return {
        "cycle_number": cycle["cycle_number"],
        "start_date":   cycle["start_date"],
        "end_date":     cycle["end_date"],
    }


@loyalty_bp.route("/loyalty/settings", methods=["GET"])
@api_admin_required
def get_loyalty_settings():
    db = get_db()
    cycle = get_current_cycle(db)
    db.commit()
    return jsonify({
        "enabled":         is_loyalty_enabled(db),
        "activation_date": get_activation_date(db),
        "current_cycle":   _cycle_info(cycle),
    })


@loyalty_bp.route("/loyalty/settings/toggle", methods=["POST"])
@api_admin_required
def toggle_loyalty_settings():
    db = get_db()
    new_enabled = not is_loyalty_enabled(db)
    set_loyalty_enabled(db, new_enabled)
    db.commit()
    return jsonify({"enabled": new_enabled})


@loyalty_bp.route("/loyalty/settings/activation-date", methods=["POST"])
@api_admin_required
def update_activation_date():
    data = request.get_json(silent=True) or {}
    activation_date = data.get("activation_date")
    if not activation_date:
        return jsonify({"error": "activation_date is required"}), 400

    db = get_db()
    try:
        set_activation_date(db, activation_date)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    db.commit()

    return jsonify({
        "activation_date": get_activation_date(db),
        "current_cycle":   _cycle_info(get_current_cycle(db)),
    })


@loyalty_bp.route("/loyalty/pending-gifts", methods=["GET"])
@api_admin_required
def get_pending_gifts():
    db = get_db()
    rows = db.execute(
        """
        SELECT lg.id, lg.tier, lg.created_at, lg.bill_id,
               c.id AS customer_id, c.name AS customer_name, c.mobile AS customer_mobile
        FROM loyalty_gifts lg
        JOIN customers c ON c.id = lg.customer_id
        WHERE lg.given_at IS NULL
        ORDER BY lg.created_at DESC
        """
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@loyalty_bp.route("/loyalty/gifts/<int:gift_id>/mark-given", methods=["POST"])
@api_admin_required
def mark_gift_given(gift_id):
    db = get_db()
    gift = db.execute(
        "SELECT id, given_at FROM loyalty_gifts WHERE id = ?", (gift_id,)
    ).fetchone()
    if not gift:
        return jsonify({"error": "Gift record not found"}), 404
    if gift["given_at"]:
        return jsonify({"error": "Gift already marked as given"}), 400

    db.execute(
        "UPDATE loyalty_gifts SET given_at = datetime('now','localtime'), given_by = ? WHERE id = ?",
        (session.get("username"), gift_id),
    )
    db.commit()
    return jsonify({"success": True}), 200


@loyalty_bp.route("/loyalty/customer/<int:customer_id>", methods=["GET"])
@api_admin_required
def get_customer_loyalty(customer_id):
    db = get_db()

    customer = db.execute("SELECT id FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not customer:
        return jsonify({"error": "Customer not found"}), 404

    cycle = get_current_cycle(db)
    db.commit()

    if cycle is None:
        return jsonify({
            "started":        False,
            "current_cycle":  None,
            "cycle_spent":    0,
            "current_tier":   None,
            "next_tier":      TIERS[0][0],
            "next_threshold": TIERS[0][1],
            "amount_to_next": TIERS[0][1],
            "gifts":          [],
        })

    spent = get_cycle_spent(db, customer_id, cycle)
    current_tier = get_tier_for_amount(spent)

    next_tier = None
    next_threshold = None
    for name, threshold in TIERS:
        if spent < threshold:
            next_tier = name
            next_threshold = threshold
            break

    gifts = db.execute(
        """
        SELECT id, tier, given_at, given_by, bill_id, created_at
        FROM loyalty_gifts
        WHERE customer_id = ? AND cycle_id = ?
        ORDER BY created_at
        """,
        (customer_id, cycle["id"]),
    ).fetchall()

    return jsonify({
        "started":        True,
        "current_cycle":  _cycle_info(cycle),
        "cycle_spent":    round(spent, 2),
        "current_tier":   current_tier,
        "next_tier":      next_tier,
        "next_threshold": next_threshold,
        "amount_to_next": round(next_threshold - spent, 2) if next_threshold else 0,
        "gifts":          [dict(g) for g in gifts],
    })
