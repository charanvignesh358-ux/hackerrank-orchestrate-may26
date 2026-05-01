"""Evaluator entrypoint for the support triage agent.

This wrapper keeps the implementation in the tested support_triage package while
presenting the code/main.py contract expected by the hackathon evaluator.
"""

import sys
from pathlib import Path


CODE_DIR = Path(__file__).resolve().parent
ROOT = CODE_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(1, str(ROOT))

from support_triage.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
