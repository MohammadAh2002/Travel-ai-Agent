from __future__ import annotations

CITY_APPS = {
    "istanbul": ["Istanbulkart for transit", "BiTaksi or Uber for rides"],
    "amman": ["Uber or Careem for rides", "Check local bus routes before departure"],
    "paris": ["Île-de-France Mobilités for transit", "Check official taxi/rideshare availability"],
}


def make_checklist(destination: str | None, profile: dict, itinerary: dict | None = None) -> list[str]:
    city = (destination or "").lower()
    items = [
        "Download offline maps and save your hotel and key addresses.",
        "Install the local transit and ride app before you arrive; verify the official app in your app store.",
        "Keep digital and printed copies of tickets and important reservations.",
        "Check passport validity, entry requirements, travel insurance and any medication needs.",
        "Save emergency contacts and your accommodation details offline.",
        "Check weather again shortly before departure and pack for the forecast.",
    ]
    for key, suggestions in CITY_APPS.items():
        if key in city:
            items[1] = suggestions[0] + "; " + suggestions[1] + " (confirm current local availability)."
            break
    if profile.get("gift_heavy"):
        items.append("If you expect to bring home many gifts, compare checked-baggage weight limits and buy extra "
                     "allowance from your airline early; review seat selection and baggage rules before checkout.")
    children = profile.get("children_ages") or []
    if children:
        items.append("Check age limits, child tickets, family facilities and child-rest breaks for each activity.")
    if itinerary:
        items.append("Download or print attraction tickets and reservations; verify opening hours on official venue sites.")
    return items
