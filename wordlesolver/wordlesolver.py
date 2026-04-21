from pathlib import Path

# Choose wordlist
WORDLIST = "words.csv"

# all the grey letters inside ""
GREY = set("pnisabot")

YELLOW = {
    # "letter": {index 0-4} 
    #  "e": {1,4},
    #  "a": {0,2},
    #  "l": {1},
    # "u": {2},
    # "r": {3}
}

GREEN = {
    # index: "letter"
    #0: "k",
    1: "e",
    #2: "o",
    3: "r",
    #4: "s",
    
}

def read_words(filename: str) -> list[str]:
    filepath = Path(__file__).parent / filename
    with open(filepath, "r", encoding="utf-8") as file:
        return [line.strip().lower() for line in file if line.strip()]

def matches_constraints(
    word: str,
    grey: set[str],
    yellow: dict[str, set[int]],
    green: dict[int, str],
) -> bool:
    if len(word) != 5:
        return False

    if any(word[pos] != letter for pos, letter in green.items()):
        return False

    required_letters = set(yellow) | set(green.values())
    forbidden_letters = grey - required_letters

    if any(letter in forbidden_letters for letter in word):
        return False

    for letter, banned_positions in yellow.items():
        if letter not in word:
            return False
        if any(word[pos] == letter for pos in banned_positions):
            return False

    return True


def main() -> None:    
    words = read_words(WORDLIST)

    for word in words:
        if matches_constraints(word, GREY, YELLOW, GREEN):
            print(word)


if __name__ == "__main__":
    main()
