# ÅBN I POWERSHELL MED "py main.py --web" (man skal stå i mappen "localwordle")

from __future__ import annotations

import argparse
import json
import random
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Spil dit eget Wordle med dansk eller engelsk ordliste."
    )
    parser.add_argument(
        "-l",
        "--language",
        choices=sorted(WORDLISTS),
        help="Vælg sprog på forhånd: da eller en.",
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


def load_words(language_code: str) -> list[str]:
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

        filepath = STATIC_FILES.get(parsed_url.path)
        if filepath is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Siden blev ikke fundet.")
            return

        self.serve_static_file(filepath)

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
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

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


def main() -> None:
    args = parse_args()
    if args.web:
        run_web_server(args.host, args.port)
        return
    run_cli(args.language)


if __name__ == "__main__":
    main()
