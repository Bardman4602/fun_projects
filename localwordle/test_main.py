import json
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from main import (
    WORDLISTS,
    build_empty_stats,
    build_definition_payload,
    build_dictionary_lookup_label,
    create_web_server,
    extract_online_definition,
    get_port_candidates,
    get_stats_payload,
    load_words,
    normalize_username,
    remove_word_from_wordlist,
    record_game_result,
    reset_stats,
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


class PlayerStatsTests(unittest.TestCase):
    def make_stats_path(self) -> Path:
        return Path(__file__).parent / f"stats_test_{uuid4().hex}.json"

    def make_excluded_words_path(self) -> Path:
        return Path(__file__).parent / f"excluded_words_test_{uuid4().hex}.json"

    def test_normalize_username_collapses_whitespace(self) -> None:
        self.assertEqual(normalize_username("  Ada   Lovelace  "), "Ada Lovelace")

    def test_build_empty_stats_covers_every_attempt(self) -> None:
        stats = build_empty_stats()
        self.assertEqual(stats["played"], 0)
        self.assertEqual(stats["guessDistribution"], {str(attempt): 0 for attempt in range(1, 7)})

    def test_record_game_result_updates_win_percentage_streak_and_distribution(self) -> None:
        stats_path = self.make_stats_path()
        try:
            first_payload = record_game_result("Ada", "da", True, 4, stats_path=stats_path)
            second_payload = record_game_result("Ada", "da", True, 2, stats_path=stats_path)
            third_payload = record_game_result("Ada", "da", False, 6, stats_path=stats_path)
        finally:
            stats_path.unlink(missing_ok=True)

        self.assertEqual(first_payload["played"], 1)
        self.assertEqual(first_payload["wins"], 1)
        self.assertEqual(first_payload["winPercentage"], 100)
        self.assertEqual(first_payload["currentStreak"], 1)
        self.assertEqual(first_payload["maxStreak"], 1)
        self.assertEqual(first_payload["guessDistribution"][3], {"attempt": 4, "count": 1})

        self.assertEqual(second_payload["played"], 2)
        self.assertEqual(second_payload["wins"], 2)
        self.assertEqual(second_payload["currentStreak"], 2)
        self.assertEqual(second_payload["maxStreak"], 2)
        self.assertEqual(second_payload["guessDistribution"][1], {"attempt": 2, "count": 1})

        self.assertEqual(third_payload["played"], 3)
        self.assertEqual(third_payload["wins"], 2)
        self.assertEqual(third_payload["winPercentage"], 67)
        self.assertEqual(third_payload["currentStreak"], 0)
        self.assertEqual(third_payload["maxStreak"], 2)

    def test_get_stats_payload_returns_existing_language_specific_stats(self) -> None:
        stats_path = self.make_stats_path()
        try:
            record_game_result("Ada", "da", True, 3, stats_path=stats_path)
            record_game_result("Ada", "en", False, 6, stats_path=stats_path)
            da_payload = get_stats_payload("Ada", "da", stats_path=stats_path)
            en_payload = get_stats_payload("Ada", "en", stats_path=stats_path)
        finally:
            stats_path.unlink(missing_ok=True)

        self.assertEqual(da_payload["wins"], 1)
        self.assertEqual(da_payload["played"], 1)
        self.assertEqual(da_payload["guessDistribution"][2], {"attempt": 3, "count": 1})
        self.assertEqual(en_payload["wins"], 0)
        self.assertEqual(en_payload["played"], 1)
        self.assertEqual(en_payload["currentStreak"], 0)

    def test_reset_stats_can_remove_single_language_only(self) -> None:
        stats_path = self.make_stats_path()
        try:
            record_game_result("Ada", "da", True, 3, stats_path=stats_path)
            record_game_result("Ada", "en", False, 6, stats_path=stats_path)

            was_reset = reset_stats("Ada", "da", stats_path=stats_path)
            da_payload = get_stats_payload("Ada", "da", stats_path=stats_path)
            en_payload = get_stats_payload("Ada", "en", stats_path=stats_path)
        finally:
            stats_path.unlink(missing_ok=True)

        self.assertTrue(was_reset)
        self.assertEqual(da_payload["played"], 0)
        self.assertEqual(da_payload["wins"], 0)
        self.assertEqual(en_payload["played"], 1)
        self.assertEqual(en_payload["wins"], 0)

    def test_reset_stats_without_language_removes_all_user_stats(self) -> None:
        stats_path = self.make_stats_path()
        try:
            record_game_result("Ada", "da", True, 3, stats_path=stats_path)
            record_game_result("Ada", "en", True, 2, stats_path=stats_path)

            was_reset = reset_stats("Ada", stats_path=stats_path)
            da_payload = get_stats_payload("Ada", "da", stats_path=stats_path)
            en_payload = get_stats_payload("Ada", "en", stats_path=stats_path)
        finally:
            stats_path.unlink(missing_ok=True)

        self.assertTrue(was_reset)
        self.assertEqual(da_payload["played"], 0)
        self.assertEqual(en_payload["played"], 0)

    def test_remove_word_from_wordlist_excludes_word_from_future_loads(self) -> None:
        excluded_words_path = self.make_excluded_words_path()
        try:
            original_words = load_words("da", excluded_words_path=excluded_words_path)
            self.assertIn("abort", original_words)

            payload = remove_word_from_wordlist("da", "abort", excluded_words_path=excluded_words_path)
            filtered_words = load_words("da", excluded_words_path=excluded_words_path)
        finally:
            excluded_words_path.unlink(missing_ok=True)

        self.assertTrue(payload["removed"])
        self.assertFalse(payload["alreadyRemoved"])
        self.assertNotIn("abort", filtered_words)
        self.assertEqual(payload["remainingWords"], len(filtered_words))

    def test_remove_word_from_wordlist_is_idempotent_for_already_removed_words(self) -> None:
        excluded_words_path = self.make_excluded_words_path()
        try:
            first_payload = remove_word_from_wordlist("en", "water", excluded_words_path=excluded_words_path)
            second_payload = remove_word_from_wordlist("en", "water", excluded_words_path=excluded_words_path)
        finally:
            excluded_words_path.unlink(missing_ok=True)

        self.assertTrue(first_payload["removed"])
        self.assertFalse(first_payload["alreadyRemoved"])
        self.assertFalse(second_payload["removed"])
        self.assertTrue(second_payload["alreadyRemoved"])
        self.assertEqual(first_payload["remainingWords"], second_payload["remainingWords"])


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
