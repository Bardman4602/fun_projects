const STATUS_PRIORITY = {
  absent: 0,
  present: 1,
  correct: 2,
};

const KEYBOARD_LAYOUTS = {
  da: [
    ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "å"],
    ["a", "s", "d", "f", "g", "h", "j", "k", "l", "æ", "ø"],
    ["enter", "z", "x", "c", "v", "b", "n", "m", "backspace"],
  ],
  en: [
    ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
    ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
    ["enter", "z", "x", "c", "v", "b", "n", "m", "backspace"],
  ],
};

const COLORBLIND_STORAGE_KEY = "localwordle-colorblind-mode";

const state = {
  language: "da",
  languageName: "Dansk",
  words: [],
  validWords: new Set(),
  answer: "",
  guesses: [],
  currentGuess: "",
  keyboardState: {},
  maxAttempts: 6,
  wordLength: 5,
  isGameOver: false,
  colorblindMode: false,
  answerDefinition: null,
  definitionRequestId: 0,
};

const boardElement = document.querySelector("#board");
const keyboardElement = document.querySelector("#keyboard");
const languageSelect = document.querySelector("#language-select");
const colorblindToggle = document.querySelector("#colorblind-toggle");
const newGameButton = document.querySelector("#new-game-button");
const statusMessage = document.querySelector("#status-message");
const subtitle = document.querySelector("#subtitle");
const definitionCard = document.querySelector("#definition-card");
const definitionWord = document.querySelector("#definition-word");
const definitionText = document.querySelector("#definition-text");
const definitionLink = document.querySelector("#definition-link");

function randomItem(items) {
  return items[Math.floor(Math.random() * items.length)];
}

function scoreGuess(guess, answer) {
  const statuses = Array(answer.length).fill("absent");
  const remaining = new Map();

  for (let index = 0; index < answer.length; index += 1) {
    if (guess[index] === answer[index]) {
      statuses[index] = "correct";
    } else {
      remaining.set(answer[index], (remaining.get(answer[index]) ?? 0) + 1);
    }
  }

  for (let index = 0; index < guess.length; index += 1) {
    const letter = guess[index];
    if (statuses[index] === "correct") {
      continue;
    }

    const available = remaining.get(letter) ?? 0;
    if (available > 0) {
      statuses[index] = "present";
      remaining.set(letter, available - 1);
    }
  }

  return statuses;
}

function setStatus(message, detail = "") {
  statusMessage.textContent = message;
  subtitle.textContent = detail;
}

function renderDefinition() {
  if (!state.answerDefinition) {
    definitionCard.classList.add("hidden");
    definitionWord.textContent = "";
    definitionText.textContent = "";
    definitionLink.classList.add("hidden");
    definitionLink.removeAttribute("href");
    return;
  }

  definitionCard.classList.remove("hidden");
  definitionWord.textContent = state.answerDefinition.word.toUpperCase();
  if (state.answerDefinition.text) {
    definitionText.textContent = state.answerDefinition.text;
  } else {
    definitionText.textContent = "Ordet kan slås op via linket nedenfor.";
  }

  if (state.answerDefinition.url) {
    definitionLink.href = state.answerDefinition.url;
    definitionLink.textContent = state.answerDefinition.linkLabel || "Slå op i ordbogen";
    definitionLink.classList.remove("hidden");
  } else {
    definitionLink.classList.add("hidden");
    definitionLink.removeAttribute("href");
    definitionLink.textContent = "Slå op i ordbogen";
  }
}

function clearDefinition() {
  state.answerDefinition = null;
  renderDefinition();
}

