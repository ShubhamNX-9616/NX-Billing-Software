from utils import r2


def deduct_stock(db, inventory_item_id, quantity, bill_id, created_by=None):
    item = db.execute(
        "SELECT current_stock FROM inventory_items WHERE id = ?", (inventory_item_id,)
    ).fetchone()
    if not item:
        return
    new_stock = r2(item["current_stock"] - quantity)
    db.execute(
        "UPDATE inventory_items SET current_stock = ?, updated_at = datetime('now','localtime') WHERE id = ?",
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
        "UPDATE inventory_items SET current_stock = ?, updated_at = datetime('now','localtime') WHERE id = ?",
        (new_stock, inventory_item_id),
    )
    db.execute(
        """INSERT INTO inventory_transactions
           (item_id, txn_type, quantity, reference_type, reference_id, created_by)
           VALUES (?, 'sale_reversal', ?, 'bill', ?, ?)""",
        (inventory_item_id, quantity, bill_id, created_by),
    )
