import json
import re
from dataclasses import dataclass
from pathlib import Path

from .constants import (
    ALWAYS_ESCALATE_SIGNALS,
    BUG_SIGNALS,
    DOMAIN_SIGNALS,
    DOMAINS,
    FEATURE_SIGNALS,
    GREETING_ONLY,
    HIGH_RISK_SIGNALS,
    HIGH_URGENCY_SIGNALS,
    INJECTION_REGEXES,
    INJECTION_SIGNALS,
    MALICIOUS_SIGNALS,
    MEDIUM_RISK_SIGNALS,
    OUT_OF_SCOPE_SIGNALS,
    PRODUCT_AREA_SIGNALS,
    REQUEST_TYPES,
    STATUSES,
)
from .corpus import CorpusIndex
from .models import DecisionTrace, RetrievalHit, Ticket
from .text import compact_sentence, contains_any, matched_signals, normalize_text, tokenize


FULL_COVERAGE_THRESHOLD = 0.22
PARTIAL_COVERAGE_THRESHOLD = 0.10


@dataclass
class ThreatResult:
    kind: str | None
    summary: str

    @property
    def is_blocking(self) -> bool:
        return self.kind in {"injection", "malicious"}


@dataclass
class SubIssueDecision:
    text: str
    status: str
    product_area: str
    response: str
    request_type: str
    trace: DecisionTrace
    risk_rank: int

    def to_output(self) -> dict[str, str]:
        if self.status not in STATUSES:
            raise ValueError(f"invalid status: {self.status}")
        if self.request_type not in REQUEST_TYPES:
            raise ValueError(f"invalid request_type: {self.request_type}")
        return {
            "status": self.status,
            "product_area": self.product_area,
            "response": self.response,
            "justification": self.trace.to_justification(),
            "request_type": self.request_type,
        }


