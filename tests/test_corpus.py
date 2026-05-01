import unittest
from pathlib import Path

from support_triage.corpus import _extract_url, _infer_title, _strip_frontmatter


class MarkdownCorpusParsingTests(unittest.TestCase):
    def test_frontmatter_source_url_and_title_are_preferred(self) -> None:
        content = """---
title: "Does Anthropic crawl data from the web?"
source_url: "https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler"
---
Body with [bots.json](https://claude.com/crawling/bots.json).
"""

        self.assertEqual(_infer_title(content, Path("fallback.md")), "Does Anthropic crawl data from the web?")
        self.assertEqual(
            _extract_url(content),
            "https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler",
        )
        self.assertNotIn("source_url", _strip_frontmatter(content))


if __name__ == "__main__":
    unittest.main()
