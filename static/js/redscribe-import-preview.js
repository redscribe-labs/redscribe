// Import confirm step. When a file is chosen, the form is sent with preview=1
// and the server answers with the rows it would create (nothing is saved).
// The rows' checkboxes sit inside the form, so the final submit imports only
// the ticked ones. Without JS the form imports everything, as before.
(function () {
  "use strict";

  function init(form) {
    const target = form.querySelector("[data-preview-target]");
    const submit = form.querySelector("[data-import-submit]");
    const file = form.querySelector("input[type=file]");
    if (!target || !submit || !file) return;
    const csrf = form.querySelector("[name=csrfmiddlewaretoken]");
    let request = 0;

    function updateSubmit() {
      const boxes = target.querySelectorAll("input[name=include]");
      if (!boxes.length) {
        submit.textContent = "Import";
        submit.disabled = !!target.querySelector("[role=alert]");
        return;
      }
      const ticked = target.querySelectorAll("input[name=include]:checked").length;
      submit.textContent = ticked ? `Import ${ticked} selected` : "Tick at least one to import";
      submit.disabled = ticked === 0;
      const all = target.querySelector("[data-preview-all]");
      if (all) {
        all.checked = ticked === boxes.length;
        all.indeterminate = ticked > 0 && ticked < boxes.length;
      }
    }

    async function preview() {
      if (!file.files.length) { target.innerHTML = ""; updateSubmit(); return; }
      const mine = ++request;
      target.innerHTML = '<p class="text-sm text-slate-500">Reading file…</p>';
      submit.disabled = true;
      const data = new FormData(form);
      data.set("preview", "1");
      data.delete("selection");
      data.delete("include");
      try {
        const response = await fetch(form.action || window.location.href, {
          method: "POST", body: data, credentials: "same-origin",
          headers: { "X-CSRFToken": csrf ? csrf.value : "" },
        });
        const html = await response.text();
        if (mine !== request) return;
        target.innerHTML = html;
      } catch (err) {
        if (mine !== request) return;
        target.innerHTML = "";  // fall back to importing everything
      }
      updateSubmit();
    }

    form.addEventListener("change", (e) => {
      if (e.target === file || e.target.name === "format") { preview(); return; }
      if (e.target.matches("[data-preview-all]")) {
        target.querySelectorAll("input[name=include]").forEach((box) => { box.checked = e.target.checked; });
      }
      updateSubmit();
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("form[data-import-preview]").forEach(init);
  });
})();
