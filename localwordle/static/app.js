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
const USERNAME_STORAGE_KEY = "localwordle-username";

const state = {
  language: "da",
  languageName: "Dansk",
  username: "",
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
  stats: null,
  statsRequestId: 0,
  lastCompletedAttempt: null,
  isRemovingWord: false,
  answerRemoved: false,
  removeWordFeedback: "",
  removeWordFeedbackTone: "",
};

const boardElement = document.querySelector("#board");
const keyboardElement = document.querySelector("#keyboard");
const languageSelect = document.querySelector("#language-select");
const usernameInput = document.querySelector("#username-input");
const colorblindToggle = document.querySelector("#colorblind-toggle");
const newGameButton = document.querySelector("#new-game-button");
const statusMessage = document.querySelector("#status-message");
const subtitle = document.querySelector("#subtitle");
const statsCard = document.querySelector("#stats-card");
const statsSummary = document.querySelector("#stats-summary");
const statsEmpty = document.querySelector("#stats-empty");
const statsContent = document.querySelector("#stats-content");
const statsPlayed = document.querySelector("#stats-played");
const statsWinPercentage = document.querySelector("#stats-win-percentage");
const statsCurrentStreak = document.querySelector("#stats-current-streak");
const statsMaxStreak = document.querySelector("#stats-max-streak");
const guessDistributionElement = document.querySelector("#guess-distribution");
const definitionCard = document.querySelector("#definition-card");
const definitionWord = document.querySelector("#definition-word");
const definitionText = document.querySelector("#definition-text");
const definitionLink = document.querySelector("#definition-link");
const removeWordButton = document.querySelector("#remove-word-button");
const removeWordFeedback = document.querySelector("#remove-word-feedback");

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

function normalizeUsername(username) {
  return username.trim().replace(/\s+/g, " ").slice(0, 24);
}

function readSavedUsername() {
  try {
    return normalizeUsername(window.localStorage.getItem(USERNAME_STORAGE_KEY) ?? "");
  } catch {
    return "";
  }
}

function saveUsername(username) {
  try {
    if (username) {
      window.localStorage.setItem(USERNAME_STORAGE_KEY, username);
    } else {
      window.localStorage.removeItem(USERNAME_STORAGE_KEY);
    }
  } catch {
    return;
  }
}

function updateUsername(rawUsername) {
  const nextUsername = normalizeUsername(rawUsername);
  const changed = nextUsername !== state.username;

  state.username = nextUsername;
  usernameInput.value = nextUsername;
  saveUsername(nextUsername);

  if (changed) {
    state.stats = null;
    state.lastCompletedAttempt = null;
  }

  return changed;
}

function createDistributionRow(entry, maxCount) {
  const row = document.createElement("div");
  row.className = "distribution-row";

  const label = document.createElement("span");
  label.className = "distribution-attempt";
  label.textContent = entry.attempt;

  const bar = document.createElement("div");
  bar.className = "distribution-bar";
  if (state.lastCompletedAttempt === entry.attempt && entry.count > 0) {
    bar.classList.add("active");
  }

  const fill = document.createElement("div");
  fill.className = "distribution-fill";
  const width = entry.count > 0 ? Math.max(12, Math.round((entry.count / maxCount) * 100)) : 0;
  fill.style.width = `${width}%`;
  fill.textContent = String(entry.count);
  bar.appendChild(fill);

  row.append(label, bar);
  return row;
}

function renderStats() {
  statsCard.classList.remove("hidden");

  if (!state.username) {
    statsSummary.textContent = "Vælg et brugernavn for at gemme statistik.";
    statsEmpty.textContent =
      "Resultater gemmes pr. brugernavn og sprog, så du kan lukke spillet og fortsætte senere.";
    statsEmpty.classList.remove("hidden");
    statsContent.classList.add("hidden");
    guessDistributionElement.innerHTML = "";
    return;
  }

  if (!state.stats) {
    statsSummary.textContent = `Henter statistik for ${state.username}...`;
    statsEmpty.textContent = "Statistikken bliver indlæst automatisk.";
    statsEmpty.classList.remove("hidden");
    statsContent.classList.add("hidden");
    guessDistributionElement.innerHTML = "";
    return;
  }

  statsSummary.textContent = `${state.isGameOver ? "Statistik" : "Samlet statistik"} for ${state.stats.username} på ${state.languageName}`;
  statsEmpty.classList.add("hidden");
  statsContent.classList.remove("hidden");
  statsPlayed.textContent = String(state.stats.played);
  statsWinPercentage.textContent = String(state.stats.winPercentage);
  statsCurrentStreak.textContent = String(state.stats.currentStreak);
  statsMaxStreak.textContent = String(state.stats.maxStreak);

  guessDistributionElement.innerHTML = "";
  const maxCount = Math.max(1, ...state.stats.guessDistribution.map((entry) => entry.count));
  for (const entry of state.stats.guessDistribution) {
    guessDistributionElement.appendChild(createDistributionRow(entry, maxCount));
  }
}