function readSavedColorblindMode() {
  try {
    return window.localStorage.getItem(COLORBLIND_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function applyColorblindMode() {
  document.body.classList.toggle("colorblind-mode", state.colorblindMode);
  colorblindToggle.checked = state.colorblindMode;

  try {
    window.localStorage.setItem(COLORBLIND_STORAGE_KEY, String(state.colorblindMode));
  } catch {
    return;
  }
}

async function loadAnswerDefinition() {
  const requestId = state.definitionRequestId + 1;
  state.definitionRequestId = requestId;
  const answer = state.answer;

  try {
    state.answerDefinition = {
      word: answer,
      text: "Finder definition...",
    };
    renderDefinition();

    const response = await fetch(
      `/api/definition?language=${encodeURIComponent(state.language)}&word=${encodeURIComponent(answer)}`
    );
    if (!response.ok) {
      throw new Error("Kunne ikke hente definitionen.");
    }

    const payload = await response.json();
    if (requestId !== state.definitionRequestId || answer !== state.answer) {
      return;
    }
    state.answerDefinition = {
      word: payload.word,
      text: payload.definition ?? "",
      url: payload.definitionUrl,
      linkLabel: payload.definitionLinkLabel,
    };
  } catch (error) {
    if (requestId !== state.definitionRequestId || answer !== state.answer) {
      return;
    }
    state.answerDefinition = {
      word: answer,
      text: error.message,
      url: "",
      linkLabel: "",
    };
  }

  renderDefinition();
}

function updateKeyboard(guess, statuses) {
  for (let index = 0; index < guess.length; index += 1) {
    const letter = guess[index];
    const nextStatus = statuses[index];
    const currentStatus = state.keyboardState[letter];
    if (!currentStatus || STATUS_PRIORITY[nextStatus] > STATUS_PRIORITY[currentStatus]) {
      state.keyboardState[letter] = nextStatus;
    }
  }
}

function renderBoard() {
  boardElement.innerHTML = "";

  for (let rowIndex = 0; rowIndex < state.maxAttempts; rowIndex += 1) {
    const row = document.createElement("div");
    row.className = "board-row";

    const guessData = state.guesses[rowIndex];
    const letters = guessData
      ? guessData.guess.split("")
      : rowIndex === state.guesses.length
        ? state.currentGuess.padEnd(state.wordLength).split("")
        : Array(state.wordLength).fill("");

    for (let columnIndex = 0; columnIndex < state.wordLength; columnIndex += 1) {
      const tile = document.createElement("div");
      const letter = letters[columnIndex] ?? "";

      tile.className = "tile";
      tile.textContent = letter.trim();

      if (tile.textContent) {
        tile.classList.add("filled");
      }

      if (guessData) {
        tile.classList.add(guessData.statuses[columnIndex]);
      }

      row.appendChild(tile);
    }

    boardElement.appendChild(row);
  }
}

function createKey(label) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "key";
  button.dataset.key = label;

  if (label === "enter") {
    button.textContent = "Enter";
    button.classList.add("wide");
  } else if (label === "backspace") {
    button.textContent = "Slet";
    button.classList.add("wide");
  } else {
    button.textContent = label;
  }

  const status = state.keyboardState[label];
  if (status) {
    button.classList.add(status);
  }

  button.addEventListener("click", () => handleInput(label));
  return button;
}

function renderKeyboard() {
  keyboardElement.innerHTML = "";
  const layout = KEYBOARD_LAYOUTS[state.language] ?? KEYBOARD_LAYOUTS.en;

  for (const rowLetters of layout) {
    const row = document.createElement("div");
    row.className = "keyboard-row";

    for (const label of rowLetters) {
      row.appendChild(createKey(label));
    }

    keyboardElement.appendChild(row);
  }
}

function startNewGame() {
  state.answer = randomItem(state.words);
  state.guesses = [];
  state.currentGuess = "";
  state.keyboardState = {};
  state.isGameOver = false;
  state.definitionRequestId += 1;
  clearDefinition();

  setStatus(
    `Nyt spil startet på ${state.languageName}.`,
    `Gæt et ord på ${state.wordLength} bogstaver. Du har ${state.maxAttempts} forsøg.`
  );
  renderBoard();
  renderKeyboard();
}

async function loadLanguage(language) {
  setStatus("Indlæser ordliste...", "");

  const response = await fetch(`/api/words?language=${encodeURIComponent(language)}`);
  if (!response.ok) {
    throw new Error("Kunne ikke hente ordlisten.");
  }

  const payload = await response.json();
  state.language = payload.language;
  state.languageName = payload.languageName;
  state.words = payload.words;
  state.validWords = new Set(payload.words);
  state.maxAttempts = payload.maxAttempts;
  state.wordLength = payload.wordLength;
  languageSelect.value = payload.language;
  renderKeyboard();
  startNewGame();
}

function finishGame(win) {
  state.isGameOver = true;
  if (win) {
    setStatus(
      "Du vandt!",
      `Ordet var ${state.answer.toUpperCase()}. Tryk på "Nyt spil" for en ny runde.`
    );
    loadAnswerDefinition();
    return;
  }

  setStatus(
    "Runden er slut.",
    `Ordet var ${state.answer.toUpperCase()}. Tryk på "Nyt spil" for at prøve igen.`
  );
  loadAnswerDefinition();
}

function submitGuess() {
  if (state.isGameOver) {
    return;
  }

  if (state.currentGuess.length !== state.wordLength) {
    setStatus("Du mangler bogstaver.", `Skriv et ord på ${state.wordLength} bogstaver.`);
    return;
  }

  if (!state.validWords.has(state.currentGuess)) {
    setStatus("Det ord findes ikke i ordlisten.", "Prøv et andet ord.");
    return;
  }

  const statuses = scoreGuess(state.currentGuess, state.answer);
  state.guesses.push({
    guess: state.currentGuess,
    statuses,
  });
  updateKeyboard(state.currentGuess, statuses);
  state.currentGuess = "";
  renderBoard();
  renderKeyboard();

  const latestGuess = state.guesses.at(-1).guess;
  if (latestGuess === state.answer) {
    finishGame(true);
    return;
  }

  if (state.guesses.length >= state.maxAttempts) {
    finishGame(false);
    return;
  }

  setStatus(
    `Forsøg ${state.guesses.length + 1} af ${state.maxAttempts}.`,
    `Du spiller på ${state.languageName}.`
  );
}

function isLetterKey(key) {
  return /^[a-zæøå]$/i.test(key);
}

function handleInput(key) {
  if (key === "enter") {
    submitGuess();
    return;
  }

  if (key === "backspace") {
    if (state.isGameOver) {
      return;
    }
    state.currentGuess = state.currentGuess.slice(0, -1);
    renderBoard();
    return;
  }

  if (!isLetterKey(key) || state.isGameOver) {
    return;
  }

  if (state.currentGuess.length >= state.wordLength) {
    return;
  }

  state.currentGuess += key.toLocaleLowerCase();
  renderBoard();
}

document.addEventListener("keydown", (event) => {
  if (event.metaKey || event.ctrlKey || event.altKey) {
    return;
  }

  if (event.key === "Enter") {
    event.preventDefault();
    handleInput("enter");
    return;
  }

  if (event.key === "Backspace") {
    event.preventDefault();
    handleInput("backspace");
    return;
  }

  if (isLetterKey(event.key)) {
    event.preventDefault();
    handleInput(event.key);
  }
});

languageSelect.addEventListener("change", async (event) => {
  try {
    await loadLanguage(event.target.value);
  } catch (error) {
    setStatus("Noget gik galt under skift af sprog.", error.message);
  }
});

newGameButton.addEventListener("click", () => {
  if (!state.words.length) {
    return;
  }
  startNewGame();
});

colorblindToggle.addEventListener("change", (event) => {
  state.colorblindMode = event.target.checked;
  applyColorblindMode();
});

definitionLink.addEventListener("click", (event) => {
  const url = definitionLink.href;
  if (!url) {
    return;
  }

  event.preventDefault();
  window.open(url, "_blank", "noopener,noreferrer");
});

state.colorblindMode = readSavedColorblindMode();
applyColorblindMode();

loadLanguage(state.language).catch((error) => {
  setStatus("Kunne ikke starte spillet.", error.message);
});
