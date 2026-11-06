// Copyright (c) 2026-2027 Michal Salanci
// SPDX-License-Identifier: MIT

// @ts-check
/**
 * The scanner page's script: the staff PIN, reading ticket QR codes with html5-qrcode, searching attendees
 * by name, and the result card with Reprint and Try again.
 *
 * Loaded by index.html after vendor/html5-qrcode.min.js. It calls POST /api/scan, GET /api/search and
 * POST /api/reprint on its own origin with the X-Staff-Pin header, and shows each answer's message on a
 * coloured card. The PIN is kept in localStorage under cdr.staffPin, or in memory when the browser refuses
 * storage.
 */

const PIN_KEY = "cdr.staffPin";
const ANSWER_TIMEOUT_MS = 12000;
const RESUME_AFTER_MS = 2000;
const SAME_TICKET_MS = 10000;
const SEARCH_DELAY_MS = 300;
const MIN_SEARCH = 3;
const TEXTS = {
  checking: "Checking…",
  searching: "Searching…",
  noMatches: "No matches",
  noName: "(no name)",
  noAnswer: "No answer — try again",
  tooMany: "Too many scans at once — try again",
  wentWrong: "Something went wrong — try again",
  wrongPin: "Wrong PIN",
  tryAgain: "Try again",
  reprint: "Reprint",
  cameraBlocked: "The camera is blocked — allow it for this site in the browser's settings, then reload",
  cameraMissing: "No camera found — open this page in Safari or Chrome on the phone",
};
const COLOURS = {
  checked_in: "green",
  reprinting: "green",
  already_checked_in: "amber",
  print_failed: "amber",
  not_checked_in: "amber",
  invalid: "red",
};
const REPRINTABLE = ["already_checked_in", "print_failed"];
const FEEDBACK = {
  green: { vibrate: [120], beeps: [[880, 0.15]] },
  amber: { vibrate: [120, 90, 120], beeps: [[660, 0.12], [660, 0.12]] },
  red: { vibrate: [120, 90, 120, 90, 120], beeps: [[220, 0.45]] },
};

/** @typedef {{ path: string, body: { secret: string, nonce: string } }} ApiRequest */
/** @typedef {{ result?: unknown, message?: unknown, attendee?: { first_name?: unknown, last_name?: unknown }, results?: unknown, more?: unknown }} ApiBody */
/** @typedef {{ status: number, body: ApiBody | null }} ApiAnswer */
/** @typedef {{ secret: string, first_name: string, last_name: string, order_code: string, checked_in_at: string | null }} SearchResult */

let memoryPin = "";
/** @type {AudioContext | null} */
let audio = null;
/** @type {any} */
let scanner = null;
let busy = false;
let lastTicket = "";
let lastTicketAt = 0;
/** @type {ApiRequest | null} */
let lastRequest = null;
let cardSecret = "";
let cardAction = "";
let activeTab = "scan";
let searchTimer = 0;
let searchSequence = 0;

/**
 * Find an element of the page by its ID.
 * @param {string} id - The element's ID.
 * @returns {HTMLElement} The element.
 * @throws {Error} When the page has no such element.
 */
function element(id) {
  const found = document.getElementById(id);
  if (!found) {
    throw new Error(`missing #${id}`);
  }
  return found;
}

/**
 * Read the staff PIN from storage, or from memory when storage is unavailable.
 * No parameters.
 * @returns {string} The PIN; empty when none is stored.
 */
function readPin() {
  try {
    return window.localStorage.getItem(PIN_KEY) || memoryPin;
  } catch {
    return memoryPin;
  }
}

/**
 * Keep the staff PIN in storage, and in memory in case storage fails.
 * @param {string} pin - The PIN.
 * @returns {void} Nothing; writes localStorage when the browser allows it.
 */
function storePin(pin) {
  memoryPin = pin;
  try {
    window.localStorage.setItem(PIN_KEY, pin);
  } catch {
    return;
  }
}

/**
 * Forget the staff PIN everywhere.
 * No parameters.
 * @returns {void} Nothing; removes it from localStorage when the browser allows it.
 */
