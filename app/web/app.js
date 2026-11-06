// Copyright (c) 2026-2027 Michal Salanci
// SPDX-License-Identifier: MIT

// @ts-check
/**
 * The scanner page's script: the staff PIN, reading ticket QR codes with html5-qrcode, and the result card.
 *
 * Loaded by index.html after vendor/html5-qrcode.min.js. It calls POST /api/scan on its own origin with the
 * scanned text, a new nonce and the X-Staff-Pin header, and shows the answer's message on a coloured card.
 * The PIN is kept in localStorage under cdr.staffPin, or in memory when the browser refuses storage.
 */

const PIN_KEY = "cdr.staffPin";
const ANSWER_TIMEOUT_MS = 12000;
const RESUME_AFTER_MS = 2000;
const SAME_TICKET_MS = 10000;
const TEXTS = {
  checking: "Checking…",
  noAnswer: "No answer — try again",
  tooMany: "Too many scans at once — try again",
  wentWrong: "Something went wrong — try again",
  wrongPin: "Wrong PIN",
  tryAgain: "Try again",
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
const FEEDBACK = {
  green: { vibrate: [120], beeps: [[880, 0.15]] },
  amber: { vibrate: [120, 90, 120], beeps: [[660, 0.12], [660, 0.12]] },
  red: { vibrate: [120, 90, 120, 90, 120], beeps: [[220, 0.45]] },
};

/** @typedef {{ path: string, body: { secret: string, nonce: string } }} ApiRequest */
/** @typedef {{ result?: unknown, message?: unknown, attendee?: { first_name?: unknown, last_name?: unknown } }} ApiBody */

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
 * Show the scan screen and start the camera.
 * No parameters.
 * @returns {void} Nothing.
 */
function showApp() {
  element("pin-screen").hidden = true;
  element("app").hidden = false;
  startCamera();
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
 * Handle a QR code the camera read: ignore it while busy or when it is the ticket just shown, else scan it.
 * @param {string} text - The QR code's text, the ticket secret.
 * @returns {void} Nothing.
 */
function onRead(text) {
  if (busy) {
    return;
  }
  if (text === lastTicket && Date.now() - lastTicketAt < SAME_TICKET_MS) {
    return;
  }
  ask({ path: "/api/scan", body: { secret: text, nonce: crypto.randomUUID() } });
}

/**
 * Send a request with the camera paused, show its card, and resume the camera 2 s after the answer.
 * @param {ApiRequest} request - The request; Try again sends it unchanged, with the same nonce.
 * @returns {Promise<void>} Resolves when the card shows the answer.
 */
async function ask(request) {
  busy = true;
  lastRequest = request;
  setPaused(true);
  showCard("checking", "", TEXTS.checking, "");
  const answer = await callApi(request);
  if (answer.status === 401) {
    busy = false;
    forgetPin();
    showPinScreen(TEXTS.wrongPin);
    return;
  }
  lastTicket = request.body.secret;
  lastTicketAt = Date.now();
  render(answer);
  window.setTimeout(() => {
    busy = false;
    setPaused(false);
  }, RESUME_AFTER_MS);
}

/**
 * Call the API and read its answer, giving up after 12 s.
 * @param {ApiRequest} request - The path and JSON body.
 * @returns {Promise<{ status: number, body: ApiBody | null }>} The HTTP status (0 for no answer) and the JSON body, if any.
 */
async function callApi(request) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), ANSWER_TIMEOUT_MS);
  try {
    const response = await fetch(request.path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Staff-Pin": readPin() },
      body: JSON.stringify(request.body),
      signal: controller.signal,
      cache: "no-store",
      credentials: "omit",
    });
    let body = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    return { status: response.status, body };
  } catch {
    return { status: 0, body: null };
  } finally {
    window.clearTimeout(timer);
  }
}

/**
 * Turn an answer into its card: the API's own message only when the body has a result.
 * @param {{ status: number, body: ApiBody | null }} answer - The HTTP status and JSON body.
 * @returns {void} Nothing.
 */
function render(answer) {
  const body = answer.body;
  if (body && typeof body.result === "string") {
    const colour = COLOURS[/** @type {keyof typeof COLOURS} */ (body.result)] || "grey";
    const message = typeof body.message === "string" ? body.message : TEXTS.wentWrong;
    showCard(colour, attendeeName(body), message, colour === "grey" ? TEXTS.tryAgain : "");
    feedback(colour);
    return;
  }
  let text = TEXTS.wentWrong;
  if (answer.status === 0) {
    text = TEXTS.noAnswer;
  } else if (answer.status === 429) {
    text = TEXTS.tooMany;
  }
  showCard("grey", "", text, TEXTS.tryAgain);
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
 * @param {string} action - The button's label, such as "Try again"; empty hides the button.
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
  const button = /** @type {HTMLButtonElement} */ (element("card-action"));
  button.textContent = action;
  button.hidden = !action;
  button.disabled = false;
}

/**
 * Resend the last request with the same body and nonce, from the card's Try again button.
 * No parameters.
 * @returns {void} Nothing.
 */
function tryAgain() {
  if (!lastRequest || busy) {
    return;
  }
  unlockAudio();
  /** @type {HTMLButtonElement} */ (element("card-action")).disabled = true;
  ask(lastRequest);
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
    showPinScreen("");
  });
  element("card-action").addEventListener("click", tryAgain);
  document.addEventListener("pointerdown", unlockAudio, { once: true });
  if (readPin()) {
    showApp();
  } else {
    showPinScreen("");
  }
}

init();
