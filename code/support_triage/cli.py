import argparse
import csv
import json
import sys
from io import StringIO
from pathlib import Path

from .models import Ticket
from .triage import SupportTriageAgent, triage_to_json


DEFAULT_CORPUS = Path(__file__).resolve().parent.parent / "data" / "support_corpus.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Terminal support triage agent for HackerRank, Claude, and Visa India.")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS), help="Path to support_corpus.json.")
    parser.add_argument("--input", help="CSV input with issue, subject, and company columns.")
    parser.add_argument("--output", help="Output JSONL path. Defaults to stdout.")
    parser.add_argument("--output-csv", help="Output CSV path with the five required result columns.")
    parser.add_argument("--issue", help="Single ticket issue body.")
    parser.add_argument("--subject", default="", help="Single ticket subject.")
    parser.add_argument("--company", default="", help="Single ticket company.")
    parser.add_argument("--ticket-json", help="Single ticket JSON object with issue, subject, company.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print single-ticket JSON.")
    return parser


def _ticket_from_args(args: argparse.Namespace) -> Ticket | None:
    if args.ticket_json:
        return Ticket.from_mapping(json.loads(args.ticket_json))
    if args.issue is not None:
        return Ticket(issue=args.issue, subject=args.subject, company=args.company)
    return None


def _iter_csv(path: str | Path) -> list[Ticket]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = {field.strip().lower() for field in (reader.fieldnames or [])}
        missing = {"issue", "subject", "company"} - fieldnames
        if missing:
            raise SystemExit(f"Input CSV missing required columns: {', '.join(sorted(missing))}")
        return [Ticket.from_mapping(row) for row in reader]


def results_to_csv_text(results: list[dict[str, str]]) -> str:
    fieldnames = ["status", "product_area", "response", "justification", "request_type"]
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for result in results:
        writer.writerow({field: result[field] for field in fieldnames})
    return output.getvalue()


def _write_output_csv(path: str | Path, results: list[dict[str, str]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(results_to_csv_text(results), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    agent = SupportTriageAgent.from_corpus_file(args.corpus)
    single = _ticket_from_args(args)

    if single is None and not args.input:
        parser.error("provide --input CSV, --issue, or --ticket-json")

    if single is not None:
        print(triage_to_json(agent, single, pretty=args.pretty))
        return 0

    tickets = _iter_csv(args.input)
    if args.output_csv:
        _write_output_csv(args.output_csv, [agent.triage(ticket) for ticket in tickets])
        return 0

    lines = [triage_to_json(agent, ticket) for ticket in tickets]
    output_text = "\n".join(lines)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output_text + ("\n" if output_text else ""), encoding="utf-8")
    else:
        sys.stdout.write(output_text + ("\n" if output_text else ""))
    return 0
