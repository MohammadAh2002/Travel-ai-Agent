from __future__ import annotations

import re


# Ordered: the first matching rule wins, so specific place types beat generic ones.
_CATEGORY_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"hammam|hamam|turkish bath|bathhouse", re.I), "Turkish bath (hammam)"),
    (re.compile(r"mosque|\bcami\b|masjid|mevlevihane|dervish", re.I), "mosque · Islamic site"),
    (re.compile(r"madrasa|medrese|islamic school", re.I), "madrasa · Islamic school"),
    (re.compile(r"türbe|turbe|mausoleum|tomb|shrine", re.I), "tomb / shrine"),
    (re.compile(r"castle|fortress|citadel|\bfort\b|keep\b", re.I), "castle / fortress"),
    (re.compile(r"museum|exhibit", re.I), "museum"),
    (re.compile(r"palace|saray|seraglio", re.I), "palace"),
    (re.compile(r"cistern", re.I), "underground cistern"),
    (re.compile(r"aqueduct", re.I), "ancient aqueduct"),
    (re.compile(r"amphitheat|\btheat(er|re)\b", re.I), "ancient theatre"),
    (re.compile(r"synagogue", re.I), "synagogue"),
    (re.compile(r"monastery|convent", re.I), "monastery"),
    (re.compile(r"church|cathedral|basilica|chapel", re.I), "church / historic basilica"),
    (re.compile(r"bazaar|market|souq|souk|cars[iı]|arasta", re.I), "market / bazaar"),
    (re.compile(r"gallery|galleries", re.I), "gallery / art venue"),
    (re.compile(r"tower|lookout|observation deck|viewpoint|panoram", re.I), "viewpoint / tower"),
    (re.compile(r"city walls|defensive walls|ramparts", re.I), "city walls"),
    (re.compile(r"hippodrome|obelisk|column of|monument", re.I), "historic monument"),
    (re.compile(r"aquarium|\bzoo\b|amusement|theme park|miniaturk|cable car|teleferik", re.I),
     "family attraction"),
    (re.compile(r"beach|island|seaside|coast", re.I), "beach / island"),
    (re.compile(r"\bpark\b|garden|botanic|grove|forest", re.I), "park / garden"),
    (re.compile(r"ruin|archaeolog|ancient|byzantine|ottoman|roman|umayyad|nabatae?an|medieval|"
                r"caravanserai|historic|heritage", re.I), "historic site"),
    (re.compile(r"\bart\b|contemporary|sculpture", re.I), "art venue"),
    (re.compile(r"square|plaza|promenade|avenue|street", re.I), "square / promenade"),
]

_TAG_LABELS = {
    "religious": "religious site",
    "museum": "museum",
    "history": "historic site",
    "views": "viewpoint",
    "markets": "market / shopping",
    "nature": "nature spot",
    "family": "family attraction",
    "art": "art venue",
    "architecture": "architectural landmark",
    "food": "food spot",
}

_KIND_LABELS = {
    "eat": "restaurant",
    "drink": "café / bar",
    "buy": "market / shopping",
    "do": "activity / experience",
    "see": "sight / attraction",
}

_WHITESPACE = re.compile(r"\s+")


def category_label(place: dict) -> str:
    """Human-readable 'what it is' for a sourced listing, e.g. 'mosque · Islamic site'."""
    kind = str(place.get("kind") or "")
    if kind in ("eat", "drink"):
        return _KIND_LABELS[kind]
    name = " ".join(str(place.get(key) or "") for key in ("name", "alt"))
    description = str(place.get("description") or "")
    for pattern, label in _CATEGORY_RULES:
        if pattern.search(name):
            return label
    for pattern, label in _CATEGORY_RULES:
        if pattern.search(description):
            return label
    for tag in place.get("tags") or []:
        if tag in _TAG_LABELS:
            return _TAG_LABELS[tag]
    return _KIND_LABELS.get(kind, "attraction" if kind else "")


def short_description(place: dict, limit: int = 200) -> str:
    """First sentence or two of the sourced listing text — what the place is and what you do there."""
    text = _WHITESPACE.sub(" ", str(place.get("description") or "")).strip()
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    blurb = ""
    for sentence in sentences:
        candidate = (blurb + " " + sentence).strip()
        if len(candidate) > limit and blurb:
            break
        blurb = candidate
        if len(blurb) >= limit // 2:
            break
    if len(blurb) > limit:
        blurb = blurb[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return blurb
