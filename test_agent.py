"""Tests for the Search Chat Agent — no network (web_search is mocked)."""
import os
import tempfile
import unittest
from unittest import mock

import agent as agent_mod
from memory import Memory
from search_tool import _parse, _LITE_RESULT_RE


class TestSearchParsing(unittest.TestCase):
    def test_lite_html_parsing(self):
        html = '''
        <tr><td><a class="result-link" href="https://example.com/paris">Paris - Wikipedia</a></td>
        <td class="result-snippet">Paris is the capital of France.</td></tr>
        <tr><td><a class="result-link" href="https://example.com/france">France</a></td>
        <td class="result-snippet">France is a country in Europe.</td></tr>'''
        results = _parse(html, _LITE_RESULT_RE)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Paris - Wikipedia")
        self.assertIn("capital of France", results[0]["snippet"])

    def test_dedupe_by_url(self):
        html = ('<a class="result-link" href="https://x.com/a">A</a>'
                '<td class="result-snippet">one</td>' * 2)
        self.assertEqual(len(_parse(html, _LITE_RESULT_RE)), 1)


class TestMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.tmp.close()
        self.mem = Memory(self.tmp.name)

    def tearDown(self):
        self.mem.close()
        os.unlink(self.tmp.name)

    def test_remember_and_recall_with_timestamp(self):
        self.mem.remember("user", "What is the capital of France?",
                          ts="2026-11-10T10:00:00+00:00")
        self.mem.remember("user", "What is the capital of Japan?",
                          ts="2026-11-10T11:00:00+00:00")
        hits = self.mem.search("capital of France")
        # France matches on 2 keywords (capital + France), Japan on 1
        self.assertEqual(hits[0]["ts"], "2026-11-10T10:00:00+00:00")
        self.assertEqual(hits[0]["matches"], 2)
        self.assertEqual(self.mem.search("capital of Mars"), [])

    def test_recent_order(self):
        self.mem.remember("user", "first")
        self.mem.remember("user", "second")
        self.assertEqual([t["text"] for t in self.mem.recent(2)],
                         ["first", "second"])


FAKE_RESULTS = [
    {"title": "Paris - Wikipedia", "url": "https://en.wikipedia.org/wiki/Paris",
     "snippet": "Paris is the capital of France."},
    {"title": "Paris | Britannica", "url": "https://www.britannica.com/place/Paris",
     "snippet": "Paris, the capital of France, is on the Seine."},
]


class TestAgent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.tmp.close()
        self.agent = agent_mod.ChatAgent(Memory(self.tmp.name))

    def tearDown(self):
        self.agent.memory.close()
        os.unlink(self.tmp.name)

    def test_greeting_needs_no_search(self):
        with mock.patch("agent.web_search") as search:
            reply = self.agent.answer("hello")
            search.assert_not_called()
            self.assertIn("Hi!", reply)

    def test_factual_answer_cites_sources(self):
        with mock.patch("agent.web_search", return_value=FAKE_RESULTS):
            reply = self.agent.answer("What is the capital of France?")
        self.assertIn("Paris is the capital of France.", reply)
        self.assertIn("https://en.wikipedia.org/wiki/Paris", reply)
        self.assertIn("Corroborated by a second source", reply)

    def test_single_source_is_flagged(self):
        with mock.patch("agent.web_search", return_value=FAKE_RESULTS[:1]):
            reply = self.agent.answer("What is the capital of France?")
        self.assertIn("single-source", reply)

    def test_no_results_means_no_guess(self):
        with mock.patch("agent.web_search", return_value=[]):
            reply = self.agent.answer("What is the capital of Mars?")
        self.assertIn("don't want to guess", reply)
        self.assertNotIn("capital of Mars is", reply)

    def test_memory_question_answered_from_memory(self):
        self.agent.answer("What is the capital of France?")
        with mock.patch("agent.web_search") as search:
            reply = self.agent.answer("When did I ask about France?")
            search.assert_not_called()
        self.assertIn("capital of France", reply)
        # the timestamp of the earlier question must be in the answer
        self.assertRegex(reply, r"2026-\d{2}-\d{2}T")

    def test_memory_question_with_no_history(self):
        reply = self.agent.answer("What did I ask before?")
        self.assertIn("don't have any earlier questions", reply)


if __name__ == "__main__":
    unittest.main()
