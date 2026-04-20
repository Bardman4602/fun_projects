from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HISTORY_PATH = Path(__file__).with_name("history.json")
DATAMUSE_URL = "https://api.datamuse.com/words"
DEFAULT_LIMIT = 10
DEFAULT_SEED_COUNT = 5
MAX_EXPANSION_PER_QUERY = 40
RELATION_WEIGHTS = {
    "ml": 1.0,
    "rel_trg": 0.75,
    "rel_syn": 0.65,
    "rel_spc": 0.45,
    "rel_gen": 0.45,
}
WORD_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z -]*[a-zA-Z]$")


def normalize_word(word: str) -> str:
    normalized = " ".join(word.strip().lower().split())
    if not normalized:
        raise ValueError("word cannot be empty")
    if not WORD_PATTERN.fullmatch(normalized):
        raise ValueError(
            "word must contain only letters, spaces, or hyphens, and start/end with a letter"
        )
    return normalized


def rank_weight(rank: int) -> float:
    rank = validate_rank(rank)
    return 1.0 / math.log2(rank + 2)


def validate_rank(rank: int) -> int:
    if rank < 1:
        raise ValueError("rank must be a positive integer")
    return rank


def parse_rank_text(value: str) -> int:
    try:
        rank = int(value)
    except ValueError as exc:
        raise ValueError("rank must be a positive integer") from exc
    return validate_rank(rank)


