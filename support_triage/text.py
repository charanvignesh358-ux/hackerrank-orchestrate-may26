import html
import re
import unicodedata
from collections import Counter

from .constants import STOPWORDS


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.-]*")


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_text(text: str) -> str:
    text = html.unescape(strip_accents(text or "")).lower()
    text = re.sub(r"https?://", " ", text)
    text = re.sub(r"[^a-z0-9_.:/@+-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> list[str]:
    normalized = normalize_text(text)
    return [token for token in TOKEN_RE.findall(normalized) if token not in STOPWORDS]


def token_counts(text: str) -> Counter:
    return Counter(tokenize(text))


def contains_any(normalized_text: str, signals: set[str]) -> bool:
    return any(signal in normalized_text for signal in signals)


def matched_signals(normalized_text: str, signals: set[str]) -> list[str]:
    return sorted(signal for signal in signals if signal in normalized_text)


def compact_sentence(text: str, max_len: int = 180) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."
