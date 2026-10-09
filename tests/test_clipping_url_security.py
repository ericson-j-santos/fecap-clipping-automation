"""URL privacy regression and real SQLite persistence/readback, without network."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from clipping import Candidate, canonical_url, classify, ensure_schema, idempotency_key, persist


class ClippingURLSecurityTests(unittest.TestCase):
    def candidate(self, url: str, text: str = "Professor da FECAP explica o tema.") -> Candidate:
        return Candidate("Notícia de teste", url, "Fixture", "2026-10-09", text)

    def test_rejects_userinfo_variants(self) -> None:
        urls = (
            "https://fixture_user:fixture_secret@example.invalid/noticia",
            "http://fixture_user@example.invalid/noticia",
            "https://:fixture_secret@example.invalid/noticia",
            "https://fixture_user:@example.invalid/noticia",
            "https://@example.invalid/noticia",
            "https://fixture%40user:fixture%3Asecret@example.invalid/noticia",
            "https://fixture_user:fixture_secret@[::1]/noticia",
            "https://fixture_user:fixture_secret@other@example.invalid/noticia",
        )
        for index, url in enumerate(urls):
            with self.subTest(case=index):
                with self.assertRaisesRegex(ValueError, "^url com credenciais não permitida$"):
                    canonical_url(url)
                with self.assertRaises(ValueError):
                    idempotency_key(self.candidate(url))

    def test_parser_error_does_not_echo_credentials(self) -> None:
        # Invalid NFKC authority can make urllib echo its input in diagnostics.
        url = "https://fixture_user:fixture_secret@example.invalid\uff0fprivate"
        with self.assertRaises(ValueError) as raised:
            canonical_url(url)
        self.assertEqual(str(raised.exception), "url inválida")
        self.assertNotIn("fixture_user", str(raised.exception))
        self.assertNotIn("fixture_secret", str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)

    def test_ordinary_url_and_tracking_removal_unchanged(self) -> None:
        source = "HTTPS://EXAMPLE.INVALID/Noticia/?id=7&utm_source=teste&FBCLID=x#section"
        expected = "https://example.invalid/Noticia?id=7"
        self.assertEqual(canonical_url(source), expected)
        self.assertEqual(canonical_url(expected), expected)

    def test_at_sign_in_path_or_query_is_not_userinfo(self) -> None:
        url = "https://example.invalid/autores/ana@example.invalid?email=ana%40example.invalid"
        self.assertEqual(canonical_url(url), url)

    def test_existing_invalid_scheme_guard_is_preserved(self) -> None:
        for url in ("file:///tmp/noticia", "//example.invalid/noticia", "https:///noticia"):
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, "^url inválida$"):
                    canonical_url(url)

    def test_valid_include_and_review_round_trip_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clipping.sqlite3"
            with sqlite3.connect(path) as writer:
                ensure_schema(writer)
                inputs = (
                    (self.candidate("https://example.invalid/editorial?utm_source=teste"),
                     "include", "inserted"),
                    (self.candidate("https://example.invalid/referencia", "Referência à FECAP"),
                     "review", "queued"),
                )
                for candidate, expected_status, expected_outcome in inputs:
                    decision = classify(candidate, {}, {})
                    self.assertEqual(decision.status, expected_status)
                    self.assertEqual(persist(writer, candidate, decision), expected_outcome)
                    writer.commit()
                    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as reader:
                        table = "clipping" if expected_status == "include" else "review_queue"
                        rows = reader.execute(f"SELECT url FROM {table}").fetchall()
                        self.assertEqual(rows, [(canonical_url(candidate.url),)])
                    clean = replace(candidate, url=canonical_url(candidate.url))
                    self.assertEqual(idempotency_key(clean), idempotency_key(candidate))
                    self.assertEqual(persist(writer, clean, decision), "duplicate")
                    writer.commit()
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as reader:
                    self.assertEqual(reader.execute("SELECT count(*) FROM clipping").fetchone()[0], 1)
                    self.assertEqual(reader.execute("SELECT count(*) FROM review_queue").fetchone()[0], 1)

    def test_rejected_input_leaves_both_tables_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clipping.sqlite3"
            with sqlite3.connect(path) as writer:
                ensure_schema(writer)
                good = self.candidate("https://example.invalid/existente")
                persist(writer, good, classify(good, {}, {}))
                writer.commit()
                before = path.read_bytes()
                for text in ("Professor da FECAP explica o tema.", "Referência à FECAP"):
                    bad = self.candidate(
                        "https://fixture_user:fixture_secret@example.invalid/noticia", text
                    )
                    for _ in range(2):
                        with self.assertRaises(ValueError):
                            persist(writer, bad, classify(bad, {}, {}))
                        self.assertFalse(writer.in_transaction)
                        self.assertEqual(path.read_bytes(), before)
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as reader:
                    self.assertEqual(
                        reader.execute("SELECT url FROM clipping").fetchall(),
                        [("https://example.invalid/existente",)],
                    )
                    self.assertEqual(reader.execute("SELECT count(*) FROM review_queue").fetchone()[0], 0)
                self.assertNotIn(b"fixture_secret", path.read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