function forgetPin() {
  memoryPin = "";
  try {
    window.localStorage.removeItem(PIN_KEY);
  } catch {
    return;
  }
}

/**
 * Show the PIN screen, with an optional warning, and stop the camera.
 * @param {string} warning - The warning to show, such as "Wrong PIN"; empty for none.
 * @returns {void} Nothing.
 */
function showPinScreen(warning) {
  stopCamera();
  element("app").hidden = true;
  element("pin-screen").hidden = false;
  const message = element("pin-message");
  message.textContent = warning;
  message.hidden = !warning;
  const field = /** @type {HTMLInputElement} */ (element("pin"));
  field.value = "";
  field.focus();
}

/**
 * Show the app on its Scan tab, which starts the camera.
 * No parameters.
 * @returns {void} Nothing.
 */
function showApp() {
  element("pin-screen").hidden = true;
  element("app").hidden = false;
  showTab("scan");
}

/**
 * Switch between the Scan and the Search tab; the camera reads only while the Scan tab is shown.
 * @param {string} tab - "scan" or "search".
 * @returns {void} Nothing.
 */
function showTab(tab) {
  activeTab = tab;
  element("scan-view").hidden = tab !== "scan";
  element("search-view").hidden = tab !== "search";
  element("tab-scan").classList.toggle("active", tab === "scan");
  element("tab-search").classList.toggle("active", tab === "search");
  if (tab === "search") {
    setPaused(true);
    element("search").focus();
    return;
  }
  if (!scanner) {
    startCamera();
  } else if (!busy) {
    setPaused(false);
  }
}

/**
 * Take the PIN from the field and start scanning; also unlocks sound, which needs a tap.
 * @param {Event} event - The tap or the keyboard's Go key; its default action is prevented.
 * @returns {void} Nothing.
 */
function start(event) {
  event.preventDefault();
  const field = /** @type {HTMLInputElement} */ (element("pin"));
  const pin = field.value.trim();
  if (!pin) {
    return;
  }
  storePin(pin);
  field.value = "";
  unlockAudio();
  showApp();
}

/**
 * Create the audio context during a tap, as browsers require before sound can play.
 * No parameters.
 * @returns {void} Nothing.
 */
function unlockAudio() {
  try {
    if (!audio) {
      const AudioCtor = window.AudioContext || /** @type {any} */ (window).webkitAudioContext;
      audio = AudioCtor ? new AudioCtor() : null;
    }
    if (audio && audio.state === "suspended") {
      audio.resume();
    }
  } catch {
    audio = null;
  }
}

/**
 * Vibrate and beep for a card's colour.
 * @param {string} colour - "green", "amber" or "red"; anything else gives no feedback.
 * @returns {void} Nothing.
 */
function feedback(colour) {
  const pattern = FEEDBACK[/** @type {keyof typeof FEEDBACK} */ (colour)];
  if (!pattern) {
    return;
  }
  if (typeof navigator.vibrate === "function") {
    navigator.vibrate(pattern.vibrate);
  }
  if (!audio) {
    return;
  }
  let at = audio.currentTime;
  for (const [frequency, seconds] of pattern.beeps) {
    const oscillator = audio.createOscillator();
    const gain = audio.createGain();
    oscillator.frequency.value = frequency;
    gain.gain.value = 0.3;
    oscillator.connect(gain).connect(audio.destination);
    oscillator.start(at);
    oscillator.stop(at + seconds);
    at += seconds + 0.08;
  }
}

/**
 * Start the rear camera, reading QR codes about 10 times a second in a box of 70% of the view.
 * No parameters.
 * @returns {void} Nothing; a camera problem is shown under the view.
 */
