from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Ticket:
    issue: str = ""
    subject: str = ""
    company: str = ""

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> "Ticket":
        normalized = {str(key).strip().lower(): value for key, value in row.items()}
        return cls(
            issue=str(normalized.get("issue") or ""),
            subject=str(normalized.get("subject") or ""),
            company=str(normalized.get("company") or ""),
        )

    @property
    def full_text(self) -> str:
        return " ".join(part for part in (self.subject, self.issue) if part).strip()


@dataclass
class SupportDoc:
    doc_id: str
    domain: str
    product_area: str
    title: str
    content: str
    response: str
    url: str | None = None
    keywords: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> "SupportDoc":
        return cls(
            doc_id=str(row["id"]),
            domain=str(row["domain"]),
            product_area=str(row["product_area"]),
            title=str(row["title"]),
            content=str(row["content"]),
            response=str(row["response"]),
            url=row.get("url") or None,
            keywords=list(row.get("keywords") or []),
        )

    @property
    def searchable_text(self) -> str:
        return " ".join([self.title, self.product_area, self.content, " ".join(self.keywords)])


@dataclass
class RetrievalHit:
    doc: SupportDoc
    score: float


@dataclass
class DecisionTrace:
    domain: str
    domain_reason: str
    threat_summary: str
    risk_level: str
    risk_reason: str
    urgency_level: str
    urgency_reason: str
    corpus_coverage: str
    decision_reason: str
    anomalies: list[str] = field(default_factory=list)
    matched_docs: list[str] = field(default_factory=list)

    def to_justification(self) -> str:
        anomalies = ", ".join(self.anomalies) if self.anomalies else "none"
        docs = ", ".join(self.matched_docs) if self.matched_docs else "none"
        return (
            f"Domain detected: {self.domain} ({self.domain_reason}). "
            f"Injection/threat signals: {self.threat_summary}. "
            f"Risk level: {self.risk_level} - {self.risk_reason}. "
            f"Urgency level: {self.urgency_level} - {self.urgency_reason}. "
            f"Corpus coverage: {self.corpus_coverage}; matched docs: {docs}. "
            f"Decision: {self.decision_reason}. "
            f"Anomalies: {anomalies}."
        )
