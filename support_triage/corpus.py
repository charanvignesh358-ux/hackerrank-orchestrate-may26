import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from .constants import PRODUCT_AREAS
from .models import RetrievalHit, SupportDoc
from .text import token_counts, tokenize


class CorpusIndex:
    """Small sparse TF-IDF index for support documents."""

    def __init__(self, docs: list[SupportDoc]) -> None:
        self.docs = docs
        self._doc_tokens = [token_counts(doc.searchable_text) for doc in docs]
        self._idf = self._build_idf(self._doc_tokens)
        self._doc_vectors = [self._tfidf(counts) for counts in self._doc_tokens]
        self._doc_norms = [self._norm(vector) for vector in self._doc_vectors]

    @classmethod
    def from_file(cls, path: str | Path) -> "CorpusIndex":
        path = Path(path)
        if path.is_dir():
            return cls(_docs_from_markdown_dir(path))
        with path.open("r", encoding="utf-8") as handle:
            raw_docs = json.load(handle)
        return cls([SupportDoc.from_mapping(row) for row in raw_docs])

    @staticmethod
    def _build_idf(doc_tokens: list[Counter]) -> dict[str, float]:
        doc_count = len(doc_tokens)
        frequency: dict[str, int] = defaultdict(int)
        for counts in doc_tokens:
            for token in counts:
                frequency[token] += 1
        return {
            token: math.log((doc_count + 1) / (count + 1)) + 1.0
            for token, count in frequency.items()
        }

    def _tfidf(self, counts: Counter) -> dict[str, float]:
        total = sum(counts.values()) or 1
        return {
            token: (count / total) * self._idf.get(token, 1.0)
            for token, count in counts.items()
        }

    @staticmethod
    def _norm(vector: dict[str, float]) -> float:
        return math.sqrt(sum(value * value for value in vector.values()))

    @staticmethod
    def _cosine(left: dict[str, float], left_norm: float, right: dict[str, float], right_norm: float) -> float:
        if not left_norm or not right_norm:
            return 0.0
        if len(left) > len(right):
            left, right = right, left
        dot = sum(value * right.get(token, 0.0) for token, value in left.items())
        return dot / (left_norm * right_norm)

    def search(
        self,
        query: str,
        domain: str | None = None,
        product_area: str | None = None,
        top_k: int = 3,
    ) -> list[RetrievalHit]:
        query_counts = token_counts(query)
        query_vector = self._tfidf(query_counts)
        query_norm = self._norm(query_vector)
        query_tokens = set(tokenize(query))
        hits: list[RetrievalHit] = []

        for idx, doc in enumerate(self.docs):
            if domain and doc.domain != domain:
                continue
            score = self._cosine(query_vector, query_norm, self._doc_vectors[idx], self._doc_norms[idx])
            keyword_overlap = query_tokens.intersection(tokenize(" ".join(doc.keywords)))
            if keyword_overlap:
                score += min(0.12, 0.025 * len(keyword_overlap))
            if product_area and doc.product_area == product_area:
                score += 0.18
            score = min(1.0, score)
            hits.append(RetrievalHit(doc=doc, score=score))

        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]


def _docs_from_markdown_dir(root: Path) -> list[SupportDoc]:
    docs: list[SupportDoc] = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in {".md", ".markdown", ".txt"} or not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not content:
            continue
        domain = _infer_domain(path)
        product_area = _infer_product_area(path, domain)
        cleaned_content = _strip_frontmatter(content)
        title = _infer_title(content, path)
        response = _first_sentences(cleaned_content)
        docs.append(
            SupportDoc(
                doc_id=_doc_id(root, path),
                domain=domain,
                product_area=product_area,
                title=title,
                content=cleaned_content,
                response=response,
                url=_extract_url(content),
                keywords=_keywords_from_path(path),
            )
        )
    if not docs:
        raise ValueError(f"No markdown or text support documents found under {root}")
    return docs


def _doc_id(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _infer_domain(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    if "hackerrank" in parts:
        return "HackerRank"
    if "claude" in parts or "anthropic" in parts:
        return "Claude"
    if "visa" in parts:
        return "Visa"
    return "General"


def _infer_product_area(path: Path, domain: str) -> str:
    allowed = set(PRODUCT_AREAS.get(domain, ())) | set(PRODUCT_AREAS["General"])
    candidates: list[str] = []
    for part in path.parts:
        slug = re.sub(r"[^a-z0-9]+", "_", part.lower()).strip("_")
        candidates.append(slug)
        candidates.append(slug.replace("_and_", "_"))
    for candidate in candidates:
        if candidate in allowed:
            return candidate
    if domain == "Visa":
        return "general_support"
    return "unknown"


def _infer_title(content: str, path: Path) -> str:
    metadata_title = _frontmatter_value(content, "title")
    if metadata_title:
        return metadata_title
    content = _strip_frontmatter(content)
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or path.stem
    return path.stem.replace("-", " ").replace("_", " ").strip() or path.name


def _first_sentences(content: str, max_chars: int = 500) -> str:
    cleaned = re.sub(r"#+\s*", "", content)
    cleaned = re.sub(r"_Last updated:[^_]+_", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    response = ""
    for sentence in sentences:
        if len(response) + len(sentence) + 1 > max_chars:
            break
        response = f"{response} {sentence}".strip()
    return response or cleaned[:max_chars].rstrip() + "..."


def _strip_frontmatter(content: str) -> str:
    return re.sub(r"\A---\s*\n.*?\n---\s*", "", content, count=1, flags=re.DOTALL).strip()


def _frontmatter_value(content: str, key: str) -> str | None:
    frontmatter = re.match(r"\A---\s*\n(.*?)\n---", content, flags=re.DOTALL)
    if not frontmatter:
        return None
    match = re.search(rf"(?m)^\s*{re.escape(key)}:\s*['\"]?([^'\"\r\n]+)", frontmatter.group(1))
    return match.group(1).strip() if match else None


def _extract_url(content: str) -> str | None:
    source_url = _frontmatter_value(content, "source_url")
    if source_url:
        return source_url
    match = re.search(r"\[(?:[^\]]+)\]\((https?://[^)]+)\)", content)
    return match.group(1) if match else None


def _keywords_from_path(path: Path) -> list[str]:
    words: list[str] = []
    for part in path.parts:
        words.extend(token for token in re.split(r"[^a-zA-Z0-9]+", part.lower()) if token)
    return words
