#!/usr/bin/env python3
"""
Single source of truth for Malaysian tax categories (YA 2025).

Imported by BOTH bot.py and setup_sheets.py so that:
  • Google Sheets dropdowns
  • DeepSeek classification
  • Google Drive folder names
  • Summary tab formulas
all use byte-for-byte identical strings. Edit categories HERE only.

Ordering = most commonly used  ->  least commonly used,
so the dropdowns and summary don't require scrolling for everyday items.
"""

# ── Receipt type labels ────────────────────────────────────────────────
TYPE_EXPENSE = "Expense"
TYPE_RELIEF  = "Relief"

# Drive top-level folder names (also the Google Sheet tab names)
EXPENSE_FOLDER = "Expenses"
RELIEF_FOLDER  = "Relief"


# ── Expense categories (most used → least used) ────────────────────────
# These are general bookkeeping buckets for everyday/business spending — NOT
# statutory tax-relief items. For a Form B (business income) filer they help
# organise records; deductibility follows ITA 1967 s.33/s.39 (e.g. client
# entertainment is generally 50% deductible, capital items are not expenses).
EXPENSE_CATEGORIES = [
    "Food & Beverage",
    "Transportation",
    "Groceries",
    "Communication",
    "Utilities",
    "Office Supplies",
    "Subscriptions",
    "Equipment & Software",
    "Entertainment",
    "Travel",
    "Professional Services",
    "Rent",
    "Other",
]


# ── Tax-relief categories (most used → least used) ─────────────────────
# (display name, max claimable RM)   0 = varies / no fixed cap
#
# SOURCE OF TRUTH — fact-checked line-by-line against the official LHDN
# "Tax Relief — Resident Individual, Year Assessment 2025" infographic,
# updated 19 January 2026:
#   https://www.hasil.gov.my/media/muob0jyz/tax-relief-ya-2025.pdf
#   https://www.hasil.gov.my/en/individual/individual-life-cycle/income-declaration/tax-reliefs/
# Applies to BOTH Form BE (employment) and Form B (business income) — the
# personal reliefs are identical; Form B just adds business sections.
# Every RM amount below was verified correct on 2026-06-09.
RELIEF_CATEGORIES = [
    ("Lifestyle (Books/Computer/Internet)",            2500),  # books, PC/phone/tablet, internet, self-dev courses
    ("Medical (Self/Spouse/Child)",                   10000),  # serious illness, fertility, vaccination, dental
    ("Life Insurance + EPF",                           7000),  # private: EPF≤4,000 + life≤3,000; pensioner: life≤7,000
    ("SOCSO / EIS",                                     350),  # PERKESO contributions (SOCSO + EIS combined)
    ("Self Education Fees",                             7000),  # tertiary; skills/self-dev courses sub-limited to 2,000
    ("Sports Equipment & Activities",                  1000),  # equipment, facility fees, competitions, gym
    ("Education & Medical Insurance",                  4000),  # self / spouse / child
    ("PRS / Deferred Annuity",                         3000),  # Private Retirement Scheme + deferred annuity
    ("Medical Check-up / Mental Health",               1000),  # SUB-LIMIT inside the 10,000 Medical cap
    ("Parents / Grandparents Medical",                 8000),  # medical/dental/care; full check-up sub-limit 1,000
    ("Childcare / Kindergarten",                       3000),  # TASKA/TADIKA, child ≤6, shared by spouses
    ("SSPN Net Deposit",                               8000),  # SSPN net savings, shared by spouses
    ("EV Charging / Food Waste Composter",             2500),  # EV charging equipment + composting machine (home use)
    ("Breastfeeding Equipment",                        1000),  # female taxpayer, child ≤2, once per 2 years
    ("First Home Loan Interest",                       7000),  # house ≤500k: 7,000; 500k–750k: 5,000 (SPA 2025–2027)
    ("Child Below 18",                                 2000),  # per unmarried child under 18
    ("Child 18+ in Education",                         8000),  # diploma+ (MY) / degree+ (overseas); else 2,000
    ("Spouse / Alimony",                               4000),  # spouse with no income / alimony paid
    ("Self / Individual Relief",                       9000),  # automatic: individual & dependent relatives
    ("Disabled Individual",                            7000),  # additional, OKU-certified self
    ("Disabled Spouse",                                6000),  # additional, disabled husband/wife
    ("Disabled Child",                                 8000),  # +8,000 more if 18+ in diploma+/degree+ study
    ("Basic Support Equipment (Disabled)",             6000),  # for disabled self/spouse/child/parent
    ("Child Disability Assessment / Early Intervention", 6000),  # SUB-LIMIT inside the 10,000 Medical cap (child ≤18)
    ("Other Relief",                                      0),  # catch-all (no fixed cap)
]

RELIEF_TYPES  = [name for name, _ in RELIEF_CATEGORIES]
RELIEF_LIMITS = {name: limit for name, limit in RELIEF_CATEGORIES}

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


def prompt_category_block() -> str:
    """Render the allowed-category lists for the DeepSeek system prompt."""
    exp = "\n".join(f"  - {c}" for c in EXPENSE_CATEGORIES)
    rel = "\n".join(f"  - {c}" for c in RELIEF_TYPES)
    return (
        f'If type is "Expense", "category" MUST be EXACTLY one of:\n{exp}\n\n'
        f'If type is "Relief", "category" MUST be EXACTLY one of:\n{rel}\n'
    )
