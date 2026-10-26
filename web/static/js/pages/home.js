import "../shell.js";
import { startLightning } from "../lib/lightning.js";
import { prefersReducedMotion } from "../lib/dom.js";
import { track } from "../lib/api.js";
import { initWaitlist } from "../features/waitlist.js";
import { initAssistant } from "../features/assistant.js";
import { initAssessment } from "../features/assessment.js";
import { initPrograms, initPricing, initStories } from "../features/catalog.js";
import { initFormLab } from "../features/formlab.js";
import { initLibrary } from "../features/library.js";
import { initContact } from "../features/contact.js";
import { initStatus, initTicker } from "../features/status.js";
import { initFormCoach } from "../features/formcoach.js";
import { initDiet } from "../features/diet.js";
import { initEffects } from "../features/effects.js";

const canvas = document.getElementById("hero-canvas");
if (canvas) startLightning(canvas, { reducedMotion: prefersReducedMotion() || window.matchMedia("(max-width: 640px)").matches }); // phones: one still frame, saves battery and CPU

initWaitlist();
initAssistant();
initAssessment();
initPrograms();
initPricing();
initStories();
initContact();
initFormLab();
initFormCoach();
initLibrary();
initDiet();
initEffects();
initStatus();
initTicker();
track("page_view");
