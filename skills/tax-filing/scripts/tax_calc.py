#!/usr/bin/env python3
"""Independent tax computation from a constants file + return inputs.

Computes the federal return (brackets, QDCG worksheet, itemized-vs-standard,
child tax credit with phase-out, NIIT, Additional Medicare Tax) and the
Virginia Form 760 tax, so the numbers on the filled PDFs can be tied out to
code instead of hand math.

Constants are NEVER hardcoded here. Look them up each year (see
reference/constants-template.json), record the source URL for each value, and
pass them in.

Usage:
    python tax_calc.py constants.json inputs.json

inputs.json keys (all dollars, missing = 0):
    wages, taxable_interest, ordinary_dividends, qualified_dividends,
    net_st_gain, net_lt_gain (after carryovers; Schedule D net),
    other_income, adjustments, qbi_deduction,
    itemized: {state_income_tax, real_estate_tax, personal_property_tax,
               mortgage_interest, charity, other}
    children (count for CTC), other_credits, other_taxes,
    medicare_wages, nii_override (optional),
    withholding, estimated_payments, medicare_surtax_withheld,
    va: {additions, subtractions, withholding, estimated_payments,
         dependents, itemized_override (optional)}
"""

import json
import sys


def bracket_tax(amount, brackets):
    """brackets: [[upper_limit_or_null, rate], ...] ascending."""
    tax, lower = 0.0, 0.0
    for upper, rate in brackets:
        top = amount if upper is None else min(amount, upper)
        if top > lower:
            tax += (top - lower) * rate
        if upper is None or amount <= upper:
            break
        lower = upper
    return tax


def qdcg_tax(taxable, preferential, c):
    """Qualified Dividends and Capital Gain Tax Worksheet."""
    preferential = max(0.0, min(preferential, taxable))
    ordinary = taxable - preferential
    zero_top, fifteen_top = c["qdcg"]["zero_top"], c["qdcg"]["fifteen_top"]
    # Room left in the 0% band after ordinary income
    at_zero = max(0.0, min(preferential, zero_top - ordinary))
    rest = preferential - at_zero
    # Room left in the 15% band
    fifteen_room = max(0.0, fifteen_top - max(ordinary, zero_top))
    at_fifteen = min(rest, fifteen_room)
    at_twenty = rest - at_fifteen
    pref_tax = at_fifteen * 0.15 + at_twenty * 0.20
    return bracket_tax(ordinary, c["brackets"]) + pref_tax


def salt_cap(magi, c):
    s = c["salt"]
    over = max(0.0, magi - s["phaseout_start"])
    return max(s["floor"], s["cap"] - s["phaseout_rate"] * over)


def ctc(magi, children, c):
    k = c["ctc"]
    credit = children * k["per_child"]
    over = max(0.0, magi - k["phaseout_start"])
    steps = -(-over // 1000)  # ceil per $1,000
    return max(0.0, credit - 50 * steps)


def federal(c, i):
    g = lambda k: float(i.get(k, 0) or 0)
    net_gain = g("net_st_gain") + g("net_lt_gain")
    cap_line7 = max(net_gain, -3000.0) if net_gain < 0 else net_gain
    income = (g("wages") + g("taxable_interest") + g("ordinary_dividends")
              + cap_line7 + g("other_income"))
    agi = income - g("adjustments")

    it = i.get("itemized", {})
    salt_paid = (it.get("state_income_tax", 0) + it.get("real_estate_tax", 0)
                 + it.get("personal_property_tax", 0))
    cap = salt_cap(agi, c)
    salt_allowed = min(salt_paid, cap)
    itemized = (salt_allowed + it.get("mortgage_interest", 0)
                + it.get("charity", 0) + it.get("other", 0))
    std = c["standard_deduction"]
    deduction = max(itemized, std)
    used = "itemized" if itemized > std else "standard"

    taxable = max(0.0, agi - deduction - g("qbi_deduction"))
    # Preferential income: qualified dividends + net capital gain (LT-limited)
    nlt = g("net_lt_gain")
    pref = g("qualified_dividends") + max(0.0, min(nlt, net_gain))
    tentative = qdcg_tax(taxable, pref, c)

    child_credit = ctc(agi, int(i.get("children", 0)), c)
    credits = child_credit + g("other_credits")

    nii = i.get("nii_override")
    if nii is None:
        nii = (g("taxable_interest") + g("ordinary_dividends")
               + max(0.0, net_gain))
    niit = c["niit"]["rate"] * max(
        0.0, min(nii, agi - c["niit"]["threshold"]))
    mw = g("medicare_wages") or g("wages")
    addl_med = c["addl_medicare"]["rate"] * max(
        0.0, mw - c["addl_medicare"]["threshold"])

    total_tax = (max(0.0, tentative - credits) + niit + addl_med
                 + g("other_taxes"))
    payments = (g("withholding") + g("estimated_payments")
                + g("medicare_surtax_withheld"))
    return {
        "agi": agi, "line7_capital": cap_line7,
        "itemized": itemized, "salt_cap": cap, "salt_allowed": salt_allowed,
        "standard": std, "deduction_used": used, "deduction": deduction,
        "taxable_income": taxable, "tentative_tax": tentative,
        "child_tax_credit": child_credit, "niit": niit,
        "addl_medicare": addl_med, "total_tax": total_tax,
        "payments": payments, "balance": total_tax - payments,
    }


def virginia(c, i, fed):
    v = c["virginia"]
    vi = i.get("va", {})
    it = i.get("itemized", {})
    vagi = fed["agi"] + vi.get("additions", 0) - vi.get("subtractions", 0)
    if "itemized_override" in vi:
        va_item = vi["itemized_override"]
    else:
        # VA: state/local INCOME tax is not deductible; check reference/virginia.md
        va_item = (min(it.get("real_estate_tax", 0)
                       + it.get("personal_property_tax", 0),
                       salt_cap(vagi, c))
                   + it.get("mortgage_interest", 0) + it.get("charity", 0)
                   + it.get("other", 0))
    ded = max(va_item, v["standard_deduction"])
    exemptions = v["exemption"] * (2 + int(vi.get("dependents", 0)))
    taxable = max(0.0, vagi - ded - exemptions)
    tax = bracket_tax(taxable, v["brackets"])
    paid = vi.get("withholding", 0) + vi.get("estimated_payments", 0)
    return {
        "va_agi": vagi, "va_itemized": va_item,
        "va_standard": v["standard_deduction"],
        "va_deduction_used": "itemized" if va_item > v["standard_deduction"]
        else "standard",
        "va_exemptions": exemptions, "va_taxable_income": taxable,
        "va_tax": tax, "va_payments": paid, "va_balance": tax - paid,
    }


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    c = json.load(open(sys.argv[1]))
    i = json.load(open(sys.argv[2]))
    fed = federal(c, i)
    out = {"year": c.get("year"), "federal": fed}
    if "virginia" in c:
        out["virginia"] = virginia(c, i, fed)
    print(json.dumps(out, indent=2, default=lambda x: round(x, 2)))


if __name__ == "__main__":
    main()
