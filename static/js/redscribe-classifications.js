(function () {
  function loadSuggestions() {
    const el = document.getElementById("classification-suggestions-data");
    if (!el) return {};
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return {};
    }
  }

  const suggestions = loadSuggestions();

  function valuesFor(taxonomy) {
    const needle = taxonomy.trim().toLowerCase();
    if (!needle) return [];
    const key = Object.keys(suggestions).find((t) => t.toLowerCase() === needle);
    return key ? suggestions[key] : [];
  }

  function setup(field) {
    const chipsContainer = field.querySelector("[data-classification-chips]");
    const chipTemplate = field.querySelector("template[data-classification-chip-template]");
    const taxonomyInput = field.querySelector("[data-classification-taxonomy-input]");
    const valueInput = field.querySelector("[data-classification-value-input]");
    const addBtn = field.querySelector("[data-add-classification]");

    const valueDatalist = document.createElement("datalist");
    valueDatalist.id = "classification-value-suggestions";
    field.appendChild(valueDatalist);
    valueInput.setAttribute("list", valueDatalist.id);

    function syncValueSuggestions() {
      valueDatalist.innerHTML = "";
      valuesFor(taxonomyInput.value).forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        valueDatalist.appendChild(option);
      });
    }
    taxonomyInput.addEventListener("input", syncValueSuggestions);
    syncValueSuggestions();

    function wireChip(chip) {
      chip.querySelector("[data-remove-classification-chip]").addEventListener("click", () => chip.remove());
    }
    chipsContainer.querySelectorAll("[data-classification-chip]").forEach(wireChip);

    function addChip() {
      const taxonomy = taxonomyInput.value.trim();
      const value = valueInput.value.trim();
      if (!taxonomy || !value) return;

      const chip = chipTemplate.content.firstElementChild.cloneNode(true);
      const [taxonomyHidden, valueHidden] = chip.querySelectorAll("input[type=hidden]");
      taxonomyHidden.value = taxonomy;
      valueHidden.value = value;
      const label = chip.querySelector("span");
      label.textContent = value;
      label.title = taxonomy;
      wireChip(chip);
      chipsContainer.appendChild(chip);

      taxonomyInput.value = "";
      valueInput.value = "";
      syncValueSuggestions();
      taxonomyInput.focus();
    }

    addBtn.addEventListener("click", addChip);
    [taxonomyInput, valueInput].forEach((input) => {
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          addChip();
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-classification-chips]").forEach((chipsContainer) => {
      setup(chipsContainer.parentElement);
    });
  });
})();
