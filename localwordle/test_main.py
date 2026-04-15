import json
import unittest
from unittest.mock import patch

from main import (
    WORDLISTS,
    build_definition_payload,
    build_dictionary_lookup_label,
    create_web_server,
    extract_online_definition,
    get_port_candidates,
    load_words,
    render_guess,
    score_guess,
)


class ScoreGuessTests(unittest.TestCase):
    def test_marks_letters_in_correct_positions(self) -> None:
        self.assertEqual(
            score_guess("trace", "trace"),
            ["correct", "correct", "correct", "correct", "correct"],
        )

    def test_handles_duplicate_letters_like_wordle(self) -> None:
        self.assertEqual(
            score_guess("array", "cigar"),
            ["absent", "present", "absent", "correct", "absent"],
        )

    def test_render_guess_uses_three_visual_states(self) -> None:
        rendered = render_guess("array", ["absent", "present", "absent", "correct", "absent"])
        self.assertEqual(rendered, " A  (R)  R  [A]  Y ")


class WordListTests(unittest.TestCase):
    def test_wordlists_load_five_letter_words(self) -> None:
        for language_code in WORDLISTS:
            with self.subTest(language_code=language_code):
                words = load_words(language_code)
                self.assertTrue(words)
                self.assertTrue(all(len(word) == 5 for word in words))

    def test_build_definition_payload_returns_definition_for_wordlist_entry(self) -> None:
        with patch("main.fetch_online_definition", return_value=("fresh online definition", "https://example.test/water")):
            payload = json.loads(build_definition_payload("en", "water").decode("utf-8"))

        self.assertEqual(payload["word"], "water")
        self.assertEqual(payload["definition"], "fresh online definition")
        self.assertEqual(payload["definitionUrl"], "https://example.test/water")
        self.assertEqual(payload["definitionLinkLabel"], "Slå op i Wiktionary")
        self.assertEqual(payload["definitionSource"], "api")

    def test_build_definition_payload_falls_back_to_lookup_link(self) -> None:
        with patch("main.fetch_online_definition", return_value=(None, None)):
            payload = json.loads(build_definition_payload("en", "water").decode("utf-8"))

        self.assertEqual(payload["word"], "water")
        self.assertIsNone(payload["definition"])
        self.assertEqual(payload["definitionUrl"], "https://en.wiktionary.org/wiki/water")
        self.assertEqual(payload["definitionLinkLabel"], "Slå op i Wiktionary")
        self.assertEqual(payload["definitionSource"], "link")

    def test_extract_online_definition_uses_first_available_sense(self) -> None:
        payload = {
            "entries": [
                {
                    "senses": [
                        {"definition": "the first usable definition"},
                        {"definition": "a later definition"},
                    ]
                }
            ]
        }

        self.assertEqual(extract_online_definition(payload), "the first usable definition")

    def test_danish_words_use_danish_lookup_link_and_label(self) -> None:
        payload = json.loads(build_definition_payload("da", "abort").decode("utf-8"))
        self.assertIsNone(payload["definition"])
        self.assertEqual(payload["definitionUrl"], "https://ordnet.dk/ddo/ordbog?query=abort")
        self.assertEqual(payload["definitionLinkLabel"], "Slå op i Den Danske Ordbog")
        self.assertEqual(payload["definitionSource"], "link")

    def test_build_dictionary_lookup_label_is_localized(self) -> None:
        self.assertEqual(build_dictionary_lookup_label("da"), "Slå op i Den Danske Ordbog")
        self.assertEqual(build_dictionary_lookup_label("en"), "Slå op i Wiktionary")


class WebServerTests(unittest.TestCase):
    def test_default_port_gets_fallback_candidates(self) -> None:
        self.assertEqual(get_port_candidates(8000), [8000, 8765, 8080, 3000, 5500, 0])

    def test_explicit_port_does_not_silently_change(self) -> None:
        self.assertEqual(get_port_candidates(8123), [8123])

    def test_create_web_server_uses_fallback_when_default_port_is_blocked(self) -> None:
        calls: list[int] = []

        class FakeServer:
            def __init__(self, server_address, handler_class) -> None:
                port = server_address[1]
                calls.append(port)
                if port == 8000:
                    raise PermissionError("blocked")
                self.server_address = server_address

            def server_close(self) -> None:
                return None

        server, actual_port = create_web_server("127.0.0.1", 8000, server_factory=FakeServer)
        self.assertEqual(actual_port, 8765)
        self.assertEqual(calls[:2], [8000, 8765])
        server.server_close()


if __name__ == "__main__":
    unittest.main()
