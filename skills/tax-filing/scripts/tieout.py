#!/usr/bin/env python3
"""Tie computed figures to independent targets (source docs, IRS transcript).

Compares tax_calc.py output against a targets file and checks simple
cross-form sums. Fails (exit 1) if any figure differs by more than --tol.

Usage:
    python tax_calc.py constants.json inputs.json > work/calc.json
    python tieout.py work/calc.json work/targets.json [--tol 2]

targets.json example (dotted paths into calc.json; values from the filled
forms, 1099/W-2 totals, or the IRS return/account transcript):
    {
      "figures": {"federal.agi": 278829, "federal.total_tax": 38394.63},
      "sums": [
        {"name": "Sched D line 16 = 1040 line 7",
         "parts": [1905.00, 72.00], "equals": 1977.00}
      ]
    }
"""

import argparse
import json
import sys


def dig(obj, path):
    for part in path.split("."):
        obj = obj[part]
    return obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("calc")
    ap.add_argument("targets")
    ap.add_argument("--tol", type=float, default=2.0)
    a = ap.parse_args()
    calc = json.load(open(a.calc))
    targets = json.load(open(a.targets))
    bad = 0
    for path, want in targets.get("figures", {}).items():
        try:
            got = dig(calc, path)
        except KeyError:
            print(f"  MISSING   {path}")
            bad += 1
            continue
        ok = abs(got - want) <= a.tol
        bad += not ok
        print(f"  {'OK      ' if ok else 'MISMATCH'}  {path}: calc={got:,.2f} target={want:,.2f}")
    for s in targets.get("sums", []):
        got = sum(s["parts"])
        ok = abs(got - s["equals"]) <= a.tol
        bad += not ok
        print(f"  {'OK      ' if ok else 'MISMATCH'}  {s['name']}: {got:,.2f} vs {s['equals']:,.2f}")
    print(f"\n  {bad} discrepancies")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
