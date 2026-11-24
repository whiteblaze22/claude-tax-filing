---
name: tax-filing
description: Prepare and fill federal and state (Virginia, California) tax return PDF forms
user_invocable: true
triggers:
  - do my taxes
  - prepare tax return
  - fill tax forms
  - file taxes
  - tax preparation
---

# Tax Filing Skill

Prepare federal and state income tax returns: read source documents, compute taxes, fill official PDF forms.

**Year-agnostic** — always look up current-year brackets, deductions, and credits. Never reuse prior-year values.

## Folder Structure

Organize all work into subfolders of the working directory:

```
working_dir/
  source/              ← user's source documents (W-2, 1099s, prior return, CSVs)
  work/                ← ALL intermediate files (extracted data, field maps, computations)
    tax_data.txt       ← extracted figures from source docs
    doc_status.txt     ← every source document + read status (see Step 1)
    constants.json     ← dated tax constants with source URLs (Step 3)
    inputs.json        ← return inputs for scripts/tax_calc.py
    calc.json          ← output of tax_calc.py (single source of truth)
    computations.txt   ← human-readable notes; numbers must come from calc.json
    f1040_fields.json  ← field discovery dumps
    f8949_fields.json
    f1040sd_fields.json
    va760_fields.json  ← (or ca540_fields.json)
    expected_*.json    ← verification expected values
  forms/               ← blank downloaded PDF forms
    f1040_blank.pdf
    f8949_blank.pdf
    f1040sd_blank.pdf
    va760_blank.pdf    ← (or ca540_blank.pdf)
  output/              ← final filled PDFs + fill script
    fill_YEAR.py       ← the fill script (reads values from work/calc.json)
    f1040_filled.pdf
    f8949_filled.pdf
    f1040sd_filled.pdf
    va760_filled.pdf   ← (or ca540_filled.pdf)
```

`work/`, `source/`, `forms/` and `output/` hold personal tax data. Never commit or publish them.

Create these folders at the start. Keep the working directory clean — no loose files.

## Context Budget Rules

These rules prevent context blowouts that cause compaction:

1. **NEVER read PDFs with the Read tool.** Each page becomes ~250KB of base64 images (a 9-page return = 1.8 MB). Extract text instead:
   ```bash
   python3 -c "
   import pdfplumber
   with pdfplumber.open('source/document.pdf') as pdf:
       for p in pdf.pages: print(p.extract_text())
   "
   ```
2. **NEVER read the same document twice.** Save extracted figures to `work/tax_data.txt` on first read.
3. **Run field discovery ONCE per form** as a bulk JSON dump to `work/`. Do NOT use `--search` repeatedly.
4. **Save all computed values to `work/computations.txt`** so they survive compaction.

## Workflow

### Step 1: Gather Source Documents

Ask the user what documents they have. Read files from `source/` (move them there if needed). Use pdfplumber for PDFs, Read tool for CSVs.

Save all extracted figures to `work/tax_data.txt` immediately — one section per document with every relevant number.

**Document inventory — HARD STOP rule.** Write `work/doc_status.txt` listing every source file with a status: `READ`, `OCR'd`, or `UNREADABLE`. Scanned/encrypted/MIME-wrapped PDFs must be OCR'd or the user asked for a readable copy (broker websites usually offer a re-download). **Never assume $0 for a document you could not read.** Do not proceed to computation until every gap is either resolved or explicitly acknowledged by the user. Also check for "pending/corrected 1099" notices. In 2025 an unreadable brokerage 1099, a missing interest form and a missing spouse W-2 were all silently treated as zero.

### Step 2: Confirm Filing Details — MANDATORY

**You MUST ask the user every one of these questions and WAIT for answers before proceeding.** Do NOT skip this step even if you think you know the answers from memory or source documents. Tax returns are legal documents.

