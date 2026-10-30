from __future__ import annotations


def budget_summary(itinerary: dict) -> str:
    total = itinerary.get("estimated_total")
    budget = itinerary.get("budget_total")
    currency = itinerary.get("currency", "")
    if total is None:
        return "Listed costs are incomplete, so the total budget cannot be verified."
    if budget is None:
        return f"Known listed costs are about {total} {currency}; unpriced items are excluded."
    if total > budget:
        return (f"Known listed costs are about {total} {currency}, already over the {budget} {currency} budget; "
                "additional unpriced expenses may increase it.")
    return (f"Known listed costs are about {total} {currency} against your {budget} {currency} budget. "
            "Unpriced expenses are not included, so this is not a guarantee the full trip fits.")
