"""Versioned fictional Canadian business banking product schedule."""

import re

PRICING_VERSION = "C360-CAD-2026-01"
PRODUCTS = {
    "business account": {
        "name": "Business Operating Account",
        "terms": [
            "Monthly maintenance: CAD 12.00 per account, billed monthly.",
            "20 electronic transactions included per statement month; CAD 0.75 per additional transaction.",
            "Incoming domestic wire: CAD 15.00 each. Outgoing domestic wire: CAD 25.00 each.",
            "Cash deposits: CAD 2.50 per CAD 1,000 deposited, charged proportionately.",
            "Minimum opening deposit: CAD 0.00. Credit interest: 0.00% per year.",
        ],
    },
    "payments": {
        "name": "Business Payments",
        "terms": [
            "Monthly service fee: CAD 8.00, billed in addition to account maintenance.",
            "Outgoing electronic funds transfer: CAD 0.50 each, billed monthly.",
            "Returned electronic funds transfer: CAD 10.00 each.",
            "Requires an active Business Operating Account.",
        ],
    },
    "credit facility": {
        "name": "Business Line of Credit Request",
        "terms": [
            "Illustrative limit: CAD 25,000.00, subject to separate credit approval.",
            "Illustrative variable interest: demo prime rate of 5.00% plus 3.00 percentage points (8.00% per year at issue).",
            "Interest is calculated daily on the outstanding balance and billed monthly after activation.",
            "Illustrative annual facility fee: CAD 100.00 after activation.",
            "This agreement records the request only. No credit is extended and no credit fees accrue without separate approval and acceptance.",
        ],
    },
}
ALIASES = {
    "business operating account": "business account", "business bank account": "business account",
    "business chequing": "business account", "business checking": "business account",
    "business banking account": "business account", "business chequing account": "business account",
    "business checking account": "business account", "operating account": "business account",
    "business payments": "payments", "payment processing": "payments",
    "eft": "payments", "line of credit": "credit facility", "business line of credit": "credit facility",
}


def pricing_schedule(requested: str) -> dict:
    products = []
    unpriced = []
    for value in re.split(r",|;|\n|\s+and\s+", requested.casefold()):
        value = " ".join(value.strip(" .").split())
        if not value:
            continue
        key = ALIASES.get(value, value)
        if key not in PRODUCTS:
            unpriced.append(value)
        elif key not in products:
            products.append(key)
    if unpriced or not products:
        raise ValueError("Use supported product names: Business account, Payments, or Credit facility.")
    if ("payments" in products or "credit facility" in products) and "business account" not in products:
        raise ValueError("Include Business account when requesting Payments or a Credit facility.")
    return {"version": PRICING_VERSION, "currency": "CAD", "products": [PRODUCTS[key] for key in products]}


def render_schedule(schedule: dict) -> str:
    sections = [
        product["name"] + "\n" + "\n".join(f"- {term}" for term in product["terms"])
        for product in schedule["products"]
    ]
    return f"Pricing schedule: {schedule['version']} ({schedule['currency']})\n\n" + "\n\n".join(sections)