- Filing status (Single, MFJ, MFS, HOH, QSS)
- Dependents (number, names)
- State of residence
- Standard vs. itemized deduction preference
- Digital asset / cryptocurrency transactions (Yes/No) — stock trades are NOT digital assets
- Health coverage status (for CA)
- Any estimated tax payments made (federal and state, with dates)
- **Spouse (if MFJ): wages/W-2, self-employment, any 1099s, and whether the spouse has earned income** (needed for dependent-care credit/exclusion). Get the spouse's documents; do not guess.
- Charitable giving (cash and appreciated stock), HSA/IRA contributions
- Prior-year carryovers (capital loss, AMT credit / Form 8801, QBI loss)
- Equity compensation: RSU/ESPP/ISO activity, Forms 3921/3922, any ISO exercise-and-hold in past years (AMT)
- Dependent-care expenses and provider details
- Any other credits or adjustments

**Do NOT proceed to Step 3 until the user has answered.** "Same as last year" counts as confirmation.

### Step 3: Look Up Year-Specific Values — constants file

Write `work/constants.json` (start from `reference/constants-template.json`). Every value needs an official source URL (IRS Rev. Proc./IRS.gov for federal, tax.virginia.gov for Virginia, FTB.ca.gov for CA). **Never fill from memory.** Also search for laws enacted since last year that change the numbers (standard deduction, child tax credit, SALT cap and its phase-down, new deductions). Show the table to the user.

Required: brackets, standard deduction, QDCG 0%/15% thresholds, child tax credit (amount and phase-out), SALT cap/floor/phase-out, NIIT and Additional Medicare thresholds, Social Security wage base, AMT exemption/phase-out, and the state brackets, standard deduction and exemption.

(2025 errors from recalled values: standard deduction $30,000 vs $31,500, child credit $2,000 vs $2,200, SALT cap $10,000 vs $40,000.)

### Step 4: Compute Federal Return

Build `work/inputs.json` from `work/tax_data.txt`, then compute in code, never by hand:

```bash
python scripts/tax_calc.py work/constants.json work/inputs.json > work/calc.json
```

`tax_calc.py` applies the brackets, the QDCG worksheet, **itemized vs standard (always compared, with the SALT cap and phase-down)**, child tax credit phase-out, NIIT, Additional Medicare Tax, and Virginia. `work/calc.json` is the single source of truth; the fill script and every summary must read from it, not retype numbers.

Line structure for reference:
1. Gross Income: W-2 wages (1a) + interest (2b) + dividends (3b) + capital gain/loss (7)
2. Adjustments → AGI (Line 11)
3. Deductions → Taxable Income (Line 15)
4. Tax: QDCG worksheet if qualified dividends/capital gains exist
5. Credits, other taxes → Total Tax (Line 24)
6. Payments (withholding, estimated) → Refund/Owed
7. If refund: collect direct deposit info (routing, account, type)
8. If AMT is possible (ISO exercises, large SALT/itemized), run the Form 6251 check; see `reference/equity-comp.md`.

Record the human-readable summary in `work/computations.txt`, copying values from `calc.json`.

### Step 5: Compute Capital Gains (if applicable)

1. Form 8949: individual transactions (Part I short-term, Part II long-term)
2. Schedule D: totals, $3,000 loss limitation, carryover calculation
3. Net gain/loss → 1040 Line 7

**Rounding rule**: Form 8949 and Schedule D must use **exact cents** matching the 1099-B / 1099-DA source documents. Only Form 1040 rounds to the nearest whole dollar (Line 7 = round of Schedule D Line 16). Do NOT round amounts on 8949 or Schedule D.

### Step 6: Compute State Return

**Virginia (Form 760)** — read `reference/virginia.md` first. `tax_calc.py` computes it from the `virginia` block of `constants.json`.
1. Federal AGI → Schedule ADJ additions/subtractions → VA AGI
2. Larger of VA standard deduction or VA itemized deductions (**state income tax is NOT deductible in Virginia**)
3. Personal exemptions (a deduction per person) → taxable income
4. Tax from the VA schedule − credits
5. VA withholding + estimated payments → Refund/Owed

**California (Form 540)**
1. Federal AGI → CA adjustments → CA taxable income
2. Tax from brackets − exemption credits → total tax
3. Withholding → Refund/Owed

### Step 7: Download Blank PDF Forms

Save to `forms/` directory.