def load_history(path: Path = HISTORY_PATH) -> list[dict[str, int | str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    guesses = payload.get("guesses", [])
    normalized_guesses: list[dict[str, int | str]] = []
    for guess in guesses:
        word = normalize_word(str(guess["word"]))
        rank = validate_rank(int(guess["rank"]))
        normalized_guesses.append({"word": word, "rank": rank})
    normalized_guesses.sort(key=lambda item: int(item["rank"]))
    return normalized_guesses


def save_history(guesses: list[dict[str, int | str]], path: Path = HISTORY_PATH) -> None:
    payload = {"guesses": sorted(guesses, key=lambda item: int(item["rank"]))}
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def upsert_guess_list(
    guesses: list[dict[str, int | str]],
    word: str,
    rank: int,
) -> list[dict[str, int | str]]:
    normalized_word = normalize_word(word)
    validated_rank = validate_rank(rank)

    updated_guesses = [
        {"word": str(guess["word"]), "rank": int(guess["rank"])}
        for guess in guesses
    ]
    for guess in updated_guesses:
        if guess["word"] == normalized_word:
            guess["rank"] = validated_rank
            break
    else:
        updated_guesses.append({"word": normalized_word, "rank": validated_rank})

    updated_guesses.sort(key=lambda item: int(item["rank"]))
    return updated_guesses


def upsert_guess(word: str, rank: int, path: Path = HISTORY_PATH) -> list[dict[str, int | str]]:
    guesses = upsert_guess_list(load_history(path), word, rank)
    save_history(guesses, path)
    return load_history(path)


def clear_history(path: Path = HISTORY_PATH) -> None:
    if path.exists():
        path.unlink()


def fetch_datamuse(params: dict[str, str], timeout: float = 10.0) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(params)
    url = f"{DATAMUSE_URL}?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "contextosolver/1.0 (+https://github.com/)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        raise ValueError("unexpected API response")
    return [item for item in payload if isinstance(item, dict)]


def expand_guess(
    word: str,
    *,
    limit: int = MAX_EXPANSION_PER_QUERY,
    timeout: float = 10.0,
) -> dict[str, float]:
    candidates: dict[str, float] = {}
    for relation, relation_weight in RELATION_WEIGHTS.items():
        params = {relation: word, "max": str(limit)}
        for entry in fetch_datamuse(params, timeout=timeout):
            candidate = entry.get("word")
            raw_score = entry.get("score", 0)
            if not isinstance(candidate, str):
                continue
            if not isinstance(raw_score, (int, float)):
                raw_score = 0
            try:
                normalized_candidate = normalize_word(candidate)
            except ValueError:
                continue
            candidate_score = relation_weight * math.log1p(float(raw_score))
            if candidate_score > candidates.get(normalized_candidate, 0.0):
                candidates[normalized_candidate] = candidate_score
    candidates.pop(normalize_word(word), None)
    return candidates


def score_candidates(
    guesses: list[dict[str, int | str]],
    *,
    per_guess_limit: int = MAX_EXPANSION_PER_QUERY,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    aggregate: dict[str, dict[str, Any]] = {}
    guessed_words = {str(guess["word"]) for guess in guesses}

    for guess in guesses:
        source_word = str(guess["word"])
        source_rank = int(guess["rank"])
        source_weight = rank_weight(source_rank)
        for candidate, api_score in expand_guess(
            source_word,
            limit=per_guess_limit,
            timeout=timeout,
        ).items():
            if candidate in guessed_words:
                continue
            item = aggregate.setdefault(
                candidate,
                {
                    "word": candidate,
                    "score": 0.0,
                    "bestSourceRank": source_rank,
                    "support": [],
                },
            )
            weighted_score = api_score * source_weight
            item["score"] += weighted_score
            item["bestSourceRank"] = min(int(item["bestSourceRank"]), source_rank)
            item["support"].append(
                {
                    "guess": source_word,
                    "rank": source_rank,
                    "score": round(weighted_score, 3),
                }
            )

    results = sorted(
        aggregate.values(),
        key=lambda item: (-float(item["score"]), int(item["bestSourceRank"]), str(item["word"])),
    )
    for item in results:
        item["score"] = round(float(item["score"]), 3)
        item["support"].sort(key=lambda support: (int(support["rank"]), -float(support["score"])))
    return results


def format_guess_row(guess: dict[str, int | str]) -> str:
    return f"{int(guess['rank']):>5}  {guess['word']}"


def format_suggestion_row(item: dict[str, Any]) -> str:
    supports = ", ".join(
        f"{support['guess']}#{support['rank']}"
        for support in item["support"][:3]
    )
    return f"{item['score']:>7.3f}  {item['word']}  <- {supports}"


def add_suggestion_arguments(
    parser: argparse.ArgumentParser,
    *,
    default_top: int = DEFAULT_LIMIT,
) -> None:
    parser.add_argument(
        "--top",
        type=int,
        default=default_top,
        help=f"How many suggestions to show (default: {default_top}).",
    )
    parser.add_argument(
        "--seed-count",
        type=int,
        default=DEFAULT_SEED_COUNT,
        help=f"How many of your best guesses to expand when suggesting words (default: {DEFAULT_SEED_COUNT}).",
    )
    parser.add_argument(
        "--per-guess-limit",
        type=int,
        default=MAX_EXPANSION_PER_QUERY,
        help=f"How many related words to fetch for each relation (default: {MAX_EXPANSION_PER_QUERY}).",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Track Contexto guesses and suggest semantically related next guesses."
    )
    subparsers = parser.add_subparsers(dest="command")

    add_parser = subparsers.add_parser("add", help="Add or update a guess and its rank.")
    add_parser.add_argument("word", help="The guess word you entered into Contexto.")
    add_parser.add_argument("rank", type=int, help="The rank Contexto returned for that guess.")

    subparsers.add_parser("list", help="Show saved guesses sorted by best rank.")
    subparsers.add_parser("clear", help="Delete saved guess history.")
    play_parser = subparsers.add_parser(
        "play",
        help="Run an interactive terminal session for a single Contexto puzzle.",
    )
    add_suggestion_arguments(play_parser, default_top=DEFAULT_LIMIT)

    suggest_parser = subparsers.add_parser(
        "suggest",
        help="Suggest next guesses from saved history or inline guess/rank pairs.",
    )
    suggest_parser.add_argument(
        "--guess",
        action="append",
        default=[],
        metavar="WORD:RANK",
        help="Inline guess and rank, for example --guess ocean:42",
    )
    add_suggestion_arguments(suggest_parser, default_top=DEFAULT_LIMIT)

    return parser


def parse_inline_guesses(values: list[str]) -> list[dict[str, int | str]]:
    guesses: list[dict[str, int | str]] = []
    for value in values:
        word, separator, rank_text = value.rpartition(":")
        if not separator:
            raise ValueError(f"invalid guess format: '{value}' (expected WORD:RANK)")
        guesses.append({"word": normalize_word(word), "rank": parse_rank_text(rank_text)})
    guesses.sort(key=lambda item: int(item["rank"]))
    return guesses


def print_guesses(
    guesses: list[dict[str, int | str]],
    *,
    output_func: Any = print,
    empty_message: str = "No guesses saved yet.",
) -> None:
    if not guesses:
        output_func(empty_message)
        return
    output_func(" Rank  Guess")
    for guess in guesses:
        output_func(format_guess_row(guess))


def print_suggestions(
    suggestions: list[dict[str, Any]],
    *,
    top: int,
    output_func: Any = print,
) -> None:
    if not suggestions:
        output_func("No candidate suggestions were returned.")
        return
    output_func(" Rank   Score  Suggestion")
    for index, item in enumerate(suggestions[:top], start=1):
        output_func(f"{index:>5}  {format_suggestion_row(item)}")


def build_seed_guesses(
    guesses: list[dict[str, int | str]],
    seed_count: int,
) -> list[dict[str, int | str]]:
    return guesses[: max(1, seed_count)]


def run_add(args: argparse.Namespace) -> int:
    guesses = upsert_guess(args.word, args.rank)
    print(f"Saved {normalize_word(args.word)} with rank {args.rank}.")
    print_guesses(guesses)
    return 0


def run_list(_: argparse.Namespace) -> int:
    print_guesses(load_history())
    return 0


def run_clear(_: argparse.Namespace) -> int:
    clear_history()
    print("Cleared saved Contexto guesses.")
    return 0


def run_suggest(args: argparse.Namespace) -> int:
    guesses = parse_inline_guesses(args.guess) if args.guess else load_history()
    if not guesses:
        print("No guesses available. Add guesses first or pass --guess WORD:RANK.", file=sys.stderr)
        return 1

    seed_guesses = build_seed_guesses(guesses, args.seed_count)
    print("Using seed guesses:")
    print_guesses(seed_guesses)
    print()
    print("Fetching related words and scoring candidates...")
    suggestions = score_candidates(
        seed_guesses,
        per_guess_limit=max(1, args.per_guess_limit),
    )

    if not suggestions:
        print("No candidate suggestions were returned.")
        return 0

    print()
    print_suggestions(suggestions, top=max(1, args.top))
    return 0


def run_play(
    args: argparse.Namespace,
    *,
    input_func: Any = input,
    output_func: Any = print,
    score_func: Any = score_candidates,
) -> int:
    guesses: list[dict[str, int | str]] = []
    top = max(1, args.top)
    seed_count = max(1, args.seed_count)
    per_guess_limit = max(1, args.per_guess_limit)

    output_func("Contexto terminal solver")
    output_func("Type a guess, then enter the rank from the website.")
    output_func("Commands: list, clear, quit")
    output_func("")

    while True:
        raw_word = input_func("Guess: ").strip()
        if not raw_word:
            output_func("Exiting Contexto solver.")
            return 0

        command = raw_word.lower()
        if command in {"quit", "exit"}:
            output_func("Exiting Contexto solver.")
            return 0
        if command == "list":
            print_guesses(
                guesses,
                output_func=output_func,
                empty_message="No guesses entered for this puzzle yet.",
            )
            output_func("")
            continue
        if command == "clear":
            guesses = []
            output_func("Cleared the current puzzle guesses.")
            output_func("")
            continue

        try:
            word = normalize_word(raw_word)
        except ValueError as exc:
            output_func(f"Error: {exc}")
            output_func("")
            continue

        rank_text = input_func("Rank: ").strip()
        if not rank_text:
            output_func("Rank entry cancelled.")
            output_func("")
            continue

        try:
            rank = parse_rank_text(rank_text)
        except ValueError as exc:
            output_func(f"Error: {exc}")
            output_func("")
            continue

        guesses = upsert_guess_list(guesses, word, rank)
        output_func("")
        output_func("Current guesses:")
        print_guesses(
            guesses,
            output_func=output_func,
            empty_message="No guesses entered for this puzzle yet.",
        )
        output_func("")

        seed_guesses = build_seed_guesses(guesses, seed_count)
        output_func(f"Using your best {len(seed_guesses)} guesses for scoring:")
        print_guesses(seed_guesses, output_func=output_func)
        output_func("")
        output_func(f"Top {top} suggestions:")

        try:
            suggestions = score_func(
                seed_guesses,
                per_guess_limit=per_guess_limit,
            )
        except urllib.error.URLError as exc:
            output_func("Network error while contacting Datamuse. Check your internet connection and try again.")
            if exc.reason:
                output_func(f"Details: {exc.reason}")
            output_func("")
            continue

        print_suggestions(suggestions, top=top, output_func=output_func)
        output_func("")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {None, "play"}:
            if args.command is None:
                args = argparse.Namespace(
                    command="play",
                    top=DEFAULT_LIMIT,
                    seed_count=DEFAULT_SEED_COUNT,
                    per_guess_limit=MAX_EXPANSION_PER_QUERY,
                )
            return run_play(args)
        if args.command == "add":
            return run_add(args)
        if args.command == "list":
            return run_list(args)
        if args.command == "clear":
            return run_clear(args)
        if args.command == "suggest":
            return run_suggest(args)
        parser.error(f"unknown command: {args.command}")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except urllib.error.URLError as exc:
        print(
            "Network error while contacting Datamuse. Check your internet connection and try again.",
            file=sys.stderr,
        )
        if exc.reason:
            print(f"Details: {exc.reason}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