class SupportTriageAgent:
    def __init__(self, corpus: CorpusIndex) -> None:
        self.corpus = corpus
        self.docs_by_id = {doc.doc_id: doc for doc in corpus.docs}

    @classmethod
    def from_corpus_file(cls, corpus_path: str | Path) -> "SupportTriageAgent":
        return cls(CorpusIndex.from_file(corpus_path))

    def triage(self, ticket: Ticket | dict[str, str]) -> dict[str, str]:
        if not isinstance(ticket, Ticket):
            ticket = Ticket.from_mapping(ticket)

        threat = self._detect_threat(ticket.full_text)
        if threat.is_blocking:
            return self._threat_response(ticket, threat)

        if threat.kind == "spam":
            return self._spam_response(ticket, threat)

        domain, domain_reason = self._detect_domain(ticket)
        if domain == "out_of_scope":
            normalized = normalize_text(ticket.full_text)
            if self._is_no_domain_failure(normalized):
                return self._no_domain_failure_response(ticket, threat)
            return self._out_of_scope_response(ticket, domain_reason, threat)

        sub_issues = self._split_sub_issues(ticket.full_text)
        if len(sub_issues) > 1:
            decisions = [self._decide_sub_issue(text, ticket, domain, domain_reason, threat) for text in sub_issues]
            return self._merge_multi_request(decisions)

        return self._decide_sub_issue(ticket.full_text, ticket, domain, domain_reason, threat).to_output()

    def triage_with_metadata(self, ticket: Ticket | dict[str, str]) -> dict[str, object]:
        if not isinstance(ticket, Ticket):
            ticket = Ticket.from_mapping(ticket)
        result = self.triage(ticket)
        return {
            "ticket": {
                "issue": ticket.issue,
                "subject": ticket.subject,
                "company": ticket.company,
            },
            "result": result,
            "meta": self._metadata_from_result(result),
            "draft_response": result["response"],
        }

    def triage_many_with_metadata(self, tickets: list[Ticket | dict[str, str]]) -> list[dict[str, object]]:
        return [self.triage_with_metadata(ticket) for ticket in tickets]

    def _detect_threat(self, text: str) -> ThreatResult:
        normalized = normalize_text(text)
        if not normalized:
            return ThreatResult(kind="spam", summary="spam/gibberish detected: empty ticket")

        for regex in INJECTION_REGEXES:
            if re.search(regex, normalized):
                return ThreatResult(kind="injection", summary=f"injection signal detected: {regex}")

        injection_hits = matched_signals(normalized, INJECTION_SIGNALS)
        if injection_hits:
            return ThreatResult(kind="injection", summary=f"injection signal detected: {', '.join(injection_hits[:3])}")

        malicious_hits = matched_signals(normalized, MALICIOUS_SIGNALS)
        if malicious_hits:
            return ThreatResult(kind="malicious", summary=f"malicious intent detected: {', '.join(malicious_hits[:3])}")

        tokens = tokenize(normalized)
        if normalized in GREETING_ONLY or " ".join(tokens) in GREETING_ONLY:
            return ThreatResult(kind="spam", summary="spam/gibberish detected: greeting or thanks only")

        if len(tokens) <= 1 and len(normalized) < 16:
            return ThreatResult(kind="spam", summary="spam/gibberish detected: no coherent support intent")

        alnum = sum(char.isalnum() for char in normalized)
        if len(normalized) >= 12 and (alnum / max(len(normalized), 1)) < 0.35:
            return ThreatResult(kind="spam", summary="spam/gibberish detected: mostly non-alphanumeric text")

        if contains_any(normalized, OUT_OF_SCOPE_SIGNALS):
            return ThreatResult(kind="out_of_scope", summary="out-of-scope general knowledge signal detected")

        return ThreatResult(kind=None, summary="none")

    def _threat_response(self, ticket: Ticket, threat: ThreatResult) -> dict[str, str]:
        domain, domain_reason = self._detect_domain(ticket)
        trace = DecisionTrace(
            domain=domain,
            domain_reason=domain_reason,
            threat_summary=threat.summary,
            risk_level="HIGH",
            risk_reason="ticket contained injection or malicious control intent",
            urgency_level="LOW",
            urgency_reason="urgency not evaluated after threat filter",
            corpus_coverage="not evaluated because Stage 1 stopped processing",
            decision_reason="escalated by Stage 1 threat and injection filter",
            anomalies=["processing stopped before domain-specific handling"],
        )
        return self._validated_output(
            status="escalated",
            product_area="unknown",
            response="I'm unable to process this request.",
            justification=trace.to_justification(),
            request_type="invalid",
        )

    def _spam_response(self, ticket: Ticket, threat: ThreatResult) -> dict[str, str]:
        domain, domain_reason = self._detect_domain(ticket)
        trace = DecisionTrace(
            domain=domain,
            domain_reason=domain_reason,
            threat_summary=threat.summary,
            risk_level="LOW",
            risk_reason="no coherent support intent was present",
            urgency_level="LOW",
            urgency_reason="no time pressure stated",
            corpus_coverage="not needed for greeting or gibberish handling",
            decision_reason="replied directly because Stage 1 marks spam/gibberish as invalid but harmless",
            anomalies=["vague ticket"],
        )
        return self._validated_output(
            status="replied",
            product_area="unknown",
            response="Happy to help - please let me know if you have a support question.",
            justification=trace.to_justification(),
            request_type="invalid",
        )

    def _out_of_scope_response(self, ticket: Ticket, domain_reason: str, threat: ThreatResult) -> dict[str, str]:
        trace = DecisionTrace(
            domain="out_of_scope",
            domain_reason=domain_reason,
            threat_summary=threat.summary,
            risk_level="LOW",
            risk_reason="harmless question outside the supported domains",
            urgency_level="LOW",
            urgency_reason="no support urgency in supported domains",
            corpus_coverage="not covered because the request is outside HackerRank, Claude, and Visa India",
            decision_reason="replied directly by Stage 5 out-of-scope harmless rule",
            anomalies=["out-of-scope request"],
        )
        return self._validated_output(
            status="replied",
            product_area="out_of_scope",
            response="I'm sorry, this falls outside the scope of what I can help with here.",
            justification=trace.to_justification(),
            request_type="invalid",
        )

    def _no_domain_failure_response(self, ticket: Ticket, threat: ThreatResult) -> dict[str, str]:
        normalized = normalize_text(ticket.full_text)
        request_type = "bug" if "site is down" in normalized else "product_issue"
        trace = DecisionTrace(
            domain="out_of_scope",
            domain_reason="no company field and failure language has no supported-domain context",
            threat_summary=threat.summary,
            risk_level="MEDIUM",
            risk_reason="failure report cannot be safely routed without a domain",
            urgency_level="HIGH" if "site is down" in normalized else "MEDIUM",
            urgency_reason="site outage language is present" if "site is down" in normalized else "vague failure language is present",
            corpus_coverage="not covered because no supported domain could be inferred",
            decision_reason=(
                "escalated by Stage 5 edge-case rule: site is down with no company context"
                if request_type == "bug"
                else "escalated by Stage 5 edge-case rule: vague failure with no company context"
            ),
            anomalies=["vague ticket", "no company context"],
        )
        return self._validated_output(
            status="escalated",
            product_area="unknown",
            response=self._escalation_message("unknown", self._display_issue(ticket.full_text, ticket)),
            justification=trace.to_justification(),
            request_type=request_type,
        )

    def _detect_domain(self, ticket: Ticket) -> tuple[str, str]:
        company = normalize_text(ticket.company)
        direct = {
            "hackerrank": "HackerRank",
            "hacker rank": "HackerRank",
            "claude": "Claude",
            "anthropic": "Claude",
            "visa": "Visa",
            "visa india": "Visa",
        }
        if company in direct:
            return direct[company], f"from company field: {ticket.company}"

        normalized = normalize_text(ticket.full_text)
        scores: dict[str, int] = {}
        for domain, signals in DOMAIN_SIGNALS.items():
            scores[domain] = sum(1 for signal in signals if signal in normalized)

        best_domain = max(scores, key=scores.get)
        best_score = scores[best_domain]
        tied = [domain for domain, score in scores.items() if score == best_score and score > 0]
        if best_score == 0:
            return "out_of_scope", "no company field and no supported-domain keywords"
        if len(tied) > 1:
            return "cross_domain", f"multiple supported domains inferred from keywords: {', '.join(tied)}"
        return best_domain, f"inferred from {best_domain} keywords in ticket text"

    def _split_sub_issues(self, text: str) -> list[str]:
        if not text.strip():
            return [text]
        normalized = normalize_text(text)
        if "inactivity" in normalized and any(signal in normalized for signal in ("candidate", "interviewer", "interview")):
            return [text]
        has_multiple_questions = text.count("?") > 1
        has_joiners = bool(
            re.search(r"\b(and also|another thing|additionally|furthermore)\b", normalized)
            or re.search(r"(?<=[.!?;])\s+also\b", text, flags=re.IGNORECASE)
        )
        has_numbered = bool(re.search(r"(^|\s)(1\.|1\)|2\.|2\))", text))
        if not (has_multiple_questions or has_joiners or has_numbered):
            return [text]

        chunks = re.split(
            r"(?:\?+\s+(?:also\s+)?|(?<=[.!?;])\s+also\s+|\b(?:and also|another thing|additionally|furthermore)\b|(?:^|\s)\d+[\.)]\s*)",
            text,
            flags=re.IGNORECASE,
        )
        issues = [chunk.strip(" .?;\n\t") for chunk in chunks if chunk and chunk.strip(" .?;\n\t")]
        return issues if len(issues) > 1 else [text]

    def _decide_sub_issue(
        self,
        text: str,
        ticket: Ticket,
        domain: str,
        domain_reason: str,
        threat: ThreatResult,
    ) -> SubIssueDecision:
        normalized = normalize_text(text)
        product_area = self._classify_product_area(normalized, domain)
        request_type = self._classify_request_type(normalized, domain)
        risk_level, risk_reason = self._score_risk(normalized, domain)
        urgency_level, urgency_reason = self._score_urgency(normalized, domain)
        escalation_reason = self._mandatory_escalation_reason(normalized, domain, ticket)
        hits = self._retrieve(text, domain, product_area)
        corpus_coverage = self._coverage(hits)
        if domain == "HackerRank" and self._is_hackerrank_user_removal_how_to(normalized):
            hits = self._retrieve("user management remove user deactivate user interviewer employee HackerRank", domain, "account_management")
            corpus_coverage = self._coverage(hits)
        elif domain == "HackerRank" and self._is_hackerrank_inactivity_timeout_question(normalized):
            hits = self._retrieve("session inactivity timeout company admin settings compliance security", domain, "interview")
            corpus_coverage = self._coverage(hits)
        elif domain == "Visa" and self._is_visa_dispute_how_to(normalized):
            hits = self._retrieve("file inquiry report purchase issue Visa card charge dispute", domain, "general_support")
            corpus_coverage = self._coverage(hits)
        elif domain == "Visa" and self._is_visa_urgent_cash_how_to(normalized):
            hits = self._retrieve("global ATM locator access cash Visa card", domain, "atm_and_cash")
            corpus_coverage = self._coverage(hits)
        elif domain == "Visa" and self._is_visa_minimum_spend_question(normalized):
            policy_doc = self.docs_by_id.get("visa/support.md")
            if policy_doc:
                hits = [RetrievalHit(doc=policy_doc, score=1.0)]
                corpus_coverage = "fully covered"

        anomalies: list[str] = []
        if domain == "cross_domain":
            anomalies.append("cross-domain signals")
        if domain == "out_of_scope":
            anomalies.append("no supported domain inferred")
        if not text.strip():
            anomalies.append("empty sub-issue")
        if threat.kind == "out_of_scope":
            anomalies.append("out-of-scope signal")

        if domain == "cross_domain":
            status = "escalated"
            response = self._escalation_message(product_area, self._display_issue(text, ticket))
            decision_reason = "escalated by Stage 5 because cross-domain ambiguity could cause unsafe routing"
        elif domain == "out_of_scope":
            status = "replied"
            product_area = "out_of_scope"
            request_type = "invalid"
            response = "I'm sorry, this falls outside the scope of what I can help with here."
            decision_reason = "replied directly by Stage 5 out-of-scope harmless rule"
        elif escalation_reason:
            status = "escalated"
            response = self._escalation_message(product_area, self._display_issue(text, ticket))
            decision_reason = f"escalated by Stage 5 rule: {escalation_reason}"
        elif risk_level == "HIGH" or urgency_level == "HIGH":
            status = "escalated"
            response = self._escalation_message(product_area, self._display_issue(text, ticket))
            decision_reason = "escalated by Stage 5 because risk or urgency is HIGH"
        elif domain == "HackerRank" and self._is_hackerrank_user_removal_how_to(normalized) and corpus_coverage != "not covered":
            status = "replied"
            response = self._hackerrank_user_removal_response(hits)
            decision_reason = "replied directly with corpus-backed HackerRank user management guidance"
        elif domain == "HackerRank" and self._is_hackerrank_inactivity_timeout_question(normalized) and corpus_coverage != "not covered":
            status = "replied"
            response = self._hackerrank_inactivity_timeout_response(hits)
            decision_reason = "replied directly with corpus-backed inactivity timeout guidance"
        elif domain == "Visa" and self._is_visa_dispute_how_to(normalized) and corpus_coverage != "not covered":
            status = "replied"
            response = self._visa_dispute_response(hits)
            decision_reason = "replied directly with corpus-backed Visa dispute guidance"
        elif domain == "Visa" and self._is_visa_urgent_cash_how_to(normalized) and corpus_coverage != "not covered":
            status = "replied"
            response = self._visa_urgent_cash_response(hits)
            decision_reason = "replied directly with corpus-backed Visa urgent-cash guidance"
        elif domain == "Visa" and self._is_visa_minimum_spend_question(normalized) and corpus_coverage != "not covered":
            status = "replied"
            response = self._visa_minimum_spend_response(hits)
            decision_reason = "replied directly with corpus-backed Visa minimum-spend guidance"
        elif corpus_coverage == "fully covered":
            status = "replied"
            response = self._grounded_response(hits)
            decision_reason = "replied directly because the corpus fully covers the support question"
        elif request_type == "feature_request":
            feature_hits = self._retrieve("feature request product feedback", domain, "feature_request")
            if self._coverage(feature_hits) != "not covered":
                status = "replied"
                response = self._grounded_response(feature_hits)
                corpus_coverage = self._coverage(feature_hits)
                hits = feature_hits
                decision_reason = "replied directly by Stage 5 feature request rule with corpus-backed acknowledgement"
            else:
                status = "escalated"
                response = self._escalation_message(product_area, self._display_issue(text, ticket))
                decision_reason = "escalated because the corpus does not cover feature request handling"
        else:
            status = "escalated"
            response = self._escalation_message(product_area, self._display_issue(text, ticket))
            decision_reason = "escalated by Stage 5 because corpus coverage was insufficient"

        trace = DecisionTrace(
            domain=domain,
            domain_reason=domain_reason,
            threat_summary=threat.summary,
            risk_level=risk_level,
            risk_reason=risk_reason,
            urgency_level=urgency_level,
            urgency_reason=urgency_reason,
            corpus_coverage=corpus_coverage,
            decision_reason=decision_reason,
            anomalies=anomalies,
            matched_docs=[f"{hit.doc.doc_id} ({hit.score:.3f})" for hit in hits if hit.score >= PARTIAL_COVERAGE_THRESHOLD],
        )
        return SubIssueDecision(
            text=text,
            status=status,
            product_area=product_area,
            response=response,
            request_type=request_type,
            trace=trace,
            risk_rank=self._risk_rank(risk_level, urgency_level),
        )

    def _classify_product_area(self, normalized_text: str, domain: str) -> str:
        if domain not in PRODUCT_AREA_SIGNALS:
            return domain if domain in {"cross_domain", "out_of_scope"} else "unknown"

        if domain == "HackerRank":
            if "certificate" in normalized_text:
                return "candidate_experience"
            if any(signal in normalized_text for signal in ("remove interviewer", "remove an interviewer", "remove employee", "remove an employee", "delete user")):
                return "account_management"
            if any(signal in normalized_text for signal in ("score dispute", "unfair grading", "review my answer", "override result", "result override")):
                return "candidate_experience"
            if "mock interview" in normalized_text:
                return "mock_interviews"
            if any(signal in normalized_text for signal in ("cs_live_", "order id", "payment", "refund")):
                return "billing_and_plans"
            if any(signal in normalized_text for signal in ("infosec", "questionnaire")):
                return "account_management"
            if any(signal in normalized_text for signal in ("apply tab", "submissions", "across any challenges")):
                return "screen"
            if any(signal in normalized_text for signal in ("zoom", "compatible check", "compatibility")):
                return "proctoring"
            if any(signal in normalized_text for signal in ("reschedule assessment", "rescheduling assessment")):
                return "assessment_access"
            if "inactivity timeout" in normalized_text:
                return "interview"
            if "pause subscription" in normalized_text or "cancel subscription" in normalized_text:
                return "subscription_management"
            if "resume builder" in normalized_text:
                return "resume_builder"

        if domain == "Claude":
            if any(signal in normalized_text for signal in ("all requests are failing", "all requests failing", "stopped working completely", "completely down")):
                return "model_behavior"
            if any(signal in normalized_text for signal in ("seat removed", "not the admin", "not the owner", "restore my access")):
                return "account_access"
            if any(signal in normalized_text for signal in ("security vulnerability", "bug bounty", "vulnerability")):
                return "safety_and_policy"
            if any(signal in normalized_text for signal in ("all requests failing", "completely down", "all requests failed")):
                return "model_behavior"
            if any(signal in normalized_text for signal in ("bedrock", "aws")):
                return "third_party_integration"
            if any(signal in normalized_text for signal in ("lti", "canvas")):
                return "lti_integration"
            if any(signal in normalized_text for signal in ("web crawling", "crawling my website", "claudebot", "robots.txt", "robots txt")):
                return "web_crawling"
            if any(signal in normalized_text for signal in ("data retention", "data training", "model training", "improve the model", "improve the models")):
                return "data_retention"
            if "how long" in normalized_text and "data" in normalized_text:
                return "data_retention"

        if domain == "Visa":
            if any(signal in normalized_text for signal in ("identity theft", "identity stolen", "stolen identity")):
                return "identity_theft"
            if any(signal in normalized_text for signal in ("minimum spend", "minimum transaction", "minimum $10", "us virgin islands")):
                return "minimum_spend_policy"
            if any(signal in normalized_text for signal in ("urgent cash", "atm", "cash advance")):
                return "atm_and_cash"
            if any(signal in normalized_text for signal in ("blocked during travel", "voyage", "abroad")):
                return "travel_support"
            if any(signal in normalized_text for signal in ("fraud", "suspicious", "unauthorized", "dispute", "chargeback", "wrong product", "refund demand")):
                return "fraud_and_disputes"

        scores: dict[str, int] = {}
        for area, signals in PRODUCT_AREA_SIGNALS[domain].items():
            scores[area] = sum(1 for signal in signals if signal in normalized_text)

        best_area = max(scores, key=scores.get)
        if scores[best_area] == 0:
            return "general_support" if domain == "Visa" else "unknown"
        return best_area

    def _classify_request_type(self, normalized_text: str, domain: str) -> str:
        if not normalized_text or domain == "out_of_scope":
            return "invalid"
        if domain == "HackerRank" and any(signal in normalized_text for signal in ("payment", "order id", "cs_live_", "refund", "subscription")):
            return "product_issue"
        if domain == "Claude" and any(signal in normalized_text for signal in ("bedrock", "aws bedrock", "third party")):
            return "product_issue"
        if contains_any(normalized_text, FEATURE_SIGNALS):
            return "feature_request"
        if contains_any(normalized_text, BUG_SIGNALS):
            return "bug"
        if domain in DOMAINS:
            return "product_issue"
        return "invalid"

    def _score_risk(self, normalized_text: str, domain: str) -> tuple[str, str]:
        if domain == "Visa" and self._is_visa_dispute_how_to(normalized_text):
            return "LOW", "standard Visa dispute how-to question covered by corpus"
        if domain == "Claude" and self._is_claude_workspace_access_restore(normalized_text):
            return "HIGH", "Claude workspace access restoration requires authorized admin or owner review"
        if self._is_refund_information_request(normalized_text):
            return "MEDIUM", "informational refund question with billing sensitivity"
        high_hits = matched_signals(normalized_text, HIGH_RISK_SIGNALS)
        if high_hits:
            return "HIGH", f"matched high-risk signals: {', '.join(high_hits[:3])}"
        if domain == "Visa" and any(signal in normalized_text for signal in ("blocked", "stolen", "suspicious")):
            return "HIGH", "Visa card blocking, stolen-card, or suspicious-transaction context"
        medium_hits = matched_signals(normalized_text, MEDIUM_RISK_SIGNALS)
        if medium_hits:
            return "MEDIUM", f"matched medium-risk signals: {', '.join(medium_hits[:3])}"
        return "LOW", "standard FAQ or product question with no sensitive indicators"

    def _score_urgency(self, normalized_text: str, domain: str) -> tuple[str, str]:
        if domain == "Visa" and self._is_visa_urgent_cash_how_to(normalized_text):
            return "LOW", "standard Visa urgent-cash support question covered by corpus"
        high_hits = matched_signals(normalized_text, HIGH_URGENCY_SIGNALS)
        if high_hits:
            return "HIGH", f"matched high-urgency signals: {', '.join(high_hits[:3])}"
        if domain == "HackerRank" and "blocked" in normalized_text and "assessment" in normalized_text:
            return "HIGH", "candidate appears blocked during an assessment"
        if domain == "Visa" and any(word in normalized_text for word in ("blocked", "bloquee", "bloque")) and any(
            word in normalized_text for word in ("travel", "voyage", "abroad")
        ):
            return "HIGH", "card appears blocked during active travel"
        if any(word in normalized_text for word in ("deadline", "renewal", "today", "urgent")):
            return "MEDIUM", "deadline or urgency language is present"
        return "LOW", "no time pressure stated"

    def _mandatory_escalation_reason(self, normalized_text: str, domain: str, ticket: Ticket) -> str | None:
        if domain == "Visa" and self._is_visa_dispute_how_to(normalized_text):
            return None
        if domain == "Claude" and self._is_claude_workspace_access_restore(normalized_text):
            return "workspace access restoration requires authorized admin or owner review"
        if domain == "Claude" and any(signal in normalized_text for signal in ("bedrock", "aws bedrock")):
            return "AWS Bedrock and third-party integration failures require external support review"
        if domain == "Claude" and any(signal in normalized_text for signal in ("all requests are failing", "all requests failing", "stopped working completely", "completely down")):
            return "Claude system-wide failure report"
        if domain == "HackerRank" and "infosec" in normalized_text and any(signal in normalized_text for signal in ("form", "questionnaire", "process")):
            return "infosec questionnaire or form requires human review"
        if domain == "HackerRank" and self._is_hackerrank_apply_tab_bug(normalized_text):
            return "apply tab visibility bug requires support review"
        if domain == "HackerRank" and all(signal in normalized_text for signal in ("submissions", "challenges")) and any(
            signal in normalized_text for signal in ("none", "all", "system-wide", "not working")
        ):
            return "system-wide submissions outage"
        if domain == "HackerRank" and "resume builder" in normalized_text and any(signal in normalized_text for signal in ("down", "not working", "broken")):
            return "resume builder bug is not safely covered by corpus"
        always_escalate_signals = ALWAYS_ESCALATE_SIGNALS
        if self._is_refund_information_request(normalized_text):
            always_escalate_signals = ALWAYS_ESCALATE_SIGNALS - {"refund"}
        if contains_any(normalized_text, always_escalate_signals):
            return "ticket matched an always-escalate keyword"
        if domain == "HackerRank" and "live test" in normalized_text and "blocked" in normalized_text:
            return "candidate blocked mid-assessment with a live test in progress"
        if "site is down" in normalized_text and not normalize_text(ticket.company):
            return "site is down with no company context"
        if "not working" in normalized_text and domain == "out_of_scope":
            return "vague failure with no company context"
        return None

    @staticmethod
    def _is_no_domain_failure(normalized_text: str) -> bool:
        return "site is down" in normalized_text or "not working" in normalized_text or "its not working" in normalized_text

    @staticmethod
    def _is_visa_dispute_how_to(normalized_text: str) -> bool:
        return "dispute" in normalized_text and any(signal in normalized_text for signal in ("how", "how do", "how can", "what should"))

    @staticmethod
    def _is_visa_urgent_cash_how_to(normalized_text: str) -> bool:
        return "urgent cash" in normalized_text or ("cash" in normalized_text and "visa card" in normalized_text)

    @staticmethod
    def _is_visa_minimum_spend_question(normalized_text: str) -> bool:
        return any(signal in normalized_text for signal in ("minimum spend", "minimum transaction", "minimum 10", "minimum $10"))

    @staticmethod
    def _is_hackerrank_user_removal_how_to(normalized_text: str) -> bool:
        has_removal = any(
            signal in normalized_text
            for signal in (
                "remove interviewer",
                "remove an interviewer",
                "remove employee",
                "remove an employee",
                "remove them",
                "remove user",
                "deactivate user",
            )
        )
        has_account_context = any(signal in normalized_text for signal in ("workspace", "account", "platform", "hiring"))
        return has_removal and has_account_context

    @staticmethod
    def _is_hackerrank_inactivity_timeout_question(normalized_text: str) -> bool:
        return (
            "inactivity timeout" in normalized_text
            or "inactive session" in normalized_text
            or ("inactivity" in normalized_text and any(signal in normalized_text for signal in ("candidate", "interviewer", "interview")))
        )

    @staticmethod
    def _is_hackerrank_apply_tab_bug(normalized_text: str) -> bool:
        if "apply tab" not in normalized_text:
            return False
        return any(
            signal in normalized_text
            for signal in (
                "cannot see",
                "can not see",
                "can't see",
                "cant see",
                "can not able to see",
                "not able to see",
                "missing",
                "not working",
            )
        )

    @staticmethod
    def _is_claude_workspace_access_restore(normalized_text: str) -> bool:
        has_access_restore = any(
            signal in normalized_text
            for signal in (
                "restore my access",
                "access restored",
                "lost access",
                "removed my seat",
                "seat was removed",
                "seat removed",
            )
        )
        lacks_authority = any(
            signal in normalized_text
            for signal in (
                "not the admin",
                "not an admin",
                "not the owner",
                "not owner",
                "not the workspace owner",
                "not workspace owner",
            )
        )
        return has_access_restore and lacks_authority

    @staticmethod
    def _is_refund_information_request(normalized_text: str) -> bool:
        if "refund" not in normalized_text:
            return False
        if any(signal in normalized_text for signal in ("demand", "charged incorrectly", "unauthorized", "wrong product", "ban the merchant")):
            return False
        return any(
            signal in normalized_text
            for signal in (
                "how do",
                "how can",
                "what is",
                "what are",
                "where can",
                "refund policy",
                "refund status",
                "request a refund",
            )
        )

    def _retrieve(self, text: str, domain: str, product_area: str) -> list[RetrievalHit]:
        if domain not in DOMAINS:
            return []
        return self.corpus.search(text, domain=domain, product_area=product_area, top_k=3)

    def _coverage(self, hits: list[RetrievalHit]) -> str:
        if not hits or hits[0].score < PARTIAL_COVERAGE_THRESHOLD:
            return "not covered"
        if hits[0].score >= FULL_COVERAGE_THRESHOLD:
            return "fully covered"
        return "partially covered"

    def _grounded_response(self, hits: list[RetrievalHit]) -> str:
        primary = hits[0].doc
        response = primary.response.strip()
        if primary.url and primary.url not in response:
            response = f"{response} Reference: {primary.url}"
        return response

    def _hackerrank_user_removal_response(self, hits: list[RetrievalHit]) -> str:
        return (
            "HackerRank's Team Management/User Management guidance says admins can open the Admin Panel, go to User Management, "
            "locate the user, choose the ellipsis next to the user's name, select Deactivate User, and confirm."
            f"{self._reference_suffix(hits)}"
        )

    def _hackerrank_inactivity_timeout_response(self, hits: list[RetrievalHit]) -> str:
        return (
            "HackerRank's account security guidance says Company Admins can configure a session inactivity timeout "
            "under Settings > Compliance & Security > Timeout for Inactive Sessions. The configurable range is "
            "30 minutes to 24 hours, and the default is 24 hours if no custom limit is set."
            f"{self._reference_suffix(hits)}"
        )

    def _visa_dispute_response(self, hits: list[RetrievalHit]) -> str:
        return (
            "Visa's support guidance provides an online purchase-issue form for problems using a Visa card. "
            "Use that purchase-issue or inquiry flow for a charge issue."
            f"{self._reference_suffix(hits)}"
        )

    def _visa_urgent_cash_response(self, hits: list[RetrievalHit]) -> str:
        return (
            "Visa travel support lists a Global ATM locator for accessing cash and links to Visa ATMs. "
            "Use the locator to find a Visa ATM, and do not share your PIN or full card details in the ticket."
            f"{self._reference_suffix(hits)}"
        )

    def _visa_minimum_spend_response(self, hits: list[RetrievalHit]) -> str:
        return (
            "Visa support says merchants generally cannot set a minimum or maximum Visa transaction amount. "
            "An exception applies in the USA and US territories, including the U.S. Virgin Islands: for credit cards, "
            "a merchant may require a minimum transaction amount of up to US$10. If a debit-card minimum is imposed, "
            "or a credit-card minimum is greater than US$10, notify your Visa card issuer."
            f"{self._reference_suffix(hits)}"
        )

    @staticmethod
    def _reference_suffix(hits: list[RetrievalHit]) -> str:
        if hits and hits[0].doc.url:
            return f" Reference: {hits[0].doc.url}"
        return ""

    def _escalation_message(self, product_area: str, text: str) -> str:
        team = self._team_for_area(product_area)
        issue = compact_sentence(text, 140).strip().rstrip(".")
        if issue:
            return f"We have escalated your ticket to our {team} team and they will follow up with you shortly. We noted that your issue is about {issue}."
        return f"We have escalated your ticket to our {team} team and they will follow up with you shortly."

    @staticmethod
    def _display_issue(text: str, ticket: Ticket) -> str:
        subject = (ticket.subject or "").strip()
        issue = (ticket.issue or "").strip()
        raw = (text or "").strip()
        if issue and (raw == ticket.full_text or raw.startswith(subject)):
            return issue
        return raw

    @staticmethod
    def _team_for_area(product_area: str) -> str:
        if product_area in {"fraud_and_disputes", "identity_theft", "account_security"}:
            return "fraud and security"
        if product_area in {"privacy", "data_retention", "safety_and_policy"}:
            return "privacy and safety"
        if product_area in {"subscription_and_billing", "billing_and_plans", "subscription_management"}:
            return "billing"
        if product_area in {"third_party_integration", "api_integration", "lti_integration"}:
            return "technical support"
        return "support"

    @staticmethod
    def _risk_rank(risk_level: str, urgency_level: str) -> int:
        levels = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        return max(levels.get(risk_level, 0), levels.get(urgency_level, 0))

    def _merge_multi_request(self, decisions: list[SubIssueDecision]) -> dict[str, str]:
        primary = max(enumerate(decisions), key=lambda item: (item[1].risk_rank, item[0] == 0))[1]
        status = "escalated" if any(decision.status == "escalated" for decision in decisions) else "replied"
        response = " ".join(
            f"{idx}. {decision.response}" for idx, decision in enumerate(decisions, start=1)
        )
        traces = [decision.trace for decision in decisions]
        merged_trace = DecisionTrace(
            domain=primary.trace.domain,
            domain_reason=primary.trace.domain_reason,
            threat_summary=primary.trace.threat_summary,
            risk_level=primary.trace.risk_level,
            risk_reason=primary.trace.risk_reason,
            urgency_level=primary.trace.urgency_level,
            urgency_reason=primary.trace.urgency_reason,
            corpus_coverage="; ".join(f"request {idx}: {trace.corpus_coverage}" for idx, trace in enumerate(traces, 1)),
            decision_reason=(
                "multi-request handling: escalated because at least one sub-issue required escalation"
                if status == "escalated"
                else "multi-request handling: replied because all sub-issues were covered by corpus"
            ),
            anomalies=["multi-request ticket"],
            matched_docs=[doc for trace in traces for doc in trace.matched_docs],
        )
        return self._validated_output(
            status=status,
            product_area=primary.product_area,
            response=response,
            justification=merged_trace.to_justification(),
            request_type=primary.request_type,
        )

    def _validated_output(
        self,
        status: str,
        product_area: str,
        response: str,
        justification: str,
        request_type: str,
    ) -> dict[str, str]:
        if status not in STATUSES:
            raise ValueError(f"invalid status: {status}")
        if request_type not in REQUEST_TYPES:
            raise ValueError(f"invalid request_type: {request_type}")
        return {
            "status": status,
            "product_area": product_area,
            "response": response,
            "justification": justification,
            "request_type": request_type,
        }

    def _metadata_from_result(self, result: dict[str, str]) -> dict[str, object]:
        justification = result.get("justification", "")
        domain = self._extract_trace_value(justification, "Domain detected", "unknown").split(" ", 1)[0]
        risk_level = self._extract_trace_value(justification, "Risk level", "UNKNOWN").split(" ", 1)[0]
        urgency_level = self._extract_trace_value(justification, "Urgency level", "UNKNOWN").split(" ", 1)[0]
        corpus_coverage = self._extract_trace_value(justification, "Corpus coverage", "unknown").split(";", 1)[0]
        decision = self._extract_trace_value(justification, "Decision", "unknown")
        anomalies = self._extract_trace_value(justification, "Anomalies", "none").rstrip(".")
        sources = self._sources_from_justification(justification)
        confidence = self._confidence_for_result(result, risk_level, corpus_coverage, sources)
        return {
            "domain": domain,
            "risk_level": risk_level,
            "urgency_level": urgency_level,
            "corpus_coverage": corpus_coverage,
            "decision": decision,
            "anomalies": anomalies,
            "confidence": confidence,
            "confidence_label": self._confidence_label(confidence),
            "sources": sources,
            "review_priority": self._review_priority(result, risk_level, urgency_level),
        }

    @staticmethod
    def _extract_trace_value(text: str, label: str, fallback: str) -> str:
        pattern = rf"{re.escape(label)}:\s*(.*?)(?=\.\s+[A-Z][A-Za-z /]+:|$)"
        match = re.search(pattern, text)
        return match.group(1).strip() if match else fallback

    def _sources_from_justification(self, justification: str) -> list[dict[str, object]]:
        match = re.search(r"matched docs:\s*(.*?)(?:\.\s+Decision:|$)", justification)
        if not match:
            return []
        raw = match.group(1).strip()
        if raw == "none":
            return []

        sources: list[dict[str, object]] = []
        for doc_id, score in re.findall(r"([^,]+?)\s+\(([0-9.]+)\)", raw):
            doc_id = doc_id.strip()
            doc = self.docs_by_id.get(doc_id)
            sources.append(
                {
                    "doc_id": doc_id,
                    "title": doc.title if doc else doc_id,
                    "domain": doc.domain if doc else "unknown",
                    "product_area": doc.product_area if doc else "unknown",
                    "url": doc.url if doc else None,
                    "score": float(score),
                }
            )
        return sources

    @staticmethod
    def _confidence_for_result(
        result: dict[str, str],
        risk_level: str,
        corpus_coverage: str,
        sources: list[dict[str, object]],
    ) -> float:
        text = result.get("justification", "").lower()
        if "stage 1 threat" in text or result.get("request_type") == "invalid":
            return 0.98
        if result.get("status") == "escalated" and risk_level == "HIGH":
            return 0.94
        if result.get("status") == "escalated" and ("always-escalate" in text or "stage 5 rule" in text):
            return 0.9
        if corpus_coverage.startswith("fully covered"):
            top_score = float(sources[0]["score"]) if sources else 0.75
            return round(min(0.96, max(0.78, 0.7 + top_score * 0.25)), 2)
        if corpus_coverage.startswith("partially covered"):
            return 0.62
        if result.get("status") == "escalated":
            return 0.76
        return 0.5

    @staticmethod
    def _confidence_label(confidence: float) -> str:
        if confidence >= 0.85:
            return "High"
        if confidence >= 0.65:
            return "Medium"
        return "Low"

    @staticmethod
    def _review_priority(result: dict[str, str], risk_level: str, urgency_level: str) -> str:
        if result.get("request_type") == "invalid":
            return "Security review"
        if result.get("status") != "escalated":
            return "No review needed"
        if risk_level == "HIGH" or urgency_level == "HIGH":
            return "High"
        if risk_level == "MEDIUM" or urgency_level == "MEDIUM":
            return "Medium"
        return "Normal"


def triage_to_json(agent: SupportTriageAgent, ticket: Ticket | dict[str, str], pretty: bool = False) -> str:
    result = agent.triage(ticket)
    kwargs = {"ensure_ascii": False}
    if pretty:
        kwargs["indent"] = 2
    return json.dumps(result, **kwargs)