**IRS**: Use `/irs-prior/` for prior-year forms (`/irs-pdf/` is always current year):
```
https://www.irs.gov/pub/irs-prior/f1040--YEAR.pdf
https://www.irs.gov/pub/irs-prior/f8949--YEAR.pdf
https://www.irs.gov/pub/irs-prior/f1040sd--YEAR.pdf
```

**VA**: Form 760 and schedules from tax.virginia.gov (Forms section, tax year).

**CA**: `ftb.ca.gov/forms/YEAR/` for state forms.

Also download Form 2441 (dependent care), Schedule 2, Schedule 3, Schedule A (if itemizing), Form 8959, 8960, 6251 as needed.

Verify each download has `%PDF-` header (not an HTML error page).

### Step 8: Discover Field Names & Fill Forms

#### Discovery — ONCE per form, use `--compact`

```bash
python scripts/discover_fields.py forms/f1040_blank.pdf --compact > work/f1040_fields.json
python scripts/discover_fields.py forms/f8949_blank.pdf --compact > work/f8949_fields.json
python scripts/discover_fields.py forms/f1040sd_blank.pdf --compact > work/f1040sd_fields.json
python scripts/discover_fields.py forms/va760_blank.pdf --compact > work/va760_fields.json   # or ca540
```

`--compact` outputs a minimal `{field_name: description}` mapping — each field name is paired with its tooltip/speak description so you can map line numbers to field names directly without manual inspection. Radio buttons include their option values (e.g. `{"/2": "Single", "/1": "MFJ"}`).

Do NOT use `--search` repeatedly or `--json` (which dumps raw metadata and wastes context).

**HARD FAIL**: If discovery returns 0 human-readable descriptions, STOP. Do not guess field names.

#### Fill Script

Write `output/fill_YEAR.py` using `scripts/fill_forms.py`:

- **`add_suffix(d)`** — appends `[0]` to text field keys. Required for IRS forms.
- **`fill_irs_pdf(in, out, fields, checkboxes, radio_values)`** — IRS forms. `radio_values` for filing status, yes/no, checking/savings.
- **`fill_pdf(in, out, fields, checkboxes)`** — CA forms. Matches by `/Parent` chain + `/AP/N` keys.

Output filled PDFs to `output/`.

### Step 9: Verify

```bash
python scripts/verify_filled.py output/f1040_filled.pdf work/expected_f1040.json
```

Fix any failures, re-run fill script.

That only checks that fields were filled as intended. Also tie the numbers out independently:

```bash
python scripts/tieout.py work/calc.json work/targets.json --tol 2
```

`targets.json` holds figures from outside the fill script: W-2/1099 totals, Form 8949 vs Schedule D vs 1040 line 7, Schedule B vs 1099s, W-2 box 14 RSU/ESPP income vs the 8949 adjustments, Virginia income schedule vs the 760. Use IRS return/account transcripts once they exist (prior year or amended). Do not present the return until every item ties or the difference is explained.

### Step 10: Present Results

Show a summary table, verification checklist, capital loss carryover (if any), list of assumptions and any documents not read (from `work/doc_status.txt`), then:

- **Sign your returns** — unsigned returns are rejected
- **Payment instructions** (if owed) — IRS Direct Pay, EFTPS, IRS online account, or a payment plan; Virginia Tax online account; deadline April 15. A payment can be **returned** by the bank (e.g. wrong routing/account); that is not the same as paid. After paying, confirm the payment posted on the IRS account transcript (TC 670/671/673 without a same-day reversal 672) and in the bank. If it was returned, repay promptly and use Look Up a Payment with the confirmation number to see the status
- **Extensions** — Form 4868 extends filing, not payment; send an estimate with it
- **Direct deposit** — recommend it for refunds; ask for bank info if not provided
- **Filing options** — e-file (Free File, VA Free File, CalFile) or mailing addresses
- **After filing** — pull the IRS account/return transcripts and compare to what was filed; if the return left money on the table, consider an amended return (Form 1040-X, three years from filing)

### Step 11: MFJ vs Single Comparison (if Married Filing Jointly)

After completing the MFJ return, compute what each spouse would owe if they filed Single instead. This helps the couple understand the tax impact of their filing status choice.

