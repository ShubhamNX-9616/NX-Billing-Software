# This module has been replaced by the db/ package.
# All imports that used `from database import ...` now use `from db import ...`.
# This file is kept only so any external tooling that references it gets a clear message.
raise ImportError(
    "database.py has been removed. Use `from db import get_db, close_db, "
    "generate_bill_number, init_db, seed_default_users` instead."
)
