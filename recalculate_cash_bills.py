import argparse
import calendar
from contextlib import closing

from database import get_db


def round2(value):
    return round(float(value) + 1e-10, 2)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Recalculate cash bills for a given month/year by reducing item MRP "
            "by a percentage and updating bill totals."
        )
    )
    parser.add_argument("--month", type=int, required=True, help="Month number, 1-12")
    parser.add_argument("--year", type=int, required=True, help="4-digit year")
    parser.add_argument(
        "--mrp-drop-percent",
        type=float,
        required=True,
        help="Percentage to reduce each bill item's MRP by",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply updates to the database. Without this flag, the script is a dry run.",
    )
    return parser.parse_args()


def validate_args(args):
    if not 1 <= args.month <= 12:
        raise ValueError("month must be between 1 and 12")
    if args.year < 2000 or args.year > 9999:
        raise ValueError("year must be a 4-digit value")
    if not 0 <= args.mrp_drop_percent <= 100:
        raise ValueError("mrp-drop-percent must be between 0 and 100")


def month_range(year, month):
    _, last_day = calendar.monthrange(year, month)
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


def fetch_target_bills(db, start_date, end_date):
    return db.execute(
        """
        SELECT id, bill_number, bill_date, subtotal, total_discount, final_total,
               total_savings, advance_paid, remaining, payment_mode_type, status
        FROM bills
        WHERE payment_mode_type = 'Cash'
          AND status != 'cancelled'
          AND bill_date BETWEEN ? AND ?
        ORDER BY bill_date, id
        """,
        (start_date, end_date),
    ).fetchall()


def current_cash_total(bills):
    return round2(sum(float(bill["final_total"] or 0) for bill in bills))


def fetch_bill_items(db, bill_id):
    return db.execute(
        """
        SELECT id, cloth_type, company_name, quality_number,
               quantity, unit_label, mrp, discount_percent
        FROM bill_items
        WHERE bill_id = ?
        ORDER BY id
        """,
        (bill_id,),
    ).fetchall()


def recalculate_item(item, mrp_drop_percent):
    original_mrp = float(item["mrp"])
    reduced_mrp = round2(original_mrp * (1 - (mrp_drop_percent / 100)))
    quantity = float(item["quantity"])
    discount_percent = float(item["discount_percent"] or 0)

    disc_per_unit = round2(reduced_mrp * discount_percent / 100)
    rate_after_disc = round2(reduced_mrp - disc_per_unit)
    line_total = round2(reduced_mrp * quantity)
    final_amount = round2(rate_after_disc * quantity)
    discount_amount = round2(line_total - final_amount)

    return {
        "id": item["id"],
        "mrp": reduced_mrp,
        "line_total": line_total,
        "discount_amount": discount_amount,
        "rate_after_disc": rate_after_disc,
        "final_amount": final_amount,
    }


def apply_bill_updates(db, bill, recalculated_items):
    new_subtotal = round2(sum(item["line_total"] for item in recalculated_items))
    new_total_discount = round2(sum(item["discount_amount"] for item in recalculated_items))
    new_final_total = round2(sum(item["final_amount"] for item in recalculated_items))
    original_advance_paid = round2(bill["advance_paid"] or 0)
    # If the bill was already fully paid before repricing, cap advance_paid to the
    # new total so the bill remains settled and the payment rows stay consistent.
    advance_paid = min(original_advance_paid, new_final_total)
    new_remaining = round2(new_final_total - advance_paid)

    db.executemany(
        """
        UPDATE bill_items
        SET mrp = ?, line_total = ?, discount_amount = ?, rate_after_disc = ?, final_amount = ?
        WHERE id = ?
        """,
        [
            (
                item["mrp"],
                item["line_total"],
                item["discount_amount"],
                item["rate_after_disc"],
                item["final_amount"],
                item["id"],
            )
            for item in recalculated_items
        ],
    )

    db.execute(
        """
        UPDATE bills
        SET subtotal = ?,
            total_discount = ?,
            final_total = ?,
            total_savings = ?,
            advance_paid = ?,
            remaining = ?,
            updated_at = datetime('now','localtime')
        WHERE id = ?
        """,
        (
            new_subtotal,
            new_total_discount,
            new_final_total,
            new_total_discount,
            advance_paid,
            new_remaining,
            bill["id"],
        ),
    )

    # Cash bills should keep a single cash payment matching the bill total.
    db.execute("DELETE FROM bill_payments WHERE bill_id = ?", (bill["id"],))
    db.execute(
        "INSERT INTO bill_payments (bill_id, payment_method, amount) VALUES (?, 'Cash', ?)",
        (bill["id"], advance_paid),
    )

    return {
        "subtotal": new_subtotal,
        "total_discount": new_total_discount,
        "final_total": new_final_total,
        "advance_paid": advance_paid,
        "remaining": new_remaining,
    }


def main():
    args = parse_args()
    validate_args(args)
    start_date, end_date = month_range(args.year, args.month)

    with closing(get_db()) as db:
        bills = fetch_target_bills(db, start_date, end_date)

        if not bills:
            print(f"No cash bills found between {start_date} and {end_date}.")
            return

        updated_count = 0
        skipped_count = 0
        current_total = current_cash_total(bills)

        print(
            f"Found {len(bills)} cash bill(s) between {start_date} and {end_date}. "
            f"MRP drop: {args.mrp_drop_percent:.2f}%."
        )
        print(f"Current cash sales total: {current_total:.2f}")
        print("Mode:", "APPLY" if args.apply else "DRY RUN")
        print()

        if args.apply:
            confirm = input(
                "Proceed with reducing bill amounts for these cash bills? Type 'yes' to continue: "
            ).strip().lower()
            if confirm != "yes":
                print("Aborted. No changes were applied.")
                return
            print()

        for bill in bills:
            items = fetch_bill_items(db, bill["id"])
            recalculated_items = [
                recalculate_item(item, args.mrp_drop_percent) for item in items
            ]

            try:
                totals = apply_bill_updates(db, bill, recalculated_items) if args.apply else {
                    "subtotal": round2(sum(item["line_total"] for item in recalculated_items)),
                    "total_discount": round2(sum(item["discount_amount"] for item in recalculated_items)),
                    "final_total": round2(sum(item["final_amount"] for item in recalculated_items)),
                    "advance_paid": min(
                        round2(bill["advance_paid"] or 0),
                        round2(sum(item["final_amount"] for item in recalculated_items)),
                    ),
                    "remaining": round2(
                        round2(sum(item["final_amount"] for item in recalculated_items))
                        - min(
                            round2(bill["advance_paid"] or 0),
                            round2(sum(item["final_amount"] for item in recalculated_items)),
                        )
                    ),
                }
            except Exception as exc:
                skipped_count += 1
                if args.apply:
                    db.rollback()
                print(f"SKIP {bill['bill_number']} ({bill['bill_date']}): {exc}")
                continue

            updated_count += 1
            print(
                f"{'UPDATE' if args.apply else 'PREVIEW'} {bill['bill_number']} "
                f"({bill['bill_date']}): final_total {round2(bill['final_total']):.2f} -> "
                f"{totals['final_total']:.2f}; advance_paid {round2(bill['advance_paid'] or 0):.2f} -> "
                f"{totals['advance_paid']:.2f}"
            )

        if args.apply:
            db.commit()
            print()
            print(f"Applied updates to {updated_count} bill(s); skipped {skipped_count}.")
        else:
            print()
            print(f"Previewed {updated_count} bill(s); would skip {skipped_count}.")


if __name__ == "__main__":
    main()