function startCamera() {
  if (scanner) {
    return;
  }
  const library = /** @type {any} */ (window).__Html5QrcodeLibrary__;
  const message = element("camera-message");
  message.hidden = true;
  scanner = new library.Html5Qrcode("reader", { formatsToSupport: [library.Html5QrcodeSupportedFormats.QR_CODE], verbose: false });
  scanner
    .start(
      { facingMode: "environment" },
      {
        fps: 10,
        qrbox: (/** @type {number} */ width, /** @type {number} */ height) => {
          const side = Math.floor(Math.min(width, height) * 0.7);
          return { width: side, height: side };
        },
      },
      onRead,
      () => {},
    )
    .catch((/** @type {any} */ error) => {
      scanner = null;
      const name = String((error && error.name) || error);
      message.textContent = name.includes("NotAllowed") ? TEXTS.cameraBlocked : TEXTS.cameraMissing;
      message.hidden = false;
    });
}

/**
 * Stop the camera, if it runs.
 * No parameters.
 * @returns {void} Nothing.
 */
function stopCamera() {
  if (!scanner) {
    return;
  }
  const running = scanner;
  scanner = null;
  running.stop().catch(() => {});
}

/**
 * Pause or resume reading, ignoring the library's complaint when the camera is not in that state.
 * @param {boolean} pause - True to pause the video, false to resume.
 * @returns {void} Nothing.
 */
function setPaused(pause) {
  if (!scanner) {
    return;
  }
  try {
    if (pause) {
      scanner.pause(true);
    } else {
      scanner.resume();
    }
  } catch {
    return;
  }
}

/**
 * Handle a QR code the camera read: ignore it while busy, on the Search tab, or when it is the ticket
 * just shown; else scan it.
 * @param {string} text - The QR code's text, the ticket secret.
 * @returns {void} Nothing.
 */
function onRead(text) {
  if (busy || activeTab !== "scan") {
    return;
  }
  if (text === lastTicket && Date.now() - lastTicketAt < SAME_TICKET_MS) {
    return;
  }
  ask(ticketRequest("/api/scan", text));
}

/**
 * Build a scan or reprint request with a new nonce.
 * @param {string} path - "/api/scan" or "/api/reprint".
 * @param {string} secret - The ticket secret.
 * @returns {ApiRequest} The request; Try again sends it unchanged, so a retry never acts twice.
 */
function ticketRequest(path, secret) {
  return { path, body: { secret, nonce: crypto.randomUUID() } };
}

/**
 * Send a scan or reprint request with the camera paused, show its card, and let the camera read again
 * 2 s after the answer (on the Scan tab only).
 * @param {ApiRequest} request - The request.
 * @returns {Promise<void>} Resolves when the card shows the answer.
 */
async function ask(request) {
  busy = true;
  lastRequest = request;
  setPaused(true);
  showCard("checking", "", TEXTS.checking, "");
  const answer = await callApi("POST", request.path, request.body);
  if (answer.status === 401) {
    busy = false;
    forgetPin();
    showPinScreen(TEXTS.wrongPin);
    return;
  }
  lastTicket = request.body.secret;
  lastTicketAt = Date.now();
  render(answer, request);
  if (activeTab === "search") {
    refreshSearch();
  }
  window.setTimeout(() => {
    busy = false;
    if (activeTab === "scan") {
      setPaused(false);
    }
  }, RESUME_AFTER_MS);
}

/**
 * Call the API and read its answer, giving up after 12 s.
 * @param {string} method - "GET" or "POST".
 * @param {string} path - The path, with its query for a GET.
 * @param {object} [body] - The JSON body of a POST.
 * @returns {Promise<ApiAnswer>} The HTTP status (0 for no answer) and the JSON body, if any.
 */
async function callApi(method, path, body) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), ANSWER_TIMEOUT_MS);
  /** @type {Record<string, string>} */
  const headers = { "X-Staff-Pin": readPin() };
  if (body) {
    headers["Content-Type"] = "application/json";
  }
  try {
    const response = await fetch(path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      cache: "no-store",
      credentials: "omit",
    });
    let parsed = null;
    try {
      parsed = await response.json();
    } catch {
      parsed = null;
    }
    return { status: response.status, body: parsed };
  } catch {
    return { status: 0, body: null };
  } finally {
    window.clearTimeout(timer);
  }
}

