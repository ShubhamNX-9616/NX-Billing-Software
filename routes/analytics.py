from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from db import get_db
from auth import api_admin_required

analytics_bp = Blueprint("analytics", __name__)


# ---------------------------------------------------------------------------
# GET /api/analytics/summary
# ---------------------------------------------------------------------------
@analytics_bp.route("/analytics/summary", methods=["GET"])
@api_admin_required
def analytics_summary():
    try:
        db = get_db()
        now = datetime.now()
        today_str  = now.strftime("%Y-%m-%d")
        this_month = now.strftime("%Y-%m")
        this_year  = now.strftime("%Y")

        overall = db.execute("""
            SELECT
                COUNT(DISTINCT b.id)                                                     AS total_bills,
                COALESCE(SUM(b.final_total), 0)                                          AS total_sales,
                COUNT(DISTINCT b.customer_id)                                            AS total_customers,
                COALESCE(SUM(cp.cash), 0)                                                AS total_cash,
                COALESCE(SUM(cp.card), 0)                                                AS total_card,
                COALESCE(SUM(cp.upi), 0)                                                 AS total_upi,
                COALESCE(SUM(CASE WHEN b.payment_mode_type='Combination'
                                  THEN b.final_total ELSE 0 END), 0)                     AS total_combination
            FROM bills b
            LEFT JOIN (
                SELECT bill_id,
                    SUM(CASE WHEN payment_method='Cash' THEN amount ELSE 0 END) AS cash,
                    SUM(CASE WHEN payment_method='Card' THEN amount ELSE 0 END) AS card,
                    SUM(CASE WHEN payment_method='UPI'  THEN amount ELSE 0 END) AS upi
                FROM bill_payments GROUP BY bill_id
            ) cp ON cp.bill_id = b.id
            WHERE b.status != 'cancelled'
        """).fetchone()

        today_row = db.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(final_total),0) AS sales "
            "FROM bills WHERE status != 'cancelled' AND bill_date = ?",
            (today_str,)
        ).fetchone()

        month_row = db.execute(
            "SELECT COALESCE(SUM(final_total),0) AS sales "
            "FROM bills WHERE status != 'cancelled' AND strftime('%Y-%m', bill_date) = ?",
            (this_month,)
        ).fetchone()

        year_row = db.execute(
            "SELECT COALESCE(SUM(final_total),0) AS sales "
            "FROM bills WHERE status != 'cancelled' AND strftime('%Y', bill_date) = ?",
            (this_year,)
        ).fetchone()

        return jsonify({
            "total_bills":       int(overall["total_bills"] or 0),
            "total_sales":       round(float(overall["total_sales"] or 0), 2),
            "total_customers":   int(overall["total_customers"] or 0),
            "total_cash":        round(float(overall["total_cash"] or 0), 2),
            "total_card":        round(float(overall["total_card"] or 0), 2),
            "total_upi":         round(float(overall["total_upi"] or 0), 2),
            "total_combination": round(float(overall["total_combination"] or 0), 2),
            "today_bills":       int(today_row["cnt"] or 0),
            "today_sales":       round(float(today_row["sales"] or 0), 2),
            "this_month_sales":  round(float(month_row["sales"] or 0), 2),
            "this_year_sales":   round(float(year_row["sales"] or 0), 2),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /api/analytics?period=daily|monthly|yearly|custom
# ---------------------------------------------------------------------------
@analytics_bp.route("/analytics", methods=["GET"])
@api_admin_required
def get_analytics():
    try:
        period = request.args.get("period", "monthly")
        db     = get_db()
        today  = datetime.now().date()

        if period == "daily":
            buckets = [
                (today - timedelta(days=i)).strftime("%Y-%m-%d")
                for i in range(29, -1, -1)
            ]
            date_filter = f"b.bill_date >= '{buckets[0]}'"
            group_expr  = "strftime('%Y-%m-%d', b.bill_date)"

        elif period == "yearly":
            buckets = [str(today.year - i) for i in range(4, -1, -1)]
            date_filter = f"strftime('%Y', b.bill_date) >= '{buckets[0]}'"
            group_expr  = "strftime('%Y', b.bill_date)"

        elif period == "custom":
            from_date = (request.args.get("from") or "").strip()
            to_date   = (request.args.get("to")   or "").strip()
            if not from_date or not to_date:
                return jsonify({"error": "from and to query params are required"}), 400
            try:
                start = datetime.strptime(from_date, "%Y-%m-%d").date()
                end   = datetime.strptime(to_date,   "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"error": "Dates must be in YYYY-MM-DD format"}), 400
            if start > end:
                return jsonify({"error": "from date cannot be after to date"}), 400
            if (end - start).days > 366:
                return jsonify({"error": "Custom date range cannot exceed 366 days"}), 400
            buckets = [
                (start + timedelta(days=i)).strftime("%Y-%m-%d")
                for i in range((end - start).days + 1)
            ]
            date_filter = "b.bill_date BETWEEN ? AND ?"
            group_expr  = "strftime('%Y-%m-%d', b.bill_date)"

        else:  # monthly (default)
            buckets = []
            for i in range(11, -1, -1):
                total_m = today.year * 12 + (today.month - 1) - i
                b_year  = total_m // 12
                b_month = (total_m % 12) + 1
                buckets.append(f"{b_year:04d}-{b_month:02d}")
            date_filter = f"strftime('%Y-%m', b.bill_date) >= '{buckets[0]}'"
            group_expr  = "strftime('%Y-%m', b.bill_date)"

        params = (from_date, to_date) if period == "custom" else ()
        rows = db.execute(f"""
            SELECT
                {group_expr}                                                              AS bucket,
                SUM(b.final_total)                                                        AS total_sales,
                COUNT(b.id)                                                               AS bill_count,
                COALESCE(SUM(cp.cash), 0)                                                AS cash,
                COALESCE(SUM(cp.card), 0)                                                AS card,
                COALESCE(SUM(cp.upi), 0)                                                 AS upi,
                COALESCE(SUM(CASE WHEN b.payment_mode_type='Combination'
                                  THEN b.final_total ELSE 0 END), 0)                     AS combination
            FROM bills b
            LEFT JOIN (
                SELECT bill_id,
                    SUM(CASE WHEN payment_method='Cash' THEN amount ELSE 0 END) AS cash,
                    SUM(CASE WHEN payment_method='Card' THEN amount ELSE 0 END) AS card,
                    SUM(CASE WHEN payment_method='UPI'  THEN amount ELSE 0 END) AS upi
                FROM bill_payments GROUP BY bill_id
            ) cp ON cp.bill_id = b.id
            WHERE b.status != 'cancelled'
              AND {date_filter}
            GROUP BY bucket
            ORDER BY bucket ASC
        """, params).fetchall()

        data_map = {r["bucket"]: dict(r) for r in rows}
        result = []
        for bucket in buckets:
            row = data_map.get(bucket, {})
            if period == "daily":
                label = datetime.strptime(bucket, "%Y-%m-%d").strftime("%d %b")
            elif period == "monthly":
                label = datetime.strptime(bucket + "-01", "%Y-%m-%d").strftime("%b %Y")
            else:
                label = bucket
            result.append({
                "label":       label,
                "bucket":      bucket,
                "total_sales": round(float(row.get("total_sales") or 0), 2),
                "cash":        round(float(row.get("cash") or 0), 2),
                "card":        round(float(row.get("card") or 0), 2),
                "upi":         round(float(row.get("upi") or 0), 2),
                "combination": round(float(row.get("combination") or 0), 2),
                "bill_count":  int(row.get("bill_count") or 0),
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /api/analytics/salespersons
# ---------------------------------------------------------------------------
@analytics_bp.route("/analytics/salespersons", methods=["GET"])
@api_admin_required
def analytics_salespersons():
    try:
        period = request.args.get("period", "monthly")
        db     = get_db()
        today  = datetime.now().date()

        if period == "daily":
            start_date = (today - timedelta(days=29)).strftime("%Y-%m-%d")
            end_date   = today.strftime("%Y-%m-%d")
            where_sql  = "b.bill_date BETWEEN ? AND ?"
            params     = (start_date, end_date)
        elif period == "yearly":
            start_date = f"{today.year - 4:04d}-01-01"
            end_date   = today.strftime("%Y-%m-%d")
            where_sql  = "b.bill_date BETWEEN ? AND ?"
            params     = (start_date, end_date)
        elif period == "custom":
            from_date = (request.args.get("from") or "").strip()
            to_date   = (request.args.get("to")   or "").strip()
            if not from_date or not to_date:
                return jsonify({"error": "from and to query params are required"}), 400
            try:
                start = datetime.strptime(from_date, "%Y-%m-%d").date()
                end   = datetime.strptime(to_date,   "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"error": "Dates must be in YYYY-MM-DD format"}), 400
            if start > end:
                return jsonify({"error": "from date cannot be after to date"}), 400
            if (end - start).days > 366:
                return jsonify({"error": "Custom date range cannot exceed 366 days"}), 400
            where_sql = "b.bill_date BETWEEN ? AND ?"
            params    = (from_date, to_date)
        else:  # monthly
            start_month = f"{today.year:04d}-{today.month:02d}"
            total_m     = today.year * 12 + (today.month - 1) - 11
            start_year  = total_m // 12
            start_mon   = (total_m % 12) + 1
            where_sql   = "strftime('%Y-%m', b.bill_date) BETWEEN ? AND ?"
            params      = (f"{start_year:04d}-{start_mon:02d}", start_month)

        rows = db.execute(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(b.salesperson_name), ''), 'Unassigned') AS salesperson_name,
                COUNT(*) AS bill_count,
                COALESCE(SUM(b.final_total), 0) AS total_sales
            FROM bills b
            WHERE b.status != 'cancelled'
              AND {where_sql}
            GROUP BY COALESCE(NULLIF(TRIM(b.salesperson_name), ''), 'Unassigned')
            ORDER BY total_sales DESC, salesperson_name ASC
            """,
            params,
        ).fetchall()
        return jsonify([
            {
                "salesperson_name": row["salesperson_name"],
                "bill_count":       int(row["bill_count"] or 0),
                "total_sales":      round(float(row["total_sales"] or 0), 2),
            }
            for row in rows
        ])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
