// Phone only: tap an exercise in the library to reveal its form cue (the CSS hides cues on small screens).
// Harmless on larger screens: the rule that hides cues does not apply there, so toggling the class changes nothing.
document.addEventListener("click", (e) => {
  const li = e.target instanceof Element ? e.target.closest(".libcard__list li") : null;
  if (li) li.classList.toggle("is-open");
});