For each spouse, compute a hypothetical Single return:
1. **Income**: Use only that spouse's W-2, 1099-INT, 1099-DIV, and 1099-B/1099-DA
2. **Standard deduction**: Single amount (typically half of MFJ)
3. **QBI deduction**: Based on that spouse's 199A dividends only
4. **Tax**: Use Single brackets and QDCG worksheet with Single 0%/15%/20% thresholds
5. **Credits**: Foreign tax credit only if that spouse paid foreign tax
6. **Additional Medicare Tax**: Use the $200K Single threshold (not $250K MFJ)
7. **Withholding**: That spouse's W-2 Box 2 only

Present a side-by-side comparison table:

| | MFJ (actual) | Both Single | Difference |
|--|-------------|-------------|------------|
| Combined tax | | | |
| Combined withheld | | | |
| **Combined owed** | | | |

Include key takeaways — especially the Additional Medicare Tax threshold difference ($250K MFJ vs $200K Single per spouse), which is often the largest driver of the MFJ vs Single gap.

## Key Gotchas

### Context
- NEVER use Read tool on PDFs — use pdfplumber
- NEVER read same document twice — save to `work/tax_data.txt`
- Field discovery once per form with `--compact` — no `--json` (wastes context), no repeated `--search`

### Field Discovery
- Field names change between years — always discover fresh
- XFA template is in `/AcroForm` → `/XFA` array, NOT from brute-force xref scanning
- Do NOT use `xml.etree` for XFA — use regex (IRS XML has broken namespaces)

### PDF Filling
- Remove XFA from AcroForm, set NeedAppearances=True, use auto_regenerate=False
- Checkboxes: set both `/V` and `/AS` to `/1` or `/Off`
- IRS fields need `[0]` suffix — use `add_suffix()`
- IRS checkboxes match by `/T` directly; radio groups match by `/AP/N` key via `radio_values`

### Rounding
- **Form 8949 & Schedule D**: Report **exact cents** (e.g. "11.36", "-240.00") to match 1099-B / 1099-DA source documents. Never round these.
- **Form 1040**: Round all amounts to the **nearest whole dollar** per IRS instructions. Line 7 (capital gain) = nearest-dollar rounding of Schedule D Line 16.
- **CA 540 / VA 760**: Round to nearest whole dollar.

### Equity compensation
- RSU basis = vest FMV; ESPP disqualifying income needs a Form 8949 code B adjustment; ISOs need a Form 6251/8801 check. See `reference/equity-comp.md`.

### Lessons from a real 2025 return
- Recalled constants were wrong (standard deduction, child credit, SALT cap). Always use `work/constants.json` with sources.
- Itemized vs standard was compared once using the wrong SALT cap and never rerun. `tax_calc.py` compares every time.
- Virginia state income tax was wrongly included in Virginia itemized deductions.
- Unreadable PDFs and a missing spouse W-2 were treated as $0.
- Three different "amount owed" figures existed across files because numbers were retyped; use `calc.json`.
- A Direct Pay payment was "Returned" and nobody noticed until the IRS transcript showed a balance; verify payments posted.

### Form-Specific
- **1040**: First few fields (`f1_01`-`f1_03`) are fiscal year headers, not name fields. SSN = 9 digits, no dashes. Digital assets = crypto only, not stocks.
- **8949**: Box A/B/C checkboxes are 3-way radio buttons. Totals at high field numbers (e.g. `f1_115`-`f1_119`), not after last data row. Schedule D lines 1b/8b (from 8949), not 1a/8a.
- **Schedule D**: Some fields have `_RO` suffix (read-only) — skip those.
- **VA 760**: Discover fields fresh; Virginia forms are not XFA IRS-style, so use `fill_pdf` and confirm dependent rows (names/SSNs) filled. Generate a Schedule INC-style income summary and an itemized-deductions summary if Virginia requests documentation.
- **CA 540**: Field names are `540-PPNN` (page+sequence, NOT line numbers). Checkboxes end with `" CB"`, radio buttons use named AP keys.
- **Downloads**: Prior-year IRS = `irs.gov/pub/irs-prior/`, current = `irs.gov/pub/irs-pdf/`
