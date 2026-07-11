import re

UNSUPPORTED_DOMAIN_KEYWORDS = [
    "python", "javascript", "programming language", "source code", "software bug",
    "cryptocurrency", "bitcoin", "ethereum", "blockchain", "nft",
    "stock market", "stock price", "interest rate", "mortgage rate",
    "election", "president", "senate", "political party", "congress",
    "exoplanet", "galaxy", "telescope", "light-year", "solar system",
    "smartphone model", "operating system update", "wifi router",
]

SUPPORTED_DOMAIN_TOPICS = [
    "manascience", "neuroplasticity", "primitive reflex", "primitive reflexes",
    "sensory processing", "occupational therapy", "physical therapy",
    "developmental challenge", "developmental challenges", "learning challenge",
    "learning challenges", "practitioner", "course", "research", "family support",
    "therapy", "therapies",
]

BOUNDARY_REDIRECT_TEMPLATE = (
    "That's outside what I'm able to help with -- I'm focused on ManaScience "
    "topics like neuroplasticity, primitive reflexes, therapies, courses, and "
    "supporting families through developmental and learning challenges. If you "
    "have a question in any of those areas, I'd love to help with that instead."
)


def fails_domain_boundary(final_answer: str, topic: str) -> bool:
    """Boolean backstop signal only -- full vs partial handling (and the use of
    `topic`) is safety_service's job, not this validator's. A mixed-domain
    answer can have an in-domain topic while still containing off-domain
    keywords (e.g. a sensory-processing answer that drifts into stock-market
    advice), so `topic` must never suppress this scan."""
    lowered = final_answer.lower()
    # Word-boundary match so a keyword can't fire inside a larger word --
    # e.g. "election" must not match "practitioner selection"/"course selection".
    return any(
        re.search(r"\b" + re.escape(keyword) + r"\b", lowered)
        for keyword in UNSUPPORTED_DOMAIN_KEYWORDS
    )


def has_supported_domain_content(final_answer: str) -> bool:
    lowered = final_answer.lower()
    return any(keyword in lowered for keyword in SUPPORTED_DOMAIN_TOPICS)
