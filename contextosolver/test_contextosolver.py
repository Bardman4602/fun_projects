import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from contextosolver import contextosolver as solver


class ContextoSolverTests(unittest.TestCase):
    def make_history_path(self) -> Path:
        return Path(__file__).parent / f"history_test_{uuid4().hex}.json"

    def test_rank_weight_prefers_better_ranks(self) -> None:
        self.assertGreater(
            solver.rank_weight(10, best_rank=10),
            solver.rank_weight(1000, best_rank=10),
        )

    def test_build_topic_words_uses_other_best_guesses_only(self) -> None:
        guesses = [
            {"word": "late", "rank": 69},
            {"word": "music", "rank": 138},
            {"word": "tune", "rank": 771},
            {"word": "song", "rank": 957},
            {"word": "radio", "rank": 1060},
            {"word": "melody", "rank": 6013},
        ]

        self.assertEqual(
            solver.build_topic_words(guesses, "late"),
            ["music", "tune", "song", "radio"],
        )

    def test_upsert_guess_list_normalizes_and_sorts(self) -> None:
        guesses = solver.upsert_guess_list([], "  Ocean  ", 120)
        guesses = solver.upsert_guess_list(guesses, "wave", 42)

        self.assertEqual(
            guesses,
            [
                {"word": "wave", "rank": 42},
                {"word": "ocean", "rank": 120},
            ],
        )

    def test_upsert_guess_normalizes_and_sorts(self) -> None:
        history_path = self.make_history_path()
        try:
            solver.upsert_guess("  Ocean  ", 120, path=history_path)
            guesses = solver.upsert_guess("wave", 42, path=history_path)
        finally:
            history_path.unlink(missing_ok=True)

        self.assertEqual(
            guesses,
            [
                {"word": "wave", "rank": 42},
                {"word": "ocean", "rank": 120},
            ],
        )

    def test_parse_inline_guesses_requires_colon(self) -> None:
        with self.assertRaises(ValueError):
            solver.parse_inline_guesses(["ocean-42"])

    def test_score_candidates_combines_multiple_supporting_guesses(self) -> None:
        guesses = [
            {"word": "ocean", "rank": 30},
            {"word": "beach", "rank": 50},
        ]

        def fake_expand_guess(word: str, **_: object) -> dict[str, float]:
            if word == "ocean":
                return {"water": 8.0, "shore": 1.0}
            if word == "beach":
                return {"water": 6.0, "shore": 4.0}
            return {}

        with patch.object(solver, "expand_guess", side_effect=fake_expand_guess):
            suggestions = solver.score_candidates(guesses)

        self.assertEqual(suggestions[0]["word"], "water")
        self.assertEqual(suggestions[0]["bestSourceRank"], 30)
        self.assertEqual(
            [support["guess"] for support in suggestions[0]["support"]],
            ["ocean", "beach"],
        )

    def test_score_candidates_strongly_prefers_the_best_ranked_guess(self) -> None:
        guesses = [
            {"word": "late", "rank": 69},
            {"word": "music", "rank": 138},
            {"word": "tune", "rank": 771},
            {"word": "song", "rank": 957},
        ]

        def fake_expand_guess(word: str, **_: object) -> dict[str, float]:
            if word == "late":
                return {"delay": 8.0}
            if word == "music":
                return {"singing": 8.0}
            if word == "tune":
                return {"singing": 8.0}
            if word == "song":
                return {"singing": 8.0}
            return {}

        with patch.object(solver, "expand_guess", side_effect=fake_expand_guess):
            suggestions = solver.score_candidates(guesses)

        self.assertEqual(suggestions[0]["word"], "delay")
        self.assertEqual(suggestions[1]["word"], "singing")

    def test_score_candidates_boosts_candidates_supported_by_multiple_good_guesses(self) -> None:
        guesses = [
            {"word": "late", "rank": 69},
            {"word": "delay", "rank": 90},
            {"word": "music", "rank": 138},
        ]

        def fake_expand_guess(
            word: str,
            *,
            topic_words: list[str] | None = None,
            **_: object,
        ) -> dict[str, float]:
            self.assertIsNotNone(topic_words)
            if word == "late":
                return {"tardy": 0.95, "posterior": 0.7}
            if word == "delay":
                return {"tardy": 0.9}
            if word == "music":
                return {"posterior": 0.92}
            return {}

        with patch.object(solver, "expand_guess", side_effect=fake_expand_guess):
            suggestions = solver.score_candidates(guesses)

        self.assertEqual(suggestions[0]["word"], "tardy")

    def test_score_candidates_excludes_all_previously_guessed_words(self) -> None:
        seed_guesses = [
            {"word": "ocean", "rank": 30},
        ]

        def fake_expand_guess(word: str, **_: object) -> dict[str, float]:
            self.assertEqual(word, "ocean")
            return {"beach": 9.0, "water": 8.0}

        with patch.object(solver, "expand_guess", side_effect=fake_expand_guess):
            suggestions = solver.score_candidates(
                seed_guesses,
                excluded_words={"ocean", "beach"},
            )

        self.assertEqual([item["word"] for item in suggestions], ["water"])

    def test_expand_guess_keeps_best_relation_score_per_candidate(self) -> None:
        responses = {
            "ml": [{"word": "water", "score": 300}],
            "rel_trg": [{"word": "water", "score": 500}, {"word": "foam", "score": 100}],
            "rel_syn": [],
            "rel_spc": [],
            "rel_gen": [],
        }

        def fake_fetch(params: dict[str, str], timeout: float = 10.0) -> list[dict[str, int | str]]:
            del timeout
            relation = next(key for key in params if key in solver.RELATION_WEIGHTS)
            return responses[relation]

        with patch.object(solver, "fetch_datamuse", side_effect=fake_fetch):
            expanded = solver.expand_guess("ocean")

        self.assertIn("water", expanded)
        self.assertIn("foam", expanded)
        self.assertGreater(expanded["water"], expanded["foam"])

    def test_expand_guess_adds_contextual_topic_queries(self) -> None:
        calls: list[dict[str, str]] = []

        def fake_fetch(params: dict[str, str], timeout: float = 10.0) -> list[dict[str, int | str]]:
            del timeout
            calls.append(params)
            if "topics" in params:
                return [{"word": "delay", "score": 300}]
            return [{"word": "lateness", "score": 300}]

        with patch.object(solver, "fetch_datamuse", side_effect=fake_fetch):
            expanded = solver.expand_guess("late", topic_words=["music", "tune"])

        self.assertIn("delay", expanded)
        self.assertTrue(any(call.get("topics") == "music tune" for call in calls))

    def test_expand_guess_filters_out_invalid_contexto_suggestions(self) -> None:
        responses = {
            "ml": [
                {"word": "ice cream", "score": 400},
                {"word": "mother-in-law", "score": 300},
                {"word": "sundae", "score": 200},
            ],
            "rel_trg": [],
            "rel_syn": [],
            "rel_spc": [],
            "rel_gen": [],
        }

        def fake_fetch(params: dict[str, str], timeout: float = 10.0) -> list[dict[str, int | str]]:
            del timeout
            relation = next(key for key in params if key in solver.RELATION_WEIGHTS)
            return responses[relation]

        with patch.object(solver, "fetch_datamuse", side_effect=fake_fetch):
            expanded = solver.expand_guess("dessert")

        self.assertNotIn("ice cream", expanded)
        self.assertNotIn("mother-in-law", expanded)
        self.assertIn("sundae", expanded)

    def test_run_play_collects_guess_and_prints_ranked_suggestions(self) -> None:
        prompts: list[str] = []
        outputs: list[str] = []
        responses = iter(["ocean", "45", "quit"])

        def fake_input(prompt: str) -> str:
            prompts.append(prompt)
            return next(responses)

        def fake_output(message: str = "") -> None:
            outputs.append(message)

        def fake_score(
            guesses: list[dict[str, int | str]],
            *,
            excluded_words: set[str],
            per_guess_limit: int,
        ) -> list[dict[str, object]]:
            self.assertEqual(guesses, [{"word": "ocean", "rank": 45}])
            self.assertEqual(excluded_words, {"ocean"})
            self.assertEqual(per_guess_limit, solver.MAX_EXPANSION_PER_QUERY)
            return [
                {
                    "word": "water",
                    "score": 2.345,
                    "bestSourceRank": 45,
                    "support": [{"guess": "ocean", "rank": 45, "score": 2.345}],
                },
                {
                    "word": "sea",
                    "score": 1.111,
                    "bestSourceRank": 45,
                    "support": [{"guess": "ocean", "rank": 45, "score": 1.111}],
                },
            ]

        args = solver.argparse.Namespace(
            top=10,
            seed_count=solver.DEFAULT_SEED_COUNT,
            per_guess_limit=solver.MAX_EXPANSION_PER_QUERY,
        )

        exit_code = solver.run_play(
            args,
            input_func=fake_input,
            output_func=fake_output,
            score_func=fake_score,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(prompts, ["Guess: ", "Rank: ", "Guess: "])
        joined_output = "\n".join(outputs)
        self.assertIn("Current guesses:", joined_output)
        self.assertIn("Top 10 suggestions:", joined_output)
        self.assertIn("water", joined_output)
        self.assertIn("sea", joined_output)
        self.assertIn("Exiting Contexto solver.", joined_output)


if __name__ == "__main__":
    unittest.main()