/**
 * The page's own text for an answer without a result: no answer, the throttle, or anything else.
 * @param {ApiAnswer} answer - The HTTP status and JSON body.
 * @returns {string} The text to show.
 */
function failureText(answer) {
  if (answer.status === 0) {
    return TEXTS.noAnswer;
  }
  if (answer.status === 429) {
    return TEXTS.tooMany;
  }
  return TEXTS.wentWrong;
}

/**
 * Turn an answer into its card: the API's own message only when the body has a result. Amber cards for a
 * ticket that is checked in get Reprint; grey cards get Try again.
 * @param {ApiAnswer} answer - The HTTP status and JSON body.
 * @param {ApiRequest} request - The request it answers; Reprint uses its ticket secret.
 * @returns {void} Nothing.
 */
function render(answer, request) {
  const body = answer.body;
  if (body && typeof body.result === "string") {
    const colour = COLOURS[/** @type {keyof typeof COLOURS} */ (body.result)] || "grey";
    const message = typeof body.message === "string" ? body.message : TEXTS.wentWrong;
    let action = "";
    if (colour === "grey") {
      action = "retry";
    } else if (REPRINTABLE.includes(body.result)) {
      action = "reprint";
    }
    cardSecret = action === "reprint" ? request.body.secret : "";
    showCard(colour, attendeeName(body), message, action);
    feedback(colour);
    return;
  }
  cardSecret = "";
  showCard("grey", "", failureText(answer), "retry");
}

/**
 * Join the attendee's name from an answer.
 * @param {ApiBody} body - The API's answer.
 * @returns {string} "First Last", or empty when the answer has no attendee.
 */
function attendeeName(body) {
  const person = body.attendee || {};
  return [person.first_name, person.last_name]
    .filter((part) => typeof part === "string" && part.trim())
    .join(" ");
}

/**
 * Show the result card.
 * @param {string} colour - "checking", "green", "amber", "red" or "grey".
 * @param {string} name - The attendee's name, shown large; empty hides it.
 * @param {string} message - The message under it.
 * @param {string} action - "retry" for Try again, "reprint" for Reprint, empty for no button.
 * @returns {void} Nothing; names go in as text, never as HTML.
 */
function showCard(colour, name, message, action) {
  const card = element("card");
  card.className = `card ${colour}`;
  card.hidden = false;
  const nameLine = element("card-name");
  nameLine.textContent = name;
  nameLine.hidden = !name;
  element("card-message").textContent = message;
  cardAction = action;
  const button = /** @type {HTMLButtonElement} */ (element("card-action"));
  button.textContent = action === "reprint" ? TEXTS.reprint : TEXTS.tryAgain;
  button.hidden = !action;
  button.disabled = false;
}

/**
 * Do what the card's button says: resend the same request (Try again), or reprint the card's ticket.
 * No parameters.
 * @returns {void} Nothing.
 */
function onCardAction() {
  if (busy) {
    return;
  }
  unlockAudio();
  /** @type {HTMLButtonElement} */ (element("card-action")).disabled = true;
  if (cardAction === "retry" && lastRequest) {
    ask(lastRequest);
  } else if (cardAction === "reprint" && cardSecret) {
    ask(ticketRequest("/api/reprint", cardSecret));
  }
}

/**
 * Search 300 ms after the last keystroke once the text has 3 characters; shorter text clears the list.
 * No parameters.
 * @returns {void} Nothing.
 */
function onSearchInput() {
  window.clearTimeout(searchTimer);
  const text = /** @type {HTMLInputElement} */ (element("search")).value.trim();
  if (text.length < MIN_SEARCH) {
    searchSequence += 1;
    element("results").replaceChildren();
    showSearchMessage("");
    element("search-more").hidden = true;
    return;
  }
  searchTimer = window.setTimeout(() => runSearch(text), SEARCH_DELAY_MS);
}

/**
 * Run the search again with the field's text, so a check-in shows its ✓ at once.
 * No parameters.
 * @returns {void} Nothing.
 */
function refreshSearch() {
  const text = /** @type {HTMLInputElement} */ (element("search")).value.trim();
  if (text.length >= MIN_SEARCH) {
    runSearch(text);
  }
}

