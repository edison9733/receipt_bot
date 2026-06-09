#!/usr/bin/env python3
"""
Adapter: turns the authoritative LHDN data in tax_config.py into the flat
strings, lists, dicts and helpers that bot.py and setup_sheets.py consume.

WHY TWO FILES
  • tax_config.py = the source of truth (Form B Part-N expense boxes, the
    expense→box mapping, and every personal relief with its cap / sub-cap /
    tier / "new for YA2025" flag), verified against the LHDN websites.
  • categories.py = this thin layer that exposes those values as the simple
    names the rest of the bot already imports, so Google Sheets dropdowns,
    Drive folder names, the DeepSeek prompt and the Summary formulas all use
    byte-for-byte identical strings.

Edit category DATA in tax_config.py. Edit the bot-facing ORDER / display
names here. Ordering below = most commonly used → least commonly used, so the
dropdowns and Summary never need scrolling for everyday items.
"""

import tax_config as tc

# ── Receipt type labels ────────────────────────────────────────────────
TYPE_EXPENSE = "Expense"
TYPE_RELIEF  = "Relief"

# Drive top-level folder names (also the Google Sheet tab names)
EXPENSE_FOLDER = "Expenses"
RELIEF_FOLDER  = "Relief"

# Handy constants surfaced from tax_config
ASSESSMENT_YEAR         = tc.ASSESSMENT_YEAR              # "YA 2025"
RECEIPT_RETENTION_YEARS = tc.RECEIPT_RETENTION_YEARS      # 7
FILING_DEADLINES        = tc.FILING_DEADLINES


# ── Expense categories (most used → least used) ────────────────────────
# Keys into tax_config.EXPENSE_CATEGORIES, in dropdown order.
_EXPENSE_ORDER = [
    "food_beverage", "transportation", "groceries", "communication",
    "utilities", "office_supplies", "subscriptions", "equipment_software",
    "entertainment", "travel", "professional_services", "rent", "other",
]
EXPENSE_CATEGORIES = [tc.EXPENSE_CATEGORIES[k]["label"] for k in _EXPENSE_ORDER]

# display label → Form B Part-N box code ("N5"/"N17"/"N21"/"N24"/"CAPITAL")
EXPENSE_FORM_B_BOX = {
    tc.EXPENSE_CATEGORIES[k]["label"]: tc.EXPENSE_CATEGORIES[k]["form_b_box"]
    for k in _EXPENSE_ORDER
}


# ── Tax-relief categories (most used → least used) ─────────────────────
# (bot display name, key into tax_config.PERSONAL_RELIEFS)
# Display names double as Drive folder names + Sheet dropdown values, so keep
# them short and stable. Caps + notes are pulled live from tax_config.
_RELIEF_ORDER = [
    ("Lifestyle (Books/Computer/Internet)",             "lifestyle"),
    ("Medical (Self/Spouse/Child)",                     "medical_self_spouse_child"),
    ("Medical Check-up / Mental Health",                "medical_checkup_mental"),
    ("Vaccination",                                     "medical_vaccination"),
    ("Dental Treatment",                                "medical_dental"),
    ("Life Insurance + EPF",                            "life_insurance_epf"),
    ("SOCSO / EIS",                                     "socso_eis"),
    ("Self Education Fees",                             "self_education"),
    ("Sports Equipment & Activities",                   "sports"),
    ("Education & Medical Insurance",                   "education_medical_insurance"),
    ("PRS / Deferred Annuity",                          "prs_annuity"),
    ("Parents / Grandparents Medical",                  "parents_medical"),
    ("Childcare / Kindergarten",                        "childcare_kindergarten"),
    ("SSPN Net Deposit",                                "sspn_net_deposit"),
    ("EV Charging / Food Waste Composter",              "ev_green"),
    ("Breastfeeding Equipment",                         "breastfeeding_equipment"),
    ("First Home Loan Interest",                        "first_home_loan_interest"),
    ("Child Below 18",                                  "child_below_18"),
    ("Child 18+ Pre-University",                        "child_18plus_pretertiary"),
    ("Child 18+ Tertiary (Diploma/Degree)",             "child_18plus_tertiary"),
    ("Child Learning Disability / Early Intervention",  "child_learning_disability"),
    ("Spouse / Alimony",                                "spouse_alimony"),
    ("Self / Individual Relief",                        "self_individual"),
    ("Disabled Individual",                             "disabled_individual"),
    ("Disabled Spouse",                                 "disabled_spouse"),
    ("Disabled Child",                                  "disabled_child"),
    ("Disabled Child 18+ Higher Education",             "disabled_child_higher_ed"),
    ("Basic Support Equipment (Disabled)",              "basic_support_equipment"),
]


