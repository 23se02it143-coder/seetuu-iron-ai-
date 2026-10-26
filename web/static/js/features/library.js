// Exercise library: a static reference grid fetched from /api/exercise-library and grouped by muscle.
// The handful of exercises the camera coach can watch live get a "Coach this lift" button that opens it,
// the same iron:coach event catalog.js and assistant.js already use.
import { api } from "../lib/api.js";
import { $, esc, icon } from "../lib/dom.js";

export async function initLibrary() {
  const grid = $("#library-grid");
  if (!grid) return;
  try {
    const { groups } = await api("/api/exercise-library");
    grid.innerHTML = groups.map(groupCard).join("");
    grid.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-coach]");
      if (!btn) return;
      window.dispatchEvent(new CustomEvent("iron:coach", { detail: { exercise: btn.dataset.coach } }));
    });
  } catch {
    grid.innerHTML = `<p class="muted">The exercise library couldn't load. Refresh the page to try again.</p>`;
  }
}

function groupCard(g) {
  return `<article class="libcard">
    <h3 class="libcard__title">${esc(g.group)}</h3>
    <p class="libcard__blurb">${esc(g.blurb)}</p>
    <ul class="libcard__list">${g.exercises.map(exRow).join("")}</ul>
  </article>`;
}

function exRow(e) {
  return `<li>
    <div class="libcard__row"><b>${esc(e.name)}</b><span>${esc(e.sets)}</span></div>
    <p class="libcard__cue">${esc(e.cue)}</p>
    ${e.coach ? `<button type="button" class="chip chip--action" data-coach="${esc(e.coach)}">${icon("camera")}Coach this lift</button>` : ""}
  </li>`;
}
