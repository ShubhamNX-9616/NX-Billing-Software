import re

from utils import r2, cloth_type_prefix
from db.connection import IST_NOW

_CIPHER = 'RAYMONDSUI'


def deduct_stock(db, inventory_item_id, quantity, bill_id, created_by=None):
    item = db.execute(
        "SELECT current_stock FROM inventory_items WHERE id = ?", (inventory_item_id,)
    ).fetchone()
    if not item:
        return
    new_stock = r2(item["current_stock"] - quantity)
    db.execute(
        f"UPDATE inventory_items SET current_stock = ?, updated_at = {IST_NOW} WHERE id = ?",
        (new_stock, inventory_item_id),
    )
    db.execute(
        """INSERT INTO inventory_transactions
           (item_id, txn_type, quantity, reference_type, reference_id, created_by)
           VALUES (?, 'sale', ?, 'bill', ?, ?)""",
        (inventory_item_id, -quantity, bill_id, created_by),
    )


def restore_stock(db, inventory_item_id, quantity, bill_id, created_by=None):
    item = db.execute(
        "SELECT current_stock FROM inventory_items WHERE id = ?", (inventory_item_id,)
    ).fetchone()
    if not item:
        return
    new_stock = r2(item["current_stock"] + quantity)
    db.execute(
        f"UPDATE inventory_items SET current_stock = ?, updated_at = {IST_NOW} WHERE id = ?",
        (new_stock, inventory_item_id),
    )
    db.execute(
        """INSERT INTO inventory_transactions
           (item_id, txn_type, quantity, reference_type, reference_id, created_by)
           VALUES (?, 'sale_reversal', ?, 'bill', ?, ?)""",
        (inventory_item_id, quantity, bill_id, created_by),
    )


def compute_special_code(cost_price, supplier_name=''):
    """Encode cost price using the cipher alphabet, optionally prefixed with supplier initials."""
    n = round(abs(float(cost_price or 0)))
    encoded = ''.join(_CIPHER[int(d)] for d in str(n))
    if supplier_name:
        initials = ''.join(w[0].upper() for w in str(supplier_name).strip().split() if w)
        if initials:
            return f"{initials}-{encoded}"
    return encoded


def next_item_code(db, cloth_type):
    """Generate the next sequential item code for a given cloth type."""
    prefix = cloth_type_prefix(cloth_type)
    row = db.execute(
        "SELECT item_code FROM inventory_items WHERE item_code LIKE ? ORDER BY item_code DESC LIMIT 1",
        (f"{prefix}-%",)
    ).fetchone()
    if row:
        try:
            last_num = int(row['item_code'].split('-')[1])
        except (IndexError, ValueError):
            last_num = 0
        next_num = last_num + 1
    else:
        next_num = 1
    return f"{prefix}-{next_num:03d}"


def adjust_stock(db, item_id, quantity, notes, username):
    """Apply a manual stock adjustment. Returns new_stock, or None if item not found."""
    item = db.execute(
        "SELECT current_stock FROM inventory_items WHERE id = ?", (item_id,)
    ).fetchone()
    if not item:
        return None
    new_stock = r2(item["current_stock"] + quantity)
    db.execute(
        f"UPDATE inventory_items SET current_stock = ?, updated_at = {IST_NOW} WHERE id = ?",
        (new_stock, item_id),
    )
    db.execute(
        """INSERT INTO inventory_transactions
           (item_id, txn_type, quantity, reference_type, notes, created_by)
           VALUES (?, 'adjustment', ?, 'manual', ?, ?)""",
        (item_id, quantity, notes, username),
    )
    return new_stock


def apply_inventory_diff(db, old_qty_map, new_qty_map, bill_id, username):
    """Apply net stock changes when a bill's items are updated."""
    for inv_id in set(old_qty_map) | set(new_qty_map):
        old_qty = r2(old_qty_map.get(inv_id, 0))
        new_qty = r2(new_qty_map.get(inv_id, 0))
        diff = r2(new_qty - old_qty)
        if diff > 0:
            deduct_stock(db, inv_id, diff, bill_id, username)
        elif diff < 0:
            restore_stock(db, inv_id, -diff, bill_id, username)


def find_item_by_code(db, item_code):
    """Inventory row for a typed item code, or None.

    Tolerant of how staff type it: "sut4" / "sut-4" / "sut001" all find
    "SUT-004" / "SUT-001" (codes are PREFIX-NNN)."""
    item = db.execute(
        "SELECT * FROM inventory_items WHERE UPPER(item_code) = UPPER(?)", (item_code,)
    ).fetchone()
    if not item:
        # Typed "sut4" / "sut-4" for "SUT-004": match the number as an
        # integer, ignoring zero padding and the hyphen.
        m = re.fullmatch(r"([A-Za-z]+)[-\s]*(\d+)", item_code.strip())
        if m:
            item = db.execute(
                "SELECT * FROM inventory_items WHERE UPPER(item_code) = UPPER(?)",
                (f"{m.group(1)}-{int(m.group(2)):03d}",),
            ).fetchone()
    if not item:
        # Typed "sut001" for "SUT-001": retry ignoring hyphens and spaces.
        squashed = item_code.replace("-", "").replace(" ", "")
        if squashed:
            item = db.execute(
                """SELECT * FROM inventory_items
                   WHERE REPLACE(REPLACE(UPPER(item_code), '-', ''), ' ', '') = UPPER(?)
                   ORDER BY id LIMIT 1""",
                (squashed,),
            ).fetchone()
    return item
