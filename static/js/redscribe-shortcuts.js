// Keyboard shortcuts. Any element with data-shortcut="<key>" (and a
// data-shortcut-label) is clicked when that key is pressed: "j", "1", "[",
// or "mod+enter" / "mod+k", where mod is ⌘ on a Mac and Ctrl elsewhere.
// Single keys are ignored while typing; mod combinations work everywhere.
// "?" opens a dialog listing what the current page offers.
(function () {
  "use strict";

  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  const dialog = document.getElementById("shortcuts-dialog");

  function typing(target) {
    if (!target || !(target instanceof Element)) return false;
    if (target.isContentEditable) return true;
    if (target.matches("textarea, select")) return true;
    return target.matches("input") && !["checkbox", "radio", "button", "submit", "reset"].includes(target.type);
  }

  function comboFor(e) {
    const mod = isMac ? e.metaKey : e.ctrlKey;
    const key = e.key === "Enter" ? "enter" : e.key.toLowerCase();
    return (mod ? "mod+" : "") + key;
  }

  function visible(el) {
    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  }

  function targets() {
    return Array.from(document.querySelectorAll("[data-shortcut]")).filter((el) => !el.disabled && visible(el.closest("label") || el));
  }

  function keyNames(combo) {
    return combo.split("+").map((part) => {
      if (part === "mod") return isMac ? "⌘" : "Ctrl";
      if (part === "enter") return "↵";
      return part.length === 1 ? part.toUpperCase() : part;
    });
  }

  function openHelp() {
    if (!dialog) return;
    const list = dialog.querySelector("[data-shortcuts-list]");
    const rowTpl = document.getElementById("shortcuts-row");
    const keyTpl = document.getElementById("shortcuts-key");
    list.replaceChildren();
    const seen = new Set();
    const entries = targets().map((el) => [el.dataset.shortcut, el.dataset.shortcutLabel || el.textContent.trim()]);
    entries.push(["?", "Show this list"]);
    for (const [combo, label] of entries) {
      if (seen.has(combo)) continue;
      seen.add(combo);
      const row = rowTpl.content.firstElementChild.cloneNode(true);
      row.querySelector("[data-label]").textContent = label;
      for (const name of keyNames(combo)) {
        const kbd = keyTpl.content.firstElementChild.cloneNode(true);
        kbd.textContent = name;
        row.querySelector("[data-keys]").appendChild(kbd);
      }
      list.appendChild(row);
    }
    dialog.showModal();
  }

  if (dialog) {
    dialog.querySelector("[data-shortcuts-close]").addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
  }
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-shortcuts-open]")) openHelp();
  });

  // Show the platform's modifier in hints like <kbd data-mod-key>.
  document.querySelectorAll("[data-mod-key]").forEach((el) => { el.textContent = isMac ? "⌘" : "Ctrl"; });

  document.addEventListener("keydown", (e) => {
    if (e.defaultPrevented || e.altKey || e.isComposing) return;
    if (document.querySelector("dialog[open]")) return;
    const combo = comboFor(e);
    const withMod = combo.startsWith("mod+");
    if (!withMod && (e.ctrlKey || e.metaKey)) return;
    if (!withMod && typing(e.target)) return;
    if (combo === "?" && !withMod) {
      e.preventDefault();
      openHelp();
      return;
    }
    const target = targets().find((el) => el.dataset.shortcut === combo);
    if (!target) return;
    e.preventDefault();
    if (target.matches("input[type=radio], input[type=checkbox]")) target.focus();
    target.click();
  });
})();
