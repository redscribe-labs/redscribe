// Background save for forms with data-autosave-url. Every couple of seconds it
// compares the form's fields with the last saved copy and, once typing has
// paused, posts the changes. The server refuses (409) if someone else saved
// first; autosave then stops so nothing is overwritten.
(function () {
  "use strict";

  const IDLE_MS = 1500;

  function snapshot(form) {
    const data = new FormData(form);
    data.delete("save_item");
    return new URLSearchParams(data).toString();
  }

  function init(form) {
    const url = form.dataset.autosaveUrl;
    const status = form.querySelector("[data-autosave-status]");
    const version = form.querySelector("[data-autosave-version]");
    const csrf = form.querySelector("[name=csrfmiddlewaretoken]");
    let saved = snapshot(form);
    let lastChange = 0;
    let pending = null;
    let inFlight = false;
    let stopped = false;

    function say(text) { if (status) status.textContent = text; }

    form.addEventListener("input", () => { lastChange = Date.now(); });
    form.addEventListener("change", () => { lastChange = Date.now(); });
    form.addEventListener("submit", () => { stopped = true; });
    window.addEventListener("beforeunload", (e) => {
      if (!stopped && lastChange && snapshot(form) !== saved) { e.preventDefault(); }
    });

    async function save() {
      const current = snapshot(form);
      if (!lastChange || current === saved || inFlight || stopped) return;
      if (Date.now() - lastChange < IDLE_MS) return;
      inFlight = true;
      pending = current;
      say("Saving…");
      try {
        const response = await fetch(url, {
          method: "POST",
          body: new URLSearchParams(new FormData(form)),
          headers: { "X-CSRFToken": csrf ? csrf.value : "", "X-Requested-With": "XMLHttpRequest" },
          credentials: "same-origin",
        });
        const body = await response.json().catch(() => ({}));
        if (response.ok && body.saved) {
          saved = pending;
          if (version) version.value = body.version;
          say("Saved " + body.saved_at);
        } else if (response.status === 409) {
          stopped = true;
          say((body.message || "Someone else saved this check after you opened it.") + " Press Save to review.");
        } else if (response.status === 400) {
          say("Not saved yet: fix the highlighted fields and press Save.");
          saved = pending;  // don't retry the same invalid input in a loop
        } else {
          say("Couldn't save automatically. Your changes are still here.");
        }
      } catch (err) {
        say("Offline? Your changes are still here; they'll save when you reconnect.");
      } finally {
        inFlight = false;
      }
    }

    // The editor script loads first and fills its hidden inputs on
    // DOMContentLoaded, so the baseline above already includes them.
    setInterval(save, 1000);
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("form[data-autosave-url]").forEach(init);
  });
})();
