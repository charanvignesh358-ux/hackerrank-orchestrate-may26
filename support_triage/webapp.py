import argparse
import csv
import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from urllib.parse import unquote, urlparse

from .cli import DEFAULT_CORPUS
from .models import Ticket
from .triage import SupportTriageAgent


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PREVIEW_INPUT = ROOT / "data" / "master_prompt_sample_tickets.csv"
REQUIRED_OUTPUT_COLUMNS = {"status", "product_area", "response", "justification", "request_type"}


def read_tickets_csv(path: str | Path) -> list[Ticket]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return tickets_from_csv_text(handle.read())


def tickets_from_csv_text(text: str) -> list[Ticket]:
    reader = csv.DictReader(StringIO(text))
    required = {"issue", "subject", "company"}
    fields = {field.lower(): field for field in (reader.fieldnames or [])}
    missing = required - set(fields)
    if missing:
        raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")
    tickets: list[Ticket] = []
    for row in reader:
        lowered = {key.lower(): value for key, value in row.items()}
        tickets.append(
            Ticket(
                issue=lowered.get("issue") or "",
                subject=lowered.get("subject") or "",
                company=lowered.get("company") or "",
            )
        )
    return tickets


def records_to_jsonl(records: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for record in records:
        result = dict(record["result"])
        if record.get("draft_response"):
            result["response"] = record["draft_response"]
        lines.append(json.dumps(result, ensure_ascii=False))
    return "\n".join(lines)


def records_to_csv(records: list[dict[str, object]]) -> str:
    output = StringIO()
    fieldnames = [
        "issue",
        "subject",
        "company",
        "status",
        "product_area",
        "request_type",
        "confidence",
        "review_priority",
        "response",
        "justification",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for record in records:
        ticket = record.get("ticket", {})
        result = record.get("result", {})
        meta = record.get("meta", {})
        writer.writerow(
            {
                "issue": ticket.get("issue", ""),
                "subject": ticket.get("subject", ""),
                "company": ticket.get("company", ""),
                "status": result.get("status", ""),
                "product_area": result.get("product_area", ""),
                "request_type": result.get("request_type", ""),
                "confidence": meta.get("confidence", ""),
                "review_priority": meta.get("review_priority", ""),
                "response": record.get("draft_response") or result.get("response", ""),
                "justification": result.get("justification", ""),
            }
        )
    return output.getvalue()


def readiness_report(root: Path = ROOT) -> dict[str, object]:
    output_csv = root / "support_tickets" / "output.csv"
    support_input = root / "support_tickets" / "support_tickets.csv"
    log_path = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "hackerrank_orchestrate" / "log.txt"
    checks = [
        _file_check("code_entrypoint", "code/main.py", root / "code" / "main.py"),
        _file_check("code_readme", "code/README.md", root / "code" / "README.md"),
        _file_check("ticket_input", "support_tickets/support_tickets.csv", support_input),
        _output_csv_check(output_csv),
        _log_check(log_path, root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    return {
        "score": passed,
        "total": len(checks),
        "checks": checks,
    }


def _file_check(check_id: str, label: str, path: Path) -> dict[str, str]:
    if path.exists() and path.is_file():
        return {"id": check_id, "label": label, "status": "pass", "detail": "present"}
    return {"id": check_id, "label": label, "status": "fail", "detail": "missing"}


def _output_csv_check(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {"id": "output_csv", "label": "support_tickets/output.csv", "status": "fail", "detail": "missing"}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
        headers = set(reader.fieldnames or [])
    except Exception as exc:
        return {"id": "output_csv", "label": "support_tickets/output.csv", "status": "fail", "detail": str(exc)}
    if headers != REQUIRED_OUTPUT_COLUMNS:
        return {
            "id": "output_csv",
            "label": "support_tickets/output.csv",
            "status": "fail",
            "detail": "schema mismatch",
        }
    if not rows or any(not all(row.get(field) for field in REQUIRED_OUTPUT_COLUMNS) for row in rows):
        return {
            "id": "output_csv",
            "label": "support_tickets/output.csv",
            "status": "fail",
            "detail": "empty fields",
        }
    return {
        "id": "output_csv",
        "label": "support_tickets/output.csv",
        "status": "pass",
        "detail": f"{len(rows)} rows",
    }


def _log_check(path: Path, root: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {"id": "fluency_log", "label": "hackerrank_orchestrate/log.txt", "status": "fail", "detail": "missing"}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        return {"id": "fluency_log", "label": "hackerrank_orchestrate/log.txt", "status": "fail", "detail": str(exc)}
    expected = f"AGREEMENT RECORDED: {root}"
    if expected not in text:
        return {
            "id": "fluency_log",
            "label": "hackerrank_orchestrate/log.txt",
            "status": "fail",
            "detail": "agreement mismatch",
        }
    turns = text.count("TURN RECORDED:")
    return {
        "id": "fluency_log",
        "label": "hackerrank_orchestrate/log.txt",
        "status": "pass",
        "detail": f"{turns} recorded turn{'s' if turns != 1 else ''}",
    }


class TriageApp:
    def __init__(self, corpus_path: str | Path = DEFAULT_CORPUS) -> None:
        self.corpus_path = Path(corpus_path)
        self.agent = SupportTriageAgent.from_corpus_file(self.corpus_path)

    def preview_records(self) -> list[dict[str, object]]:
        return self.triage_tickets(read_tickets_csv(DEFAULT_PREVIEW_INPUT))

    def triage_tickets(self, tickets: list[Ticket]) -> list[dict[str, object]]:
        records = self.agent.triage_many_with_metadata(tickets)
        for index, record in enumerate(records, start=1):
            record["id"] = index
        return records


class TriageRequestHandler(BaseHTTPRequestHandler):
    server_version = "SupportTriageHTTP/0.1"

    @property
    def app(self) -> TriageApp:
        return self.server.app  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._redirect("/ui/")
            return
        if parsed.path == "/api/health":
            self._json({"ok": True, "corpus": str(self.app.corpus_path)})
            return
        if parsed.path == "/api/preview":
            self._json({"records": self.app.preview_records()})
            return
        if parsed.path == "/api/readiness":
            self._json(readiness_report())
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/triage":
            self._handle_triage()
            return
        if parsed.path == "/api/export/jsonl":
            self._handle_export("jsonl")
            return
        if parsed.path == "/api/export/csv":
            self._handle_export("csv")
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def _handle_triage(self) -> None:
        try:
            payload = self._read_json()
            if "csv" in payload:
                tickets = tickets_from_csv_text(str(payload["csv"]))
            else:
                tickets = [Ticket.from_mapping(row) for row in payload.get("tickets", [])]
            self._json({"records": self.app.triage_tickets(tickets)})
        except Exception as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _handle_export(self, kind: str) -> None:
        try:
            payload = self._read_json()
            records = payload.get("records", [])
            if kind == "csv":
                body = records_to_csv(records).encode("utf-8")
                self._bytes(body, "text/csv; charset=utf-8", "triage-results.csv")
            else:
                body = records_to_jsonl(records).encode("utf-8")
                self._bytes(body, "application/x-ndjson; charset=utf-8", "triage-results.jsonl")
        except Exception as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def _serve_static(self, request_path: str) -> None:
        safe_path = unquote(request_path).lstrip("/")
        if not safe_path:
            safe_path = "ui/index.html"
        target = (ROOT / safe_path).resolve()
        if ROOT not in target.parents and target != ROOT:
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._bytes(target.read_bytes(), content_type)

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, body: bytes, content_type: str, filename: str | None = None) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


class TriageHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], app: TriageApp) -> None:
        super().__init__(server_address, TriageRequestHandler)
        self.app = app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local support triage web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = TriageApp(args.corpus)
    server = TriageHTTPServer((args.host, args.port), app)
    url = f"http://{args.host}:{args.port}/ui/"
    print(f"Support triage UI running at {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
