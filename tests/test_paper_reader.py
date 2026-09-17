"""论文读取：DOI/网页/PDF/打不开 各种情况都要给出对的判定与说法。"""
from pathlib import Path
import json
import sys
import unittest
import urllib.error
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import paper_reader  # noqa: E402


class _Response:
    def __init__(self, body, url="", ctype="text/html; charset=utf-8"):
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.url = url
        self.headers = {"Content-Type": ctype}

    def read(self, size=-1):
        return self._body if size is None or size < 0 else self._body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    """按 URL 前缀给响应；记下访问过的地址，便于断言「没有去下载 PDF」。"""

    def __init__(self, routes):
        self.routes = routes
        self.seen = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.seen.append(url)
        for prefix, value in self.routes.items():
            if url.startswith(prefix):
                if isinstance(value, Exception):
                    raise value
                body, ctype = value
                return _Response(body, url=url, ctype=ctype)
        raise urllib.error.URLError("no route for " + url)


def _crossref_body(title, abstract="", doi="10.1234/abc"):
    return json.dumps({"message": {"title": [title], "abstract": abstract,
                                   "container-title": ["Journal of Tests"],
                                   "issued": {"date-parts": [[2024, 5, 1]]},
                                   "author": [{"given": "A", "family": "B"}],
                                   "DOI": doi}})


LONG_ABSTRACT = "This study introduces a method. " * 20


class DetectionTests(unittest.TestCase):
    def test_paper_hosts_and_doi(self):
        self.assertTrue(paper_reader.looks_like_paper("https://arxiv.org/abs/2310.06825"))
        self.assertTrue(paper_reader.looks_like_paper("https://doi.org/10.1038/s41586-021-03819-2"))
        self.assertTrue(paper_reader.looks_like_paper("10.1016/j.jcp.2024.112345"))
        self.assertTrue(paper_reader.looks_like_paper("https://www.nature.com/articles/x"))

    def test_non_paper_links(self):
        self.assertFalse(paper_reader.looks_like_paper("https://example.com"))
        self.assertFalse(paper_reader.looks_like_paper("https://example.com/doityourself"))
        self.assertFalse(paper_reader.looks_like_paper("https://www.bilibili.com/video/BV1"))
        self.assertFalse(paper_reader.looks_like_paper(""))

    def test_helpers(self):
        self.assertEqual(paper_reader.doi_in("见 doi:10.1000/XYZ.1。"), "10.1000/xyz.1")
        self.assertEqual(paper_reader.arxiv_in("https://arxiv.org/pdf/2310.06825v2"), "2310.06825")
        self.assertEqual(paper_reader.find_url("看这个 https://a.com/b。"), "https://a.com/b")
        self.assertEqual(paper_reader.strip_tags("<b>标题</b> &amp; 副题"), "标题 & 副题")


class ReadTests(unittest.TestCase):
    def test_doi_uses_crossref(self):
        opener = _FakeOpener({"https://api.crossref.org/works/": (_crossref_body("A Test Paper", LONG_ABSTRACT),
                                                                "application/json")})
        paper = paper_reader.read_paper("https://doi.org/10.1234/abc", opener)
        self.assertTrue(paper["readable"])
        self.assertEqual(paper["source"], "Crossref")
        self.assertEqual(paper["title"], "A Test Paper")
        self.assertEqual(paper["date"], "2024-05-01")
        self.assertIn("introduces a method", paper["abstract"])

    def test_short_crossref_abstract_falls_back_to_page(self):
        page = ('<html><head><meta name="citation_title" content="Page Title">'
                '<meta name="citation_abstract" content="From the page abstract">'
                '<meta name="citation_journal_title" content="J. Page">'
                '<meta name="citation_date" content="2024/03/02"></head>'
                '<body>text</body></html>')
        opener = _FakeOpener({
            "https://api.crossref.org/works/": (_crossref_body("Meta Title", "too short"), "application/json"),
            "https://doi.org/10.1234/abc": (page, "text/html"),
        })
        paper = paper_reader.read_paper("https://doi.org/10.1234/abc", opener)
        self.assertTrue(paper["readable"])
        self.assertEqual(paper["abstract"], "From the page abstract")
        self.assertIn("https://doi.org/10.1234/abc", opener.seen)

    def test_arxiv_pdf_link_reads_abs_page(self):
        page = ('<html><head><meta name="citation_title" content="Mistral 7B">'
                '<meta name="citation_abstract" content="' + LONG_ABSTRACT + '"></head><body>x</body></html>')
        opener = _FakeOpener({"https://arxiv.org/abs/2310.06825": (page, "text/html")})
        paper = paper_reader.read_paper("https://arxiv.org/pdf/2310.06825v1", opener)
        self.assertTrue(paper["readable"])
        self.assertEqual(paper["title"], "Mistral 7B")
        self.assertEqual(paper["url"], "https://arxiv.org/abs/2310.06825")

    def test_pdf_is_not_downloaded(self):
        opener = _FakeOpener({})
        paper = paper_reader.read_paper("https://example.org/paper.pdf", opener)
        self.assertFalse(paper["readable"])
        self.assertEqual(paper["reason"], "pdf")
        self.assertEqual(opener.seen, [])   # 不该去下载 PDF

    def test_missing_doi_is_not_found(self):
        error = urllib.error.HTTPError("https://api.crossref.org/works/10.9/x", 404, "Not Found", {}, None)
        opener = _FakeOpener({
            "https://api.crossref.org/works/": error,
            "https://doi.org/10.9/x": urllib.error.HTTPError("https://doi.org/10.9/x", 404, "NF", {}, None),
        })
        paper = paper_reader.read_paper("https://doi.org/10.9/x", opener)
        self.assertFalse(paper["readable"])
        self.assertEqual(paper["reason"], "not-found")

    def test_plain_page_is_not_a_paper(self):
        opener = _FakeOpener({"https://example.com": ("<html><title>Example Domain</title><body>hi</body></html>",
                                                      "text/html")})
        paper = paper_reader.read_paper("https://example.com", opener)
        self.assertFalse(paper["readable"])
        self.assertEqual(paper["reason"], "not-paper")

    def test_network_failure(self):
        opener = _FakeOpener({})
        paper = paper_reader.read_paper("https://example.com/x", opener)
        self.assertFalse(paper["readable"])
        self.assertEqual(paper["reason"], "no-network")

    def test_failure_line_mentions_title_when_known(self):
        line = paper_reader.failure_line({"title": "Some Paper", "reason": "paywall"})
        self.assertIn("Some Paper", line)
        self.assertIn("订阅", line)
        self.assertTrue(paper_reader.failure_line({"reason": "pdf"}))

    def test_body_cleaning_drops_navigation(self):
        raw = "View PDF\nHome\nAbstract: This paper studies something with a long enough line to keep.\nPrev | Next"
        cleaned = paper_reader.clean_body(raw)
        self.assertIn("This paper studies something", cleaned)
        self.assertNotIn("View PDF", cleaned)
        self.assertNotIn("Prev | Next", cleaned)
        self.assertEqual(paper_reader.clean_body(""), "")


if __name__ == "__main__":
    unittest.main()
