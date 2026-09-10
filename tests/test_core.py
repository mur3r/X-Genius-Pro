"""
Юнит-тесты чистой логики (xgenius/core). Не требуют selenium/tkinter.
Запуск из папки проекта:  python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xgenius import core  # noqa: E402
from xgenius.core import (  # noqa: E402
    ChatStore, classify_page, classify_driver_error, split_for_typing,
    OK_TO_TYPE, NO_INPUT, RETRY, NEED_RELOGIN, LOCKED, SUCCESS, is_x_url,
)


def probe(**kw):
    base = {
        "url": "https://x.com/i/chat/g123", "ready": "complete", "hasComposer": False,
        "composerValue": None, "hasSend": False, "entries": 0, "conversationLoaded": False,
        "hasLoginForm": False, "hasSpinner": False, "toasts": "", "text": "",
    }
    base.update(kw)
    return base


class ClassifyPageTests(unittest.TestCase):
    def test_composer_present_is_ok(self):
        self.assertEqual(classify_page(probe(hasComposer=True), "g123")[0], OK_TO_TYPE)

    def test_conversation_loaded_without_composer_is_no_input(self):
        verdict, reason = classify_page(probe(conversationLoaded=True, entries=12), "g123")
        self.assertEqual(verdict, NO_INPUT)

    def test_read_only_marker_reported(self):
        verdict, reason = classify_page(
            probe(conversationLoaded=True, text="you can't send messages to this group"), "g123")
        self.assertEqual(verdict, NO_INPUT)
        self.assertIn("marker", reason)

    def test_error_page_is_retry(self):
        verdict, _ = classify_page(probe(text="something went wrong. try reloading."), "g123")
        self.assertEqual(verdict, RETRY)

    def test_still_loading_is_retry(self):
        verdict, _ = classify_page(probe(ready="loading", hasSpinner=True), "g123")
        self.assertEqual(verdict, RETRY)

    def test_chrome_error_page_is_retry_not_relogin(self):
        verdict, _ = classify_page(probe(url="chrome-error://chromewebdata/"), "g123")
        self.assertEqual(verdict, RETRY)

    def test_login_redirect(self):
        self.assertEqual(classify_page(probe(url="https://x.com/i/flow/login"), "g123")[0], NEED_RELOGIN)

    def test_lock_page(self):
        self.assertEqual(classify_page(probe(url="https://x.com/account/access"), "g123")[0], LOCKED)

    def test_redirected_away_from_chat_is_no_input(self):
        verdict, _ = classify_page(probe(url="https://x.com/messages"), "g123")
        self.assertEqual(verdict, NO_INPUT)

    def test_probe_failure_is_retry(self):
        self.assertEqual(classify_page(None, "g123")[0], RETRY)


class DriverErrorTests(unittest.TestCase):
    def test_timeout(self):
        self.assertEqual(classify_driver_error(Exception("HTTPConnectionPool: Read timed out. (read timeout=120)")), "timeout")

    def test_connection_refused_is_closed(self):
        self.assertEqual(classify_driver_error(Exception("Max retries exceeded ... [WinError 10061] connection refused")), "closed")

    def test_chrome_not_reachable(self):
        self.assertEqual(classify_driver_error(Exception("chrome not reachable")), "closed")

    def test_invalid_session_type(self):
        class InvalidSessionIdException(Exception):
            pass
        self.assertEqual(classify_driver_error(InvalidSessionIdException("x")), "closed")

    def test_other(self):
        self.assertEqual(classify_driver_error(Exception("no such element")), "other")


class TypingSplitTests(unittest.TestCase):
    def test_bmp_symbols_are_keys(self):
        chunks = split_for_typing("a☭卐♫✰")
        self.assertTrue(all(k == "key" for k, _ in chunks))
        self.assertEqual("".join(p for _, p in chunks), "a☭卐♫✰")

    def test_emoji_becomes_insert(self):
        chunks = split_for_typing("hi 🔥🚀 ok")
        kinds = [k for k, _ in chunks]
        self.assertIn("insert", kinds)
        self.assertEqual("".join(p for _, p in chunks), "hi 🔥🚀 ok")
        insert = [p for k, p in chunks if k == "insert"]
        self.assertEqual(insert, ["🔥🚀"])

    def test_newline(self):
        chunks = split_for_typing("a\nb")
        self.assertEqual(chunks, [("key", "a"), ("newline", "\n"), ("key", "b")])

    def test_vs16_joins_previous(self):
        chunks = split_for_typing("x❤️y")
        self.assertEqual("".join(p for _, p in chunks), "x❤️y")
        self.assertIn(("insert", "❤️"), chunks)


class ChatStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ChatStore(Path(self.tmp.name))
        self.u = "user1"

    def tearDown(self):
        self.tmp.cleanup()

    def test_merge_never_drops_groups(self):
        self.store.merge_parsed(self.u, ["g1", "g2", "g3"])
        all_groups, added = self.store.merge_parsed(self.u, ["g2"])  # неполный парсинг
        self.assertEqual(sorted(all_groups), ["g1", "g2", "g3"])
        self.assertEqual(added, 0)

    def test_retry_returns_group_to_end_of_queue(self):
        self.store.merge_parsed(self.u, ["g1", "g2"])
        first = self.store.next_chat(self.u)
        self.store.report(self.u, first, RETRY, "timeout")
        second = self.store.next_chat(self.u)
        self.assertNotEqual(first, second)
        third = self.store.next_chat(self.u)
        self.assertEqual(third, first)

    def test_no_input_disables_after_strikes_but_keeps_cache(self):
        self.store.merge_parsed(self.u, ["g1", "g2"])
        event = None
        for _ in range(core.NO_INPUT_STRIKES_TO_DISABLE):
            event = self.store.report(self.u, "g1", NO_INPUT, "no composer")
        self.assertEqual(event, "disabled")
        self.assertIn("g1", self.store.all_groups(self.u))
        self.assertNotIn("g1", self.store.enabled_groups(self.u))
        self.assertIn("g1", self.store.disabled_groups(self.u))
        for _ in range(4):
            self.assertEqual(self.store.next_chat(self.u), "g2")

    def test_disabled_group_retried_after_ttl(self):
        self.store.merge_parsed(self.u, ["g1"])
        now = 1_000_000.0
        for _ in range(core.NO_INPUT_STRIKES_TO_DISABLE):
            self.store.report(self.u, "g1", NO_INPUT, "x", now=now)
        self.assertIsNone(self.store.next_chat(self.u, now=now + 60))
        later = now + core.DISABLED_TTL_HOURS * 3600 + 1
        self.assertEqual(self.store.next_chat(self.u, now=later), "g1")

    def test_success_resets_strikes(self):
        self.store.merge_parsed(self.u, ["g1"])
        self.store.report(self.u, "g1", NO_INPUT, "x")
        self.store.report(self.u, "g1", NO_INPUT, "x")
        self.store.report(self.u, "g1", SUCCESS)
        self.assertEqual(self.store.group_state(self.u, "g1")["no_input"], 0)

    def test_persisted_between_instances(self):
        self.store.merge_parsed(self.u, ["g1", "g2"])
        self.store.report(self.u, "g1", NO_INPUT, "x")
        reloaded = ChatStore(Path(self.tmp.name))
        self.assertEqual(sorted(reloaded.all_groups(self.u)), ["g1", "g2"])
        self.assertEqual(reloaded.group_state(self.u, "g1")["no_input"], 1)

    def test_legacy_files_are_read(self):
        (Path(self.tmp.name) / "chat_cache.json").write_text('{"user1": ["a", "b"]}', encoding="utf-8")
        (Path(self.tmp.name) / "chat_queue.json").write_text('{"user1": ["b"]}', encoding="utf-8")
        s = ChatStore(Path(self.tmp.name))
        self.assertEqual(s.all_groups("user1"), ["a", "b"])
        self.assertEqual(s.next_chat("user1"), "b")


class UrlTests(unittest.TestCase):
    def test_is_x_url(self):
        self.assertTrue(is_x_url("https://x.com/home"))
        self.assertFalse(is_x_url("chrome-error://chromewebdata/"))
        self.assertFalse(is_x_url("about:blank"))
        self.assertFalse(is_x_url(None))


if __name__ == "__main__":
    unittest.main()
