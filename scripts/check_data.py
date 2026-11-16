"""
Read-only health check: finds bad dates and money that does not add up.

Usage (from the project root):
    python scripts/check_data.py
    python scripts/check_data.py --billing path/to/billing.db --tailoring path/to/tailoring.db

Changes nothing (the databases are opened read-only). Exit code 0 = clean,
1 = problems found, so it can also be run on a schedule.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services.data_check import format_report, run_checks  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Read-only check of billing / tailoring / measurements data.")
    parser.add_argument("--billing", default=os.path.join(ROOT, "billing.db"))
    parser.add_argument("--tailoring", default=os.path.join(ROOT, "tailoring.db"))
    parser.add_argument("--measurements", default=os.path.join(ROOT, "measurements.db"))
    args = parser.parse_args()

    problems, skipped = run_checks(args.billing, args.tailoring, args.measurements)
    print(format_report(problems, skipped))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