/**
 * Ask the API for attendees matching a text and list them; an answer older than the latest search is ignored.
 * @param {string} text - The search text, at least 3 characters.
 * @returns {Promise<void>} Resolves when the list or a message is shown.
 */
async function runSearch(text) {
  searchSequence += 1;
  const sequence = searchSequence;
  showSearchMessage(TEXTS.searching);
  const answer = await callApi("GET", `/api/search?q=${encodeURIComponent(text)}`);
  if (sequence !== searchSequence) {
    return;
  }
  if (answer.status === 401) {
    forgetPin();
    showPinScreen(TEXTS.wrongPin);
    return;
  }
  const body = answer.body;
  if (body && body.result === "ok" && Array.isArray(body.results)) {
    renderResults(body.results.filter(isSearchResult), body.more === true);
    return;
  }
  element("results").replaceChildren();
  element("search-more").hidden = true;
  showSearchMessage(body && typeof body.result === "string" && typeof body.message === "string" ? body.message : failureText(answer));
}

/**
 * Tell whether a value from the API is a usable search result.
 * @param {unknown} value - One item of the answer's results.
 * @returns {value is SearchResult} True when it has a secret and text fields.
 */
function isSearchResult(value) {
  const item = /** @type {any} */ (value);
  return Boolean(item) && typeof item.secret === "string" && item.secret !== "" && typeof item.order_code === "string";
}

/**
 * List the search results as rows to tap: a row not checked in checks the attendee in, a row checked in
 * reprints their sticker.
 * @param {SearchResult[]} results - The results.
 * @param {boolean} more - Whether pretix had more than 50 matches.
 * @returns {void} Nothing; names go in as text, never as HTML.
 */
function renderResults(results, more) {
  const rows = results.map((result) => {
    const name = [result.first_name, result.last_name].filter((part) => typeof part === "string" && part.trim()).join(" ");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "result";
    const nameLine = document.createElement("span");
    nameLine.className = "result-name";
    nameLine.textContent = name || TEXTS.noName;
    const detail = document.createElement("span");
    detail.className = "result-detail";
    const checkedIn = typeof result.checked_in_at === "string" ? `  ✓ ${result.checked_in_at.slice(11, 16)}` : "";
    detail.textContent = `${result.order_code}${checkedIn}`;
    button.append(nameLine, detail);
    button.addEventListener("click", () => {
      if (busy) {
        return;
      }
      unlockAudio();
      ask(ticketRequest(checkedIn ? "/api/reprint" : "/api/scan", result.secret));
    });
    const row = document.createElement("li");
    row.append(button);
    return row;
  });
  element("results").replaceChildren(...rows);
  showSearchMessage(rows.length ? "" : TEXTS.noMatches);
  element("search-more").hidden = !more;
}

/**
 * Show a line under the search field.
 * @param {string} text - The text; empty hides the line.
 * @returns {void} Nothing.
 */
function showSearchMessage(text) {
  const line = element("search-message");
  line.textContent = text;
  line.hidden = !text;
}

/**
 * Wire up the page and show the scan screen when a PIN is stored, otherwise the PIN screen.
 * No parameters.
 * @returns {void} Nothing.
 */
function init() {
  element("start").addEventListener("click", start);
  element("pin").addEventListener("keydown", (event) => {
    if (/** @type {KeyboardEvent} */ (event).key === "Enter") {
      start(event);
    }
  });
  element("change-pin").addEventListener("click", () => {
    forgetPin();
    element("card").hidden = true;
    element("results").replaceChildren();
    showPinScreen("");
  });
  element("card-action").addEventListener("click", onCardAction);
  element("tab-scan").addEventListener("click", () => showTab("scan"));
  element("tab-search").addEventListener("click", () => showTab("search"));
  element("search").addEventListener("input", onSearchInput);
  document.addEventListener("pointerdown", unlockAudio, { once: true });
  if (readPin()) {
    showApp();
  } else {
    showPinScreen("");
  }
}

init();
