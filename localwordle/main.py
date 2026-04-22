# ÅBN I POWERSHELL MED "py main.py --web" (man skal stå i mappen "localwordle")

from __future__ import annotations

import argparse
import json
import random
import threading
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

MAX_ATTEMPTS = 6
WORD_LENGTH = 5
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
WORDLIST_DIR = BASE_DIR / "wordlists"
STATS_FILE = BASE_DIR / "player_stats.json"
EXCLUDED_WORDS_FILE = BASE_DIR / "excluded_words.json"
WORDLISTS = {
    "da": ("Dansk", WORDLIST_DIR / "dkwords.csv"),
    "en": ("English", WORDLIST_DIR / "words.csv"),
}
DICTIONARY_LINK_TEMPLATES = {
    "da": "https://ordnet.dk/ddo/ordbog?query={word}",
    "en": "https://en.wiktionary.org/wiki/{word}",
}
DICTIONARY_SOURCE_NAMES = {
    "da": "Den Danske Ordbog",
    "en": "Wiktionary",
}
ONLINE_DEFINITION_LANGUAGES = {"en"}
ONLINE_DICTIONARY_API_TEMPLATE = "https://freedictionaryapi.com/api/v1/entries/{language}/{word}"
ONLINE_DICTIONARY_TIMEOUT_SECONDS = 4
LANGUAGE_ALIASES = {
    "1": "da",
    "2": "en",
    "da": "da",
    "dk": "da",
    "dansk": "da",
    "en": "en",
    "eng": "en",
    "english": "en",
}
STATUS_LABELS = {
    "correct": "rigtig placering",
    "present": "findes i ordet",
    "absent": "findes ikke i ordet",
}
WORD_CACHE: dict[str, list[str]] = {}
STATIC_FILES = {
    "/": STATIC_DIR / "index.html",
    "/app.js": STATIC_DIR / "app.js",
    "/styles.css": STATIC_DIR / "styles.css",
}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}
FALLBACK_PORTS = (8765, 8080, 3000, 5500, 0)
STATS_LOCK = threading.Lock()
WORDS_LOCK = threading.Lock()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Spil dit eget Wordle med dansk eller engelsk ordliste."
    )
    parser.add_argument(
        "-l",
        "--language",
        choices=sorted(WORDLISTS),
        help="Vælg sprog på forhånd: da eller en. Bruges også sammen med --reset-stats.",
    )
    parser.add_argument(
        "--reset-stats",
        metavar="USERNAME",
        help="Nulstil gemt statistik for et brugernavn. Brug evt. sammen med --language.",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Start en lokal webserver og spil i browseren.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host til webserveren. Standard er 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        default=8000,
        type=int,
        help="Port til webserveren. Standard er 8000.",
    )
    return parser.parse_args()


def load_base_words(language_code: str) -> list[str]:
    if language_code in WORD_CACHE:
        return WORD_CACHE[language_code]

    _, filepath = WORDLISTS[language_code]
    with filepath.open("r", encoding="utf-8") as handle:
        words = {
            line.strip().lower()
            for line in handle
            if len(line.strip()) == WORD_LENGTH and line.strip().isalpha()
        }

    if not words:
        raise ValueError(f"Ingen gyldige ord fundet i {filepath}")

    WORD_CACHE[language_code] = sorted(words)
    return WORD_CACHE[language_code]


