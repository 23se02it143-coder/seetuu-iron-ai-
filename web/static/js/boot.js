// Runs before first paint: flags JS availability so CSS can differ, without inline scripts (CSP).
document.documentElement.classList.replace("no-js", "js");
