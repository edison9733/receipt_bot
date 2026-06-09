#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tax_config.py  —  LHDN tax configuration for the receipt bot.

ASSESSMENT YEAR: YA 2025  (income earned 1 Jan–31 Dec 2025, filed in 2026)
Form B (Borang B) — resident individual WITH business income.

Verified against:
  - LHDN "Tax Relief Resident Individual YA 2025" infographic (hasil.gov.my, updated 2026-01-19)
  - LHDN Public Ruling No. 7/2025
  - LHDN Form B 2024 return + Explanatory Notes (Part N structure; carried into YA2025)
  - Budget 2025 measures

HANDOFF NOTES FOR CLAUDE CODE
-----------------------------
1. This file is pure data + tiny helpers. Import it into bot.py:
       from tax_config import (
           ASSESSMENT_YEAR, FORM_B_EXPENSE_BOXES, EXPENSE_CATEGORIES,
           PERSONAL_RELIEFS, classify_expense, relief_cap_remaining,
       )
2. The bot currently writes ONE free-text "Category" per receipt. Recommended upgrade:
   store BOTH (a) an expense category key from EXPENSE_CATEGORIES and
   (b) the Form B box it rolls into (form_b_box), so the Sheet can group by box.
3. DUAL-USE categories (business N24 OR personal Lifestyle relief, never both) are
   flagged needs_business_personal_flag=True. The bot should ask the user
   "business or personal use?" for these before deciding the tax treatment.