def read_excluded_words_store(excluded_words_path: Path = EXCLUDED_WORDS_FILE) -> dict[str, object]:
    if not excluded_words_path.exists():
        return {}

    try:
        payload = json.loads(excluded_words_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    return payload


def write_excluded_words_store(
    store: dict[str, object],
    excluded_words_path: Path = EXCLUDED_WORDS_FILE,
) -> None:
    excluded_words_path.write_text(
        json.dumps(store, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_excluded_words(
    language_code: str,
    excluded_words_path: Path = EXCLUDED_WORDS_FILE,
) -> set[str]:
    store = read_excluded_words_store(excluded_words_path)
    raw_words = store.get(language_code, [])
    if not isinstance(raw_words, list):
        return set()

    excluded_words: set[str] = set()
    for raw_word in raw_words:
        if not isinstance(raw_word, str):
            continue
        normalized_word = raw_word.strip().lower()
        if len(normalized_word) == WORD_LENGTH and normalized_word.isalpha():
            excluded_words.add(normalized_word)

    return excluded_words


def load_words(
    language_code: str,
    excluded_words_path: Path = EXCLUDED_WORDS_FILE,
) -> list[str]:
    with WORDS_LOCK:
        words = load_base_words(language_code)
        excluded_words = get_excluded_words(language_code, excluded_words_path)

    if not excluded_words:
        return words.copy()

    return [word for word in words if word not in excluded_words]


def normalize_username(username: str) -> str:
    return " ".join(username.split()).strip()


def build_empty_stats() -> dict[str, int | dict[str, int]]:
    return {
        "played": 0,
        "wins": 0,
        "currentStreak": 0,
        "maxStreak": 0,
        "guessDistribution": {str(attempt): 0 for attempt in range(1, MAX_ATTEMPTS + 1)},
    }


def coerce_stats(raw_stats: object) -> dict[str, int | dict[str, int]]:
    stats = build_empty_stats()
    if not isinstance(raw_stats, dict):
        return stats

    for field in ("played", "wins", "currentStreak", "maxStreak"):
        value = raw_stats.get(field)
        if isinstance(value, int) and value >= 0:
            stats[field] = value

    raw_distribution = raw_stats.get("guessDistribution")
    if isinstance(raw_distribution, dict):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            value = raw_distribution.get(str(attempt))
            if isinstance(value, int) and value >= 0:
                stats["guessDistribution"][str(attempt)] = value

    return stats


def read_stats_store(stats_path: Path = STATS_FILE) -> dict[str, object]:
    if not stats_path.exists():
        return {"users": {}}

    try:
        payload = json.loads(stats_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"users": {}}

    if not isinstance(payload, dict):
        return {"users": {}}

    users = payload.get("users")
    if not isinstance(users, dict):
        return {"users": {}}

    return {"users": users}


def write_stats_store(store: dict[str, object], stats_path: Path = STATS_FILE) -> None:
    stats_path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def build_stats_payload(username: str, language_code: str, stats: dict[str, int | dict[str, int]]) -> dict[str, object]:
    played = int(stats["played"])
    wins = int(stats["wins"])
    guess_distribution = stats["guessDistribution"]
    win_percentage = round((wins / played) * 100) if played else 0

    return {
        "username": username,
        "language": language_code,
        "played": played,
        "wins": wins,
        "winPercentage": win_percentage,
        "currentStreak": int(stats["currentStreak"]),
        "maxStreak": int(stats["maxStreak"]),
        "guessDistribution": [
            {"attempt": attempt, "count": int(guess_distribution[str(attempt)])}
            for attempt in range(1, MAX_ATTEMPTS + 1)
        ],
    }


def get_stats_payload(username: str, language_code: str, stats_path: Path = STATS_FILE) -> dict[str, object]:
    normalized_username = normalize_username(username)
    if not normalized_username:
        raise ValueError("Brugernavn mangler.")
    if language_code not in WORDLISTS:
        raise ValueError("Ukendt sprog.")

    with STATS_LOCK:
        store = read_stats_store(stats_path)
        users = store["users"]
        user_entry = users.get(normalized_username.casefold(), {})
        if not isinstance(user_entry, dict):
            user_entry = {}
        languages = user_entry.get("languages", {})
        if not isinstance(languages, dict):
            languages = {}
        stats = coerce_stats(languages.get(language_code))

    return build_stats_payload(normalized_username, language_code, stats)


def record_game_result(
    username: str,
    language_code: str,
    won: bool,
    attempts: int,
    stats_path: Path = STATS_FILE,
) -> dict[str, object]:
    normalized_username = normalize_username(username)
    if not normalized_username:
        raise ValueError("Brugernavn mangler.")
    if language_code not in WORDLISTS:
        raise ValueError("Ukendt sprog.")
    if attempts < 1 or attempts > MAX_ATTEMPTS:
        raise ValueError("Ugyldigt antal forsøg.")

    with STATS_LOCK:
        store = read_stats_store(stats_path)
        users = store["users"]
        user_key = normalized_username.casefold()
        user_entry = users.get(user_key)
        if not isinstance(user_entry, dict):
            user_entry = {"displayName": normalized_username, "languages": {}}

        languages = user_entry.get("languages")
        if not isinstance(languages, dict):
            languages = {}

        stats = coerce_stats(languages.get(language_code))
        stats["played"] += 1

        if won:
            stats["wins"] += 1
            stats["currentStreak"] += 1
            stats["maxStreak"] = max(int(stats["maxStreak"]), int(stats["currentStreak"]))
            stats["guessDistribution"][str(attempts)] += 1
        else:
            stats["currentStreak"] = 0

        user_entry["displayName"] = normalized_username
        languages[language_code] = stats
        user_entry["languages"] = languages
        users[user_key] = user_entry
        store["users"] = users
        write_stats_store(store, stats_path)

    return build_stats_payload(normalized_username, language_code, stats)


def reset_stats(
    username: str,
    language_code: str | None = None,
    stats_path: Path = STATS_FILE,
) -> bool:
    normalized_username = normalize_username(username)
    if not normalized_username:
        raise ValueError("Brugernavn mangler.")
    if language_code is not None and language_code not in WORDLISTS:
        raise ValueError("Ukendt sprog.")

    with STATS_LOCK:
        store = read_stats_store(stats_path)
        users = store["users"]
        user_key = normalized_username.casefold()
        user_entry = users.get(user_key)
        if not isinstance(user_entry, dict):
            return False

        if language_code is None:
            users.pop(user_key, None)
            store["users"] = users
            write_stats_store(store, stats_path)
            return True

        languages = user_entry.get("languages")
        if not isinstance(languages, dict) or language_code not in languages:
            return False

        languages.pop(language_code, None)
        if languages:
            user_entry["languages"] = languages
            users[user_key] = user_entry
        else:
            users.pop(user_key, None)

        store["users"] = users
        write_stats_store(store, stats_path)
        return True


def build_dictionary_lookup_url(language_code: str, word: str) -> str:
    encoded_word = quote(word, safe="")
    return DICTIONARY_LINK_TEMPLATES[language_code].format(word=encoded_word)


def build_dictionary_lookup_label(language_code: str) -> str:
    return f"Slå op i {DICTIONARY_SOURCE_NAMES[language_code]}"


def extract_online_definition(api_payload: dict[str, object]) -> str | None:
    entries = api_payload.get("entries")
    if not isinstance(entries, list):
        return None

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        senses = entry.get("senses")
        if not isinstance(senses, list):
            continue

        for sense in senses:
            if not isinstance(sense, dict):
                continue

            definition = sense.get("definition")
            if isinstance(definition, str) and definition.strip():
                return definition.strip()

    return None


def fetch_online_definition(language_code: str, word: str) -> tuple[str | None, str | None]:
    if language_code not in ONLINE_DEFINITION_LANGUAGES:
        return None, None

    encoded_word = quote(word, safe="")
    url = ONLINE_DICTIONARY_API_TEMPLATE.format(language=language_code, word=encoded_word)
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "LocalWordle/1.0 (+https://localhost)",
        },
    )

    try:
        with urlopen(request, timeout=ONLINE_DICTIONARY_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None, None

    if not isinstance(payload, dict):
        return None, None

    definition = extract_online_definition(payload)
    source = payload.get("source")
    if isinstance(source, dict):
        source_url = source.get("url")
        if isinstance(source_url, str) and source_url.strip():
            return definition, source_url.strip()

    return definition, None


def choose_language(current_language: str | None = None) -> str:
    if current_language in WORDLISTS:
        return current_language

    print("Vælg ordliste:")
    print("  1. Dansk")
    print("  2. Engelsk")

    while True:
        choice = input("> ").strip().lower()
        language_code = LANGUAGE_ALIASES.get(choice)
        if language_code:
            return language_code
        print("Skriv 1 / da for dansk eller 2 / en for 1.")


def score_guess(guess: str, answer: str) -> list[str]:
    statuses = ["absent"] * WORD_LENGTH
    remaining_letters: Counter[str] = Counter()

    for index, (guess_letter, answer_letter) in enumerate(zip(guess, answer)):
        if guess_letter == answer_letter:
            statuses[index] = "correct"
        else:
            remaining_letters[answer_letter] += 1

    for index, guess_letter in enumerate(guess):
        if statuses[index] == "correct":
            continue
        if remaining_letters[guess_letter] > 0:
            statuses[index] = "present"
            remaining_letters[guess_letter] -= 1

    return statuses


def render_guess(guess: str, statuses: list[str]) -> str:
    tiles: list[str] = []
    for letter, status in zip(guess.upper(), statuses):
        if status == "correct":
            tiles.append(f"[{letter}]")
        elif status == "present":
            tiles.append(f"({letter})")
        else:
            tiles.append(f" {letter} ")
    return " ".join(tiles)


def explain_legend() -> None:
    print()
    print("Forklaring: [A] = rigtig placering, (A) = findes i ordet,  A  = ikke i ordet")
    print()


def prompt_guess(valid_words: set[str]) -> str:
    while True:
        guess = input("Gæt et ord på 5 bogstaver: ").strip().lower()
        if guess in {"q", "quit", "exit"}:
            raise KeyboardInterrupt
        if len(guess) != WORD_LENGTH:
            print("Ordet skal være på 5 bogstaver.")
            continue
        if not guess.isalpha():
            print("Brug kun bogstaver.")
            continue
        if guess not in valid_words:
            print("Det ord findes ikke i den valgte ordliste.")
            continue
        return guess


def play_round(language_code: str, words: list[str]) -> None:
    language_name, _ = WORDLISTS[language_code]
    answer = random.choice(words)
    valid_words = set(words)

    print()
    print(f"Nyt spil startet. Sprog: {language_name}.")
    print("Skriv 'q' hvis du vil afslutte midt i et spil.")
    explain_legend()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"Forsøg {attempt}/{MAX_ATTEMPTS}")
        guess = prompt_guess(valid_words)
        statuses = score_guess(guess, answer)
        print(render_guess(guess, statuses))
        print()

        if guess == answer:
            print(f"Du vandt på {attempt} forsøg. Ordet var '{answer}'.")
            return

    print(f"Ikke helt denne gang. Ordet var '{answer}'.")


def prompt_next_action() -> str:
    print()
    print("Tryk Enter for at spille igen, skriv 'sprog' for at skifte sprog, eller 'q' for at afslutte.")
    return input("> ").strip().lower()


def run_cli(language: str | None = None) -> None:
    current_language = choose_language(language)

    try:
        while True:
            words = load_words(current_language)
            play_round(current_language, words)

            action = prompt_next_action()
            if action in {"q", "quit", "exit", "n", "nej"}:
                print("Tak for spillet.")
                return
            if action == "sprog":
                current_language = choose_language()
    except KeyboardInterrupt:
        print()
        print("Spillet blev afsluttet.")


def build_word_payload(language_code: str) -> bytes:
    language_name, _ = WORDLISTS[language_code]
    payload = {
        "language": language_code,
        "languageName": language_name,
        "wordLength": WORD_LENGTH,
        "maxAttempts": MAX_ATTEMPTS,
        "words": load_words(language_code),
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def remove_word_from_wordlist(
    language_code: str,
    word: str,
    excluded_words_path: Path = EXCLUDED_WORDS_FILE,
) -> dict[str, object]:
    normalized_word = word.strip().lower()
    if language_code not in WORDLISTS:
        raise ValueError("Ukendt sprog.")
    if len(normalized_word) != WORD_LENGTH or not normalized_word.isalpha():
        raise ValueError("Ugyldigt ord.")

    with WORDS_LOCK:
        base_words = load_base_words(language_code)
        if normalized_word not in base_words:
            raise ValueError("Ordet findes ikke i ordlisten.")

        excluded_words = get_excluded_words(language_code, excluded_words_path)
        active_words = [candidate for candidate in base_words if candidate not in excluded_words]

        if normalized_word in excluded_words:
            return {
                "language": language_code,
                "word": normalized_word,
                "removed": False,
                "alreadyRemoved": True,
                "remainingWords": len(active_words),
            }

        if len(active_words) <= 1:
            raise ValueError("Kan ikke fjerne det sidste ord fra ordlisten.")

        excluded_words.add(normalized_word)
        store = read_excluded_words_store(excluded_words_path)
        store[language_code] = sorted(excluded_words)
        write_excluded_words_store(store, excluded_words_path)

        return {
            "language": language_code,
            "word": normalized_word,
            "removed": True,
            "alreadyRemoved": False,
            "remainingWords": len(active_words) - 1,
        }


def build_definition_payload(language_code: str, word: str) -> bytes:
    normalized_word = word.strip().lower()
    fallback_url = build_dictionary_lookup_url(language_code, normalized_word)
    online_definition, online_source_url = fetch_online_definition(language_code, normalized_word)

    if online_definition:
        definition = online_definition
        definition_url = online_source_url or fallback_url
        definition_source = "api"
    else:
        definition = None
        definition_url = fallback_url
        definition_source = "link"

    payload = {
        "language": language_code,
        "word": normalized_word,
        "definition": definition,
        "definitionUrl": definition_url,
        "definitionLinkLabel": build_dictionary_lookup_label(language_code),
        "definitionSource": definition_source,
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class LocalWordleHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)

        if parsed_url.path == "/api/words":
            self.serve_wordlist(parsed_url.query)
            return

        if parsed_url.path == "/api/definition":
            self.serve_definition(parsed_url.query)
            return

        if parsed_url.path == "/api/stats":
            self.serve_stats(parsed_url.query)
            return

        filepath = STATIC_FILES.get(parsed_url.path)
        if filepath is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Siden blev ikke fundet.")
            return

        self.serve_static_file(filepath)

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)

        if parsed_url.path == "/api/stats":
            self.record_stats()
            return

        if parsed_url.path == "/api/words/remove":
            self.remove_word()
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Siden blev ikke fundet.")

    def serve_static_file(self, filepath: Path) -> None:
        if not filepath.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Filen blev ikke fundet.")
            return

        content = filepath.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", CONTENT_TYPES.get(filepath.suffix, "text/plain; charset=utf-8"))
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def serve_wordlist(self, query: str) -> None:
        params = parse_qs(query)
        language_code = params.get("language", ["da"])[0].lower()
        if language_code not in WORDLISTS:
            self.send_error(HTTPStatus.BAD_REQUEST, "Ukendt sprog.")
            return

        payload = build_word_payload(language_code)
        self.send_json_response(payload)

    def serve_definition(self, query: str) -> None:
        params = parse_qs(query)
        language_code = params.get("language", ["da"])[0].lower()
        word = params.get("word", [""])[0]

        if language_code not in WORDLISTS:
            self.send_error(HTTPStatus.BAD_REQUEST, "Ukendt sprog.")
            return

        if len(word.strip()) != WORD_LENGTH or not word.strip().isalpha():
            self.send_error(HTTPStatus.BAD_REQUEST, "Ugyldigt ord.")
            return

        payload = build_definition_payload(language_code, word)
        self.send_json_response(payload)

    def serve_stats(self, query: str) -> None:
        params = parse_qs(query)
        username = params.get("username", [""])[0]
        language_code = params.get("language", ["da"])[0].lower()

        try:
            payload = json.dumps(
                get_stats_payload(username, language_code),
                ensure_ascii=False,
            ).encode("utf-8")
        except ValueError as error:
            self.send_error(HTTPStatus.BAD_REQUEST, str(error))
            return

        self.send_json_response(payload)

    def record_stats(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))

        try:
            raw_body = self.rfile.read(content_length)
            body = json.loads(raw_body.decode("utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(HTTPStatus.BAD_REQUEST, "Ugyldig JSON.")
            return

        if not isinstance(body, dict):
            self.send_error(HTTPStatus.BAD_REQUEST, "Ugyldig JSON.")
            return

        username = body.get("username", "")
        language_code = str(body.get("language", "da")).lower()
        won = body.get("won")
        attempts = body.get("attempts")

        if not isinstance(won, bool) or not isinstance(attempts, int):
            self.send_error(HTTPStatus.BAD_REQUEST, "Ugyldigt resultat.")
            return

        try:
            payload = json.dumps(
                record_game_result(username, language_code, won, attempts),
                ensure_ascii=False,
            ).encode("utf-8")
        except ValueError as error:
            self.send_error(HTTPStatus.BAD_REQUEST, str(error))
            return

        self.send_json_response(payload)

    def remove_word(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))

        try:
            raw_body = self.rfile.read(content_length)
            body = json.loads(raw_body.decode("utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(HTTPStatus.BAD_REQUEST, "Ugyldig JSON.")
            return

        if not isinstance(body, dict):
            self.send_error(HTTPStatus.BAD_REQUEST, "Ugyldig JSON.")
            return

        language_code = str(body.get("language", "da")).lower()
        word = body.get("word", "")

        try:
            payload = json.dumps(
                remove_word_from_wordlist(language_code, str(word)),
                ensure_ascii=False,
            ).encode("utf-8")
        except ValueError as error:
            self.send_error(HTTPStatus.BAD_REQUEST, str(error))
            return

        self.send_json_response(payload)

    def send_json_response(self, payload: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def get_port_candidates(port: int) -> list[int]:
    candidates = [port]
    if port == 8000:
        for fallback_port in FALLBACK_PORTS:
            if fallback_port not in candidates:
                candidates.append(fallback_port)
    return candidates


def create_web_server(
    host: str,
    port: int,
    server_factory: type[ThreadingHTTPServer] = ThreadingHTTPServer,
) -> tuple[ThreadingHTTPServer, int]:
    last_error: OSError | None = None

    for candidate_port in get_port_candidates(port):
        try:
            server = server_factory((host, candidate_port), LocalWordleHandler)
            actual_port = server.server_address[1]
            return server, actual_port
        except PermissionError as error:
            last_error = error
        except OSError as error:
            last_error = error

    requested_port = port
    raise RuntimeError(
        "Kunne ikke starte webserveren. "
        f"Port {requested_port} og de automatiske reserveporte blev afvist. "
        "Prøv igen med for eksempel '--port 8765' eller '--port 0'."
    ) from last_error


def run_web_server(host: str, port: int) -> None:
    server, actual_port = create_web_server(host, port)
    if actual_port != port:
        print(f"Port {port} kunne ikke bruges. Skifter automatisk til port {actual_port}.")

    print(f"Local Wordle kører på http://{host}:{actual_port}")
    print("Åbn adressen i din browser. Tryk Ctrl+C for at stoppe serveren.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("Webserveren blev stoppet.")
    finally:
        server.server_close()


def run_reset_stats(username: str, language_code: str | None) -> None:
    was_reset = reset_stats(username, language_code)
    normalized_username = normalize_username(username)

    if was_reset:
        if language_code:
            language_name, _ = WORDLISTS[language_code]
            print(f"Statistik for '{normalized_username}' på {language_name} blev nulstillet.")
        else:
            print(f"Al statistik for '{normalized_username}' blev nulstillet.")
        return

    if language_code:
        language_name, _ = WORDLISTS[language_code]
        print(f"Der blev ikke fundet statistik for '{normalized_username}' på {language_name}.")
    else:
        print(f"Der blev ikke fundet statistik for '{normalized_username}'.")


def main() -> None:
    args = parse_args()
    if args.reset_stats:
        run_reset_stats(args.reset_stats, args.language)
        return
    if args.web:
        run_web_server(args.host, args.port)
        return
    run_cli(args.language)


if __name__ == "__main__":
    main()
