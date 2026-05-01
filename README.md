# Terminal Support Triage Agent

A pure-Python CLI agent for triaging support tickets across three supported domains:

- HackerRank: assessments, hiring workflows, candidate and recruiter flows
- Claude: subscriptions, API, privacy, safety, conversation and integration questions
- Visa India: payment cards, fraud, transactions, travel, merchants

The agent is deliberately corpus-grounded. It answers only from `data/support_corpus.json`; when the corpus does not safely cover a ticket, it escalates.

## Quick Start

```powershell
python -m unittest discover -s tests
python -m support_triage --issue "How do I opt out of web crawling?" --company Claude --pretty
python -m support_triage --input data/sample_tickets.csv --output out/results.jsonl
python code/main.py --input support_tickets/support_tickets.csv --output-csv support_tickets/output.csv
```

Each result is a strict JSON object:

```json
{
  "status": "replied",
  "product_area": "web_crawling",
  "response": "...",
  "justification": "...",
  "request_type": "product_issue"
}
```

Batch mode writes one JSON object per line. Evaluator CSV mode writes the five required result columns:
`status`, `product_area`, `response`, `justification`, and `request_type`.

## Project Structure

- `support_triage/cli.py`: terminal entry point
- `code/main.py`: evaluator-facing wrapper entry point
- `code/README.md`: evaluator runbook and architecture summary
- `support_tickets/output.csv`: generated CSV for the scoring contract
- `support_triage/triage.py`: threat filter, domain detection, risk scoring, escalation logic, response generation
- `support_triage/corpus.py`: small sparse TF-IDF retriever implemented without external packages
- `support_triage/constants.py`: taxonomy, keyword signals, risk and threat signals
- `data/support_corpus.json`: replaceable support corpus used as source of truth
- `data/sample_tickets.csv`: demo input
- `data/master_prompt_sample_tickets.csv`: 29-case master-prompt preview input
- `tests/test_triage.py`: unit tests for threat filtering, routing, retrieval, escalation, and JSON output
- `tests/test_master_prompt_cases.py`: regression tests for the 29 exact master-prompt rulings
- `docs/prompts.md`: LLM prompts for code generation, testing, optimization, and explanation
- `docs/presentation.md`: judge-facing architecture and demo notes
- `docs/PREVIEW.md`: preview commands and demo notes

## Design

```mermaid
graph LR
    CSV[Ticket CSV or CLI ticket] --> Threat[Stage 1 threat filter]
    Threat --> Domain[Domain detection]
    Domain --> Multi[Multi-request split]
    Multi --> Risk[Risk and urgency scoring]
    Risk --> Retrieve[Corpus retrieval]
    Retrieve --> Decide[Reply or escalate]
    Decide --> JSON[Strict JSON output]
```

Key choices:

- Pure Python keeps the hackathon setup simple.
- Sparse TF-IDF retrieval is explainable, fast, and dependency-free.
- Stage 1 injection/malicious detection stops processing before retrieval or response drafting.
- High-risk, high-urgency, ambiguous, and insufficient-corpus cases escalate.
- Responses use the `response` field from the retrieved corpus document, plus its URL when present.

## Replacing The Corpus

Use `data/support_corpus.json` as the template. Every document needs:

- `id`
- `domain`
- `product_area`
- `title`
- `content`
- `response`
- optional `url`
- optional `keywords`

The `response` should contain only wording that is safe for the agent to send. This avoids free-form factual invention.

## CLI Usage

Single ticket:

```powershell
python -m support_triage --issue "Please remove an interviewer from our workspace." --subject "Team cleanup" --company HackerRank --pretty
```

JSON ticket:

```powershell
python -m support_triage --ticket-json "{\"issue\":\"There is an unauthorized transaction on my card right now.\",\"subject\":\"Fraud\",\"company\":\"Visa\"}"
```

CSV batch:

```powershell
python -m support_triage --input data/sample_tickets.csv --output out/results.jsonl
```

Evaluator CSV batch:

```powershell
python code/main.py --input support_tickets/support_tickets.csv --output-csv support_tickets/output.csv
```

Custom corpus:

```powershell
python -m support_triage --corpus path/to/support_corpus.json --input tickets.csv
```

You can also point `--corpus` at a folder of `.md`, `.markdown`, or `.txt` files. The loader infers the domain from folder names such as `hackerrank`, `claude`, and `visa`.

Master-prompt preview:

```powershell
python -m support_triage --input data\master_prompt_sample_tickets.csv --output out\master_prompt_preview.jsonl
```

## Animated UI Preview

Open the static dashboard directly:

```text
ui\index.html
```

The page includes generated preview data, so it works even without a local server. Static mode supports filtering, editing the visible draft, analytics, and browser-side exports.

For the real-world workflow with CSV upload and live Python triage, start the local web app:

```powershell
python -m support_triage.webapp --port 8080
```

Open:

```text
http://127.0.0.1:8080/ui/
```

Live mode adds:

- CSV upload from the browser
- Python agent processing for uploaded tickets
- confidence labels and source citations
- human review queue
- editable support drafts
- CSV and JSONL export
- live API health status

To regenerate the CLI preview data manually:

```powershell
python -m support_triage --input data\master_prompt_sample_tickets.csv --output out\master_prompt_preview.jsonl
```

The dashboard reads `out/master_prompt_preview.jsonl` and shows metrics, ticket filtering, decision details, strict JSON, domain mix, product areas, and the safety pipeline animation.

## Output Rules

The agent always returns:

- `status`: `replied` or `escalated`
- `product_area`: label from the taxonomy
- `response`: user-facing message
- `justification`: internal trace with domain, threat signals, risk, corpus coverage, decision, anomalies
- `request_type`: `product_issue`, `feature_request`, `bug`, or `invalid`

## Testing

```powershell
python -m unittest discover -s tests
```

The tests cover:

- prompt injection and malicious instructions
- spam/greeting handling
- unsupported general questions
- Visa fraud and travel escalation
- HackerRank account-management reply
- Claude web crawling reply
- AWS Bedrock escalation
- multi-request handling
- strict JSON serialization

## Known Limits

- The included corpus is a starter corpus for local demo purposes. Replace it with the official hackathon corpus before judging.
- Keyword routing is intentionally conservative. Ambiguous or high-risk tickets escalate.
- Multilingual domain detection includes a few common signals but is not a full translation system.
- The retriever is built for small and medium corpora. For very large corpora, switch to a dedicated search engine or vector database.