4. Caps marked sub_cap_of sit INSIDE a parent cap — never sum them past the parent.
5. All amounts are RM. 7-year receipt retention required by LHDN.
"""

ASSESSMENT_YEAR = "YA 2025"
CURRENCY = "MYR"
RECEIPT_RETENTION_YEARS = 7

# Filing deadlines for YA2025 (e-Filing), per LHDN RF Filing Programme 2026
FILING_DEADLINES = {
    "form_be_no_business": {"due": "2026-04-30", "efiling_grace": "2026-05-15"},
    "form_b_with_business": {"due": "2026-06-30", "efiling_grace": "2026-07-15"},
}

# ──────────────────────────────────────────────────────────────────────────
# PART 1 — FORM B BUSINESS EXPENSE BOXES (Part N, Income Statement)
# Deductibility test: s.33(1) Income Tax Act 1967 (wholly & exclusively for
# producing gross income). Disallowed items: s.39. Only N15 has an official
# LHDN one-line note; N16–N24 have NO official "includes" list — the example
# text below is COMMON PRACTICE, not an LHDN enumeration.
# ──────────────────────────────────────────────────────────────────────────
FORM_B_EXPENSE_BOXES = {
    "N5":  {"label": "Purchases and cost of production",
            "official_note": None,
            "common_practice": "Cost of goods sold, stock for resale, direct production cost, "
                               "less discounts/rebates/purchase returns.",
            "block": "cost_of_sales"},
    "N15": {"label": "Loan interest",
            "official_note": "Total expenditure on interest excluding interest on hire purchase / lease.",
            "common_practice": "Interest on business loans (excludes hire-purchase / lease interest).",
            "block": "expense"},
    "N16": {"label": "Salaries and wages",
            "official_note": None,
            "common_practice": "Staff salary, allowance, EPF, SOCSO, EIS, staff costs.",
            "block": "expense"},
    "N17": {"label": "Rental / lease",
            "official_note": None,
            "common_practice": "Office rent, co-working space, business premise rental, "
                               "lease rental for business equipment/machinery.",
            "block": "expense"},
    "N18": {"label": "Contract and subcontracts",
            "official_note": None,
            "common_practice": "Outsourced work, freelancers, contractors, subcontracted "
                               "design/dev/reporting directly related to business income.",
            "block": "expense"},
    "N19": {"label": "Commissions",
            "official_note": None,
            "common_practice": "Sales/referral/platform/agent commission to secure sales.",
            "block": "expense"},
    "N20": {"label": "Bad debts",
            "official_note": None,
            "common_practice": "Specific trade debts written off (general provision NOT deductible).",
            "block": "expense"},
    "N21": {"label": "Travelling and transport",
            "official_note": None,
            "common_practice": "Business travel, client meetings, petrol/mileage, toll, parking, "
                               "e-hailing for business, flights/hotel for business trips. "
                               "Avoid personal/private travel.",
            "block": "expense"},
    "N22": {"label": "Repairs and maintenance",
            "official_note": None,
            "common_practice": "Repairing business assets, equipment servicing, repainting. "
                               "NOT renovation/improvement that creates a capital asset.",
            "block": "expense"},
    "N23": {"label": "Promotion and advertisement",
            "official_note": None,
            "common_practice": "Ads, marketing tools, sponsored posts, website promotion, "
                               "design for ads, flyers, branded gifts.",
            "block": "expense"},
    "N24": {"label": "Other expenses",
            "official_note": None,
            "common_practice": "Utilities, internet, phone, software subscriptions, data tools, "
                               "office supplies, stationery, printing, accounting/tax fees, "
                               "business insurance, bank charges, licence renewal, staff training, "
                               "legal fees for trade-debt recovery.",
            "block": "expense"},
}

# Capital items are NOT N15–N24 expenses; depreciation is added back at N27 and
# relief is given via CAPITAL ALLOWANCES instead. Flag these for the user.
CAPITAL_ALLOWANCE_NOTE = (
    "Computers, machinery, and enduring software licences are CAPITAL items: "
    "claim via capital allowances, not as N15–N24 expenses. Depreciation is disallowed."
)

# ──────────────────────────────────────────────────────────────────────────
# PART 2 — BOT EXPENSE CATEGORIES  ->  Form B box mapping
# needs_business_personal_flag=True  => dual-use; ask user business vs personal.
# capital_warning=True               => likely capital item (see note above).
# personal_default=True              => usually NOT a business expense (personal).
# ──────────────────────────────────────────────────────────────────────────
EXPENSE_CATEGORIES = {
    "food_beverage":      {"label": "Food & Beverage",      "form_b_box": "N24",
                           "note": "Client entertainment only 50% deductible (s.39); staff refreshments full."},
    "transportation":     {"label": "Transportation",       "form_b_box": "N21"},
    "travel":             {"label": "Travel",               "form_b_box": "N21",
                           "redundant_with": "transportation",
                           "note": "Redundant with Transportation — both map to N21."},
    "groceries":          {"label": "Groceries",            "form_b_box": "N5",
                           "personal_default": True,
                           "note": "Personal unless trading stock / raw material (then N5)."},
    "communication":      {"label": "Communication",        "form_b_box": "N24",
                           "needs_business_personal_flag": True,
                           "note": "Phone/internet: business N24 OR personal Lifestyle relief, not both."},
    "utilities":          {"label": "Utilities",            "form_b_box": "N24",
                           "needs_business_personal_flag": True,
                           "note": "Business-use only; personal portion not deductible."},
    "office_supplies":    {"label": "Office Supplies",      "form_b_box": "N24"},
    "subscriptions":      {"label": "Subscriptions",        "form_b_box": "N24",
                           "needs_business_personal_flag": True,
                           "note": "Business software/services; personal subs may fall under Lifestyle relief."},
    "equipment_software": {"label": "Equipment & Software", "form_b_box": "CAPITAL",
                           "capital_warning": True,
                           "needs_business_personal_flag": True,
                           "note": "Likely capital allowance, NOT N24. Personal device may be Lifestyle relief."},
    "entertainment":      {"label": "Entertainment",        "form_b_box": "N24",
                           "note": "Client entertainment 50% restricted (s.39)."},
    "professional_services": {"label": "Professional Services", "form_b_box": "N24",
                           "note": "Legal/accounting/consulting; if subcontracted scope of work -> N18."},
    "rent":               {"label": "Rent",                 "form_b_box": "N17",
                           "note": "Business premise/equipment rental. No personal 'rent' relief exists."},
    "other":              {"label": "Other",                "form_b_box": "N24"},
}

# ──────────────────────────────────────────────────────────────────────────
# PART 3 — PERSONAL TAX RELIEFS (YA 2025) — Part H of the return
# cap            : RM ceiling for this line
# sub_cap_of     : key of the parent relief whose cap this counts toward
# new_ya2025     : True if newly introduced/increased for YA2025
# not_for_business: True if relief is void when the item is used for business
# tiers          : alternative to a single cap (e.g. first-home loan interest)
# once_every_years / age_limit / claimants : eligibility constraints
# ──────────────────────────────────────────────────────────────────────────
PERSONAL_RELIEFS = {
    # --- Individual & spouse ---
    "self_individual": {"label": "Self / individual & dependent relatives",
                        "cap": 9000, "automatic": True},
    "disabled_individual": {"label": "Disabled individual (OKU, additional)",
                        "cap": 7000, "new_ya2025": True,
                        "note": "Increased from RM6,000; requires JKM OKU registration."},
    "spouse_alimony":   {"label": "Husband / wife / alimony to former wife", "cap": 4000},
    "disabled_spouse":  {"label": "Disabled spouse (additional)",
                        "cap": 6000, "new_ya2025": True, "note": "Increased from RM5,000."},

    # --- Medical & special needs ---
    "parents_medical":  {"label": "Medical/dental/special-needs/carer for parents & grandparents",
                        "cap": 8000,
                        "note": "Parents' full check-up & vaccination restricted to RM1,000 within this."},
    "basic_support_equipment": {"label": "Basic supporting equipment (disabled self/spouse/child/parent)",
                        "cap": 6000},
    "medical_self_spouse_child": {"label": "Medical for self/spouse/child (overall)",
                        "cap": 10000,
                        "note": "Umbrella cap. Sub-caps below all count toward this RM10,000."},
    "medical_vaccination": {"label": "Vaccination", "cap": 1000,
                        "sub_cap_of": "medical_self_spouse_child"},
    "medical_dental":   {"label": "Dental examination & treatment", "cap": 1000,
                        "sub_cap_of": "medical_self_spouse_child"},
    "medical_checkup_mental": {"label": "Full check-up / disease & mental-health screening / "
                                        "self-health monitoring devices / self-test kits",
                        "cap": 1000, "sub_cap_of": "medical_self_spouse_child",
                        "note": "YA2025 scope expanded to self-monitoring devices (glucometer, BP, thermometer)."},
    "child_learning_disability": {"label": "Child (<=18) learning-disability diagnosis / "
                                          "early intervention / rehabilitation",
                        "cap": 6000, "sub_cap_of": "medical_self_spouse_child",
                        "new_ya2025": True, "note": "Increased from RM4,000; within the RM10,000 cap."},

    # --- Education ---
    "self_education":   {"label": "Self education fees", "cap": 7000,
                        "sub_limit": {"upskilling_self_enhancement": 2000},
                        "note": "Upskilling/self-enhancement courses sub-limited to RM2,000."},

    # --- Lifestyle & green ---
    "lifestyle":        {"label": "Lifestyle (books, PC/phone/tablet, internet, courses)",
                        "cap": 2500, "not_for_business": True,
                        "note": "PC/tablet must be NOT for business use; internet under own name."},
    "sports":           {"label": "Sports equipment & activities",
                        "cap": 1000, "new_ya2025": True,
                        "note": "Increased from RM500; gym membership, gear, facility/competition fees."},
    "ev_green":         {"label": "EV charging facility + food-waste composting machine",
                        "cap": 2500, "not_for_business": True,
                        "new_ya2025": True, "note": "Composting machine added YA2025; runs YA2025–YA2027."},

    # --- Insurance, savings & contributions ---
    "life_insurance_epf": {"label": "Life insurance + EPF (combined)", "cap": 7000,
                        "sub_limit": {"epf_approved_scheme": 4000, "life_insurance_takaful": 3000},
                        "note": "EPF RM4,000 + life/takaful RM3,000. Pensioners w/o EPF may use full RM7,000."},
    "education_medical_insurance": {"label": "Education & medical insurance",
                        "cap": 4000, "new_ya2025": True, "note": "Increased from RM3,000."},
    "prs_annuity":      {"label": "PRS / deferred annuity", "cap": 3000,
                        "note": "Extended to YA2030."},
    "socso_eis":        {"label": "SOCSO / EIS contribution", "cap": 350},

    # --- Children, family savings, breastfeeding ---
    "child_below_18":   {"label": "Child below 18 (unmarried)", "cap": 2000, "per_child": True},
    "child_18plus_pretertiary": {"label": "Child 18+ unmarried, pre-tertiary full-time "
                                         "(A-Level/cert/matriculation/prep)",
                        "cap": 2000, "per_child": True},
    "child_18plus_tertiary": {"label": "Child 18+ unmarried, diploma+ (Malaysia) / degree+ (overseas)",
                        "cap": 8000, "per_child": True},
    "disabled_child":   {"label": "Disabled child (base)", "cap": 8000, "per_child": True,
                        "new_ya2025": True, "note": "Increased from RM6,000."},
    "disabled_child_higher_ed": {"label": "Disabled child 18+ in higher education (additional)",
                        "cap": 8000, "per_child": True,
                        "note": "Stacks with disabled_child base -> up to RM16,000 total."},
    "breastfeeding_equipment": {"label": "Breastfeeding equipment (child <=2, female taxpayer)",
                        "cap": 1000, "once_every_years": 2},
    "childcare_kindergarten": {"label": "Childcare centre / kindergarten fees (child <=6, registered)",
                        "cap": 3000, "claimants": "one parent per child"},
    "sspn_net_deposit": {"label": "SSPN net deposit (deposits minus withdrawals)",
                        "cap": 8000, "claimants": "one parent per child",
                        "note": "Extended YA2025–YA2027."},

    # --- Housing (NEW for YA2025) ---
    "first_home_loan_interest": {"label": "First-home housing-loan interest",
                        "cap": None, "new_ya2025": True,
                        "tiers": [
                            {"house_price_max": 500000, "relief": 7000},
                            {"house_price_min": 500001, "house_price_max": 750000, "relief": 5000},
                        ],
                        "note": "SPA dated 1 Jan 2025–31 Dec 2027; claimable 3 consecutive YAs."},
}


# ──────────────────────────────────────────────────────────────────────────
# PART 4 — tiny helpers (safe to extend in bot.py)
# ──────────────────────────────────────────────────────────────────────────
def classify_expense(category_key):
    """Return the Form B box dict for a bot expense category key, or None."""
    cat = EXPENSE_CATEGORIES.get(category_key)
    if not cat:
        return None
    box = cat["form_b_box"]
    return {
        "category_label": cat["label"],
        "form_b_box": box,
        "form_b_label": FORM_B_EXPENSE_BOXES.get(box, {}).get("label", box),
        "needs_business_personal_flag": cat.get("needs_business_personal_flag", False),
        "capital_warning": cat.get("capital_warning", False),
        "personal_default": cat.get("personal_default", False),
    }


def relief_cap_remaining(relief_key, already_claimed):
    """Remaining headroom for a relief. For tiered reliefs, returns the max tier."""
    r = PERSONAL_RELIEFS.get(relief_key)
    if not r:
        return None
    cap = r.get("cap")
    if cap is None and r.get("tiers"):
        cap = max(t["relief"] for t in r["tiers"])
    if cap is None:
        return None
    return max(0, cap - already_claimed)


def first_home_relief(house_price):
    """Return the first-home loan-interest relief for a given house price (RM)."""
    for t in PERSONAL_RELIEFS["first_home_loan_interest"]["tiers"]:
        lo = t.get("house_price_min", 0)
        hi = t.get("house_price_max", float("inf"))
        if lo <= house_price <= hi:
            return t["relief"]
    return 0  # house price above RM750,000 => no relief


if __name__ == "__main__":
    # quick self-check / summary print
    print(f"{ASSESSMENT_YEAR}  |  {len(FORM_B_EXPENSE_BOXES)} Form B boxes  |  "
          f"{len(EXPENSE_CATEGORIES)} expense categories  |  "
          f"{len(PERSONAL_RELIEFS)} relief lines")
    dual = [k for k, v in EXPENSE_CATEGORIES.items()
            if v.get("needs_business_personal_flag")]
    print("Dual-use (ask business/personal):", ", ".join(dual))
    print("First-home @ RM450k ->", first_home_relief(450000))
    print("First-home @ RM600k ->", first_home_relief(600000))
    print("First-home @ RM800k ->", first_home_relief(800000))
