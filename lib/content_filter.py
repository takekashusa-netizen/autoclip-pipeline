"""
Real profanity filter for auto-generated YouTube titles and descriptions.

Applied uniformly to any word on the list — no exceptions carved out for any
specific term, including slurs. The goal is simply to keep auto-generated,
transcript-derived text from triggering YouTube's own content/monetization
flags on vulgar language.
"""
import re

_FILTERED_TERMS = [
    "fuck", "fucking", "fucked", "fucker",
    "shit", "shitty",
    "bitch",
    "asshole",
    "cunt",
    "dick",
    "piss",
    "bastard",
    "goddamn",
    "nigger", "nigga",
    "faggot", "fag",
    "retard", "retarded",
]

_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _FILTERED_TERMS) + r")\b",
    re.IGNORECASE,
)


def _censor_match(match: re.Match) -> str:
    word = match.group(0)
    if len(word) <= 2:
        return "*" * len(word)
    return word[0] + "*" * (len(word) - 2) + word[-1]


def clean_text(text: str) -> str:
    if not text:
        return text
    return _PATTERN.sub(_censor_match, text)