function renderDefinition() {
  if (!state.answerDefinition) {
    definitionCard.classList.add("hidden");
    definitionWord.textContent = "";
    definitionText.textContent = "";
    definitionLink.classList.add("hidden");
    definitionLink.removeAttribute("href");
    removeWordButton.classList.add("hidden");
    removeWordButton.disabled = false;
    removeWordButton.textContent = "Fjern ord fra ordlisten";
    removeWordFeedback.classList.add("hidden");
    removeWordFeedback.textContent = "";
    removeWordFeedback.classList.remove("success", "error");
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

  if (state.isGameOver && state.answer) {
    removeWordButton.classList.remove("hidden");
    removeWordButton.disabled = state.isRemovingWord || state.answerRemoved;

    if (state.isRemovingWord) {
      removeWordButton.textContent = "Fjerner ord...";
    } else if (state.answerRemoved) {
      removeWordButton.textContent = "Ord fjernet fra ordlisten";
    } else {
      removeWordButton.textContent = "Fjern ord fra ordlisten";
    }
  } else {
    removeWordButton.classList.add("hidden");
    removeWordButton.disabled = false;
    removeWordButton.textContent = "Fjern ord fra ordlisten";
  }

  if (state.removeWordFeedback) {
    removeWordFeedback.textContent = state.removeWordFeedback;
    removeWordFeedback.classList.remove("hidden", "success", "error");
    if (state.removeWordFeedbackTone) {
      removeWordFeedback.classList.add(state.removeWordFeedbackTone);
    }
  } else {
    removeWordFeedback.classList.add("hidden");
    removeWordFeedback.textContent = "";
    removeWordFeedback.classList.remove("success", "error");
  }
}

function clearDefinition() {
  state.answerDefinition = null;
  state.isRemovingWord = false;
  state.answerRemoved = false;
  state.removeWordFeedback = "";
  state.removeWordFeedbackTone = "";
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

async function loadStats() {
  if (!state.username) {
    state.stats = null;
    renderStats();
    return;
  }

  const requestId = state.statsRequestId + 1;
  state.statsRequestId = requestId;
  state.stats = null;
  renderStats();

  try {
    const response = await fetch(
      `/api/stats?username=${encodeURIComponent(state.username)}&language=${encodeURIComponent(state.language)}`
    );
    if (!response.ok) {
      throw new Error("Kunne ikke hente statistik.");
    }

    const payload = await response.json();
    if (requestId !== state.statsRequestId) {
      return;
    }
    state.stats = payload;
  } catch (error) {
    if (requestId !== state.statsRequestId) {
      return;
    }
    state.stats = null;
    statsSummary.textContent = `Kunne ikke hente statistik for ${state.username}.`;
    statsEmpty.textContent = error.message;
    statsEmpty.classList.remove("hidden");
    statsContent.classList.add("hidden");
    guessDistributionElement.innerHTML = "";
    return;
  }

  renderStats();
}

async function saveCompletedGame(win) {
  if (!state.username) {
    renderStats();
    return;
  }

  const requestId = state.statsRequestId + 1;
  state.statsRequestId = requestId;

  try {
    const response = await fetch("/api/stats", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        username: state.username,
        language: state.language,
        won: win,
        attempts: state.guesses.length,
      }),
    });
    if (!response.ok) {
      throw new Error("Kunne ikke gemme statistik.");
    }

    const payload = await response.json();
    if (requestId !== state.statsRequestId) {
      return;
    }
    state.stats = payload;
    renderStats();
  } catch (error) {
    if (requestId !== state.statsRequestId) {
      return;
    }
    statsSummary.textContent = `Kunne ikke gemme statistik for ${state.username}.`;
    statsEmpty.textContent = error.message;
    statsEmpty.classList.remove("hidden");
    statsContent.classList.add("hidden");
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

async function removeAnswerWord() {
  if (!state.isGameOver || !state.answer || state.isRemovingWord || state.answerRemoved) {
    return;
  }

  state.isRemovingWord = true;
  state.removeWordFeedback = "";
  state.removeWordFeedbackTone = "";
  renderDefinition();

  try {
    const response = await fetch("/api/words/remove", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        language: state.language,
        word: state.answer,
      }),
    });
    if (!response.ok) {
      throw new Error("Kunne ikke fjerne ordet fra ordlisten.");
    }

    const payload = await response.json();
    state.words = state.words.filter((candidate) => candidate !== payload.word);
    state.validWords = new Set(state.words);
    state.answerRemoved = Boolean(payload.removed || payload.alreadyRemoved);
    state.removeWordFeedback = `${payload.word.toUpperCase()} er fjernet fra ${state.languageName.toLowerCase()} ordliste.`;
    state.removeWordFeedbackTone = "success";
  } catch (error) {
    state.removeWordFeedback = error.message;
    state.removeWordFeedbackTone = "error";
  } finally {
    state.isRemovingWord = false;
    renderDefinition();
  }
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
  state.lastCompletedAttempt = null;
  state.definitionRequestId += 1;
  clearDefinition();
  renderStats();

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
  await loadStats();
}

function finishGame(win) {
  state.isGameOver = true;
  state.lastCompletedAttempt = win ? state.guesses.length : null;
  renderStats();
  if (win) {
    setStatus(
      "Du vandt!",
      `Ordet var ${state.answer.toUpperCase()}. Tryk på "Nyt spil" for en ny runde.`
    );
    loadAnswerDefinition();
    saveCompletedGame(true);
    return;
  }

  setStatus(
    "Runden er slut.",
    `Ordet var ${state.answer.toUpperCase()}. Tryk på "Nyt spil" for at prøve igen.`
  );
  loadAnswerDefinition();
  saveCompletedGame(false);
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

function isTypingTarget(target) {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  if (target.isContentEditable) {
    return true;
  }

  return ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
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
  if (isTypingTarget(event.target)) {
    return;
  }

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

usernameInput.addEventListener("change", async (event) => {
  updateUsername(event.target.value);
  await loadStats();
});

usernameInput.addEventListener("input", (event) => {
  updateUsername(event.target.value);
  renderStats();
});

usernameInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") {
    return;
  }

  event.preventDefault();
  usernameInput.blur();
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

removeWordButton.addEventListener("click", () => {
  removeAnswerWord();
});

state.colorblindMode = readSavedColorblindMode();
state.username = readSavedUsername();
usernameInput.value = state.username;
applyColorblindMode();
renderStats();

loadLanguage(state.language).catch((error) => {
  setStatus("Kunne ikke starte spillet.", error.message);
});
