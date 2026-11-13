// SPDX-License-Identifier: Apache-2.0
// Theme toggle + tiny helpers. No build step, no framework.
(function () {
  "use strict";

  var STORAGE_KEY = "metadatarr-theme";

  function applyTheme(theme) {
    if (theme === "light" || theme === "dark") {
      document.documentElement.dataset.theme = theme;
    } else {
      delete document.documentElement.dataset.theme;
    }
  }

  function currentTheme() {
    return localStorage.getItem(STORAGE_KEY) || "auto";
  }

  function cycleTheme() {
    var order = ["auto", "dark", "light"];
    var next = order[(order.indexOf(currentTheme()) + 1) % order.length];
    localStorage.setItem(STORAGE_KEY, next);
    applyTheme(next);
    updateToggleLabel(next);
  }

  function updateToggleLabel(theme) {
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;
    btn.textContent = theme === "dark" ? "🌙" : theme === "light" ? "☀️" : "🖥️";
    btn.setAttribute("aria-label", "Theme: " + theme + " (click to change)");
  }

  document.addEventListener("DOMContentLoaded", function () {
    applyTheme(currentTheme());
    updateToggleLabel(currentTheme());
    var btn = document.getElementById("theme-toggle");
    if (btn) btn.addEventListener("click", cycleTheme);

    var dot = document.getElementById("health-dot");
    if (dot) {
      document.body.addEventListener("htmx:afterRequest", function (evt) {
        if (evt.detail && evt.detail.elt === dot) {
          dot.classList.toggle("ok", evt.detail.successful);
          dot.classList.toggle("err", !evt.detail.successful);
        }
      });
    }
  });
})();
