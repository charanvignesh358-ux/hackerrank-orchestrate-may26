import csv
from io import StringIO
import unittest
from pathlib import Path
from unittest.mock import patch

from support_triage.cli import main, results_to_csv_text


class CliOutputTests(unittest.TestCase):
    def test_csv_text_contains_required_result_columns(self) -> None:
        csv_text = results_to_csv_text(
            [
                {
                    "status": "replied",
                    "product_area": "web_crawling",
                    "response": "Use robots.txt.",
                    "justification": "Corpus coverage: fully covered.",
                    "request_type": "product_issue",
                }
            ]
        )
        rows = list(csv.DictReader(StringIO(csv_text)))

        self.assertEqual(
            rows[0].keys(),
            {"status", "product_area", "response", "justification", "request_type"},
        )
        self.assertEqual(rows[0]["status"], "replied")
        self.assertEqual(rows[0]["product_area"], "web_crawling")
        self.assertTrue(all(rows[0][field] for field in rows[0]))

    def test_output_csv_flag_routes_batch_results_to_writer(self) -> None:
        input_path = Path(__file__).resolve().parent.parent / "data" / "sample_tickets.csv"
        captured: dict[str, object] = {}

        def fake_write(path: str, results: list[dict[str, str]]) -> None:
            captured["path"] = path
            captured["results"] = results

        with patch("support_triage.cli._write_output_csv", fake_write):
            self.assertEqual(main(["--input", str(input_path), "--output-csv", "ignored.csv"]), 0)

        self.assertEqual(captured["path"], "ignored.csv")
        self.assertEqual(len(captured["results"]), 10)

    def test_input_csv_accepts_problem_statement_header_case(self) -> None:
        input_path = Path(__file__).resolve().parent.parent / "out" / "problem_header_case.csv"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text(
            "Issue,Subject,Company\nHow do I opt out of web crawling?,Claude crawling,Claude\n",
            encoding="utf-8",
        )
        captured: dict[str, object] = {}

        def fake_write(path: str, results: list[dict[str, str]]) -> None:
            captured["path"] = path
            captured["results"] = results

        with patch("support_triage.cli._write_output_csv", fake_write):
            self.assertEqual(main(["--input", str(input_path), "--output-csv", "ignored.csv"]), 0)

        self.assertEqual(captured["path"], "ignored.csv")
        self.assertEqual(len(captured["results"]), 1)
        self.assertEqual(captured["results"][0]["status"], "replied")


if __name__ == "__main__":
    unittest.main()