def _cap_for(key: str) -> int:
    """RM cap for a relief key; tiered reliefs report their highest tier."""
    r = tc.PERSONAL_RELIEFS[key]
    cap = r.get("cap")
    if cap is None and r.get("tiers"):
        cap = max(t["relief"] for t in r["tiers"])
    return int(cap or 0)


# (display name, max claimable RM)   0 = varies / no fixed cap
RELIEF_CATEGORIES = [(name, _cap_for(key)) for name, key in _RELIEF_ORDER]
RELIEF_CATEGORIES.append(("Other Relief", 0))  # catch-all, no fixed cap

RELIEF_TYPES  = [name for name, _ in RELIEF_CATEGORIES]
RELIEF_LIMITS = {name: limit for name, limit in RELIEF_CATEGORIES}

# display name → tax_config relief key (for sub-cap / tier / note lookups)
RELIEF_KEY = {name: key for name, key in _RELIEF_ORDER}

# relief display names whose cap is shared INSIDE the RM10,000 medical umbrella
RELIEF_SUBCAP_PARENT = {
    name: tc.PERSONAL_RELIEFS[key]["sub_cap_of"]
    for name, key in _RELIEF_ORDER
    if tc.PERSONAL_RELIEFS[key].get("sub_cap_of")
}
# the umbrella relief's own display name (so the Summary can reference it)
MEDICAL_UMBRELLA = "Medical (Self/Spouse/Child)"

# Default catch-alls
DEFAULT_EXPENSE = "Other"
DEFAULT_RELIEF  = "Other Relief"


# ── Helpers ────────────────────────────────────────────────────────────
def folder_name(category: str) -> str:
    """Sanitize a category string into a safe Google Drive folder name."""
    name = category.replace("/", "-")
    name = " ".join(name.split())          # collapse whitespace
    return name.strip() or "Uncategorized"


def valid_category(receipt_type: str, category: str) -> str:
    """Force a category to an allowed value for its type (else catch-all)."""
    if receipt_type == TYPE_RELIEF:
        return category if category in RELIEF_TYPES else DEFAULT_RELIEF
    return category if category in EXPENSE_CATEGORIES else DEFAULT_EXPENSE


def form_b_box(category: str) -> str:
    """Form B Part-N box code for an expense category (default N24)."""
    return EXPENSE_FORM_B_BOX.get(category, "N24")


def form_b_box_label(box: str) -> str:
    """Human label for a Form B box code; CAPITAL = capital allowance."""
    if box == "CAPITAL":
        return "Capital allowance (not an N-box expense)"
    info = tc.FORM_B_EXPENSE_BOXES.get(box)
    return info["label"] if info else box


def relief_cap(category: str) -> int:
    """RM cap for a relief display name (0 = no fixed cap / catch-all)."""
    return RELIEF_LIMITS.get(category, 0)


def prompt_category_block() -> str:
    """Render the allowed-category lists for the DeepSeek system prompt."""
    exp = "\n".join(f"  - {c}" for c in EXPENSE_CATEGORIES)
    rel = "\n".join(f"  - {c}" for c in RELIEF_TYPES)
    return (
        f'If type is "Expense", "category" MUST be EXACTLY one of:\n{exp}\n\n'
        f'If type is "Relief", "category" MUST be EXACTLY one of:\n{rel}\n'
    )


if __name__ == "__main__":
    print(f"{ASSESSMENT_YEAR}: {len(EXPENSE_CATEGORIES)} expense categories, "
          f"{len(RELIEF_TYPES)} relief types (incl. catch-all).")
    print("Form B boxes used:", sorted(set(EXPENSE_FORM_B_BOX.values())))
    print("Medical sub-caps:", list(RELIEF_SUBCAP_PARENT))
