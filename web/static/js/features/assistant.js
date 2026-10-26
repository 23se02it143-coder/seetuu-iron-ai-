// On-page chat wired to /api/assistant/message.
// Replies type out, come with follow-up chips, and can carry a button that jumps to the coach, diet planner, etc.
import { api, ApiError, track } from "../lib/api.js";
import { $, esc, icon, prefersReducedMotion } from "../lib/dom.js";

const MAX_TURNS = 11; // the API accepts 12 messages; keep room for the new one
const GREETING = "Hi, I'm IRON CORE. Ask me about form, warm-ups, recovery, diet or our plans. I can't diagnose injuries, and I'll tell you when something needs a clinician.";
const START_CHIPS = ["How should I warm up for squats?", "My lower back rounds on deadlifts", "Bulking diet plan", "What does Pro cost?"];

export async function initAssistant() {
  const log = $("#chat-log");
  const form = $("#chat-form");
  const input = $("#chat-input");
  const chips = $("#chat-chips");
  if (!log || !form) return;

  let history = [];
  let busy = false;
  let tracked = false;

  api("/api/config").then((cfg) => {
    $("#chat-mode").textContent = cfg.assistant_mode === "ai" ? "AI-powered training assistant" : "Guided training assistant";
  }).catch(() => {});

  const scroll = () => { log.scrollTop = log.scrollHeight; };

  function add(role, text, extraClass = "") {
    const el = document.createElement("div");
    el.className = `msg msg--${role === "user" ? "user" : "bot"} ${extraClass}`.trim();
    el.textContent = text;
    log.append(el);
    scroll();
    return el;
  }

  function setChips(list) {
    chips.innerHTML = list.slice(0, 4).map((c) => `<button type="button" class="chip">${esc(c)}</button>`).join("");
  }

  /** Type the reply out quickly (a few characters per frame). Reduced-motion users get it instantly. */
  function typeOut(el, text) {
    return new Promise((resolve) => {
      if (prefersReducedMotion() || text.length > 700) { el.textContent = text; return resolve(); }
      el.textContent = "";
      el.classList.add("is-typing");
      let i = 0;
      const tick = () => {
        i = Math.min(text.length, i + 3);
        el.textContent = text.slice(0, i);
        scroll();
        if (i < text.length) setTimeout(tick, 14); else { el.classList.remove("is-typing"); resolve(); }
      };
      tick();
    });
  }

  function actionButton(action) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip chip--action";
    b.innerHTML = `${icon(action.href ? "arrow-up-right" : "target")}${esc(action.label)}`;
    b.addEventListener("click", () => {
      track("cta_click");
      if (action.href) { location.href = action.href; return; }
      if (action.exercise) return void window.dispatchEvent(new CustomEvent("iron:coach", { detail: { exercise: action.exercise } }));
      if (action.target === "#diet" && action.goal) return void window.dispatchEvent(new CustomEvent("iron:diet", { detail: { goal: action.goal, weight: action.weight } }));
      document.querySelector(action.target)?.scrollIntoView({ behavior: "smooth" });
    });
    const wrap = document.createElement("div");
    wrap.className = "msg__actions";
    wrap.append(b);
    return wrap;
  }

  async function send(text) {
    text = text.trim();
    if (!text || busy) return;
    busy = true;
    add("user", text);
    history.push({ role: "user", content: text });
    input.value = "";
    setChips([]);

    const typing = document.createElement("div");
    typing.className = "msg msg--bot msg--typing";
    typing.setAttribute("aria-label", "IRON CORE is typing");
    typing.innerHTML = "<i></i><i></i><i></i>";
    log.append(typing);
    scroll();

    try {
      const res = await api("/api/assistant/message", { method: "POST", body: { messages: history.slice(-MAX_TURNS) } });
      typing.remove();
      const el = add("bot", "", res.flagged ? "msg--alert" : "");
      await typeOut(el, res.reply);
      if (res.action) el.append(actionButton(res.action));
      scroll();
      setChips(res.chips?.length ? res.chips : START_CHIPS);
      history.push({ role: "assistant", content: res.reply });
      if (!tracked) { tracked = true; track("assistant_used"); }
    } catch (err) {
      typing.remove();
      history.pop();
      add("bot", err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setChips(START_CHIPS);
    } finally {
      busy = false;
      input.focus({ preventScroll: true });
    }
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });
  chips.addEventListener("click", (e) => { const c = e.target.closest(".chip"); if (c) send(c.textContent); });
  setChips(START_CHIPS);

  // start over
  const foot = $(".chat__foot");
  if (foot) {
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "chat__clear";
    clear.textContent = "Clear chat";
    clear.addEventListener("click", () => {
      history = [];
      log.innerHTML = "";
      add("bot", GREETING);
      setChips(START_CHIPS);
    });
    foot.append(clear);
  }

  // voice input where the browser supports it
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (Recognition) {
    const mic = document.createElement("button");
    mic.type = "button";
    mic.className = "chat__mic";
    mic.setAttribute("aria-label", "Speak your question");
    mic.setAttribute("aria-pressed", "false");
    mic.innerHTML = icon("broadcast");
    form.insertBefore(mic, form.querySelector(".chat__send"));
    let rec = null;
    mic.addEventListener("click", () => {
      if (rec) { rec.stop(); return; }
      rec = new Recognition();
      rec.lang = "en-IN";
      rec.interimResults = false;
      rec.onstart = () => mic.setAttribute("aria-pressed", "true");
      rec.onresult = (e) => { input.value = e.results[0][0].transcript; send(input.value); };
      rec.onend = () => { mic.setAttribute("aria-pressed", "false"); rec = null; };
      rec.onerror = () => { mic.setAttribute("aria-pressed", "false"); rec = null; };
      rec.start();
    });
  }
}
