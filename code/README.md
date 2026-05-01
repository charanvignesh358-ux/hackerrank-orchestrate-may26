# Support Triage Agent

This directory is the evaluator-facing entrypoint for the HackerRank Orchestrate submission. The runnable entrypoint is `code/main.py`; the implementation is packaged under `code/support_triage/` so the uploaded code zip is self-contained.

## Run Commands

From the repository root:

```powershell
python code/main.py --issue "How do I opt out of web crawling?" --company Claude --pretty
python code/main.py --input support_tickets/support_tickets.csv --output-csv support_tickets/output.csv
python -m unittest discover -s tests
```

The local browser UI is optional:

```powershell
python -m support_triage.webapp --port 8080
```

Open `http://127.0.0.1:8080/ui/`.

## Architecture

The agent is pure Python and dependency-free. It uses a five-stage deterministic pipeline:

1. Threat and injection filter
2. Domain detection for HackerRank, Claude, and Visa India
3. Multi-request splitting
4. Risk and urgency scoring
5. Corpus retrieval and reply/escalate decision

Responses are grounded in `data/support_corpus.json`. Replied tickets use the selected corpus document's `response` field, plus the source URL when present. Escalated tickets receive a deterministic routing message with a traceable justification.

## Output Schema

Every ticket result contains exactly these required fields:

```text
status, product_area, response, justification, request_type
```

`status` is `replied` or `escalated`. `request_type` is `product_issue`, `feature_request`, `bug`, or `invalid`.

## Judging Notes

The sparse TF-IDF retriever is intentionally simple and reproducible. Similarity thresholds are calibrated conservatively so weak keyword overlap does not automatically become a reply. High-risk account, billing, security, fraud, and live-assessment cases are escalated before corpus coverage can produce an unsafe automated answer.
