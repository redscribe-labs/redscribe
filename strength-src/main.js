import { ZxcvbnFactory } from "@zxcvbn-ts/core";
import * as zxcvbnCommonPackage from "@zxcvbn-ts/language-common";
import * as zxcvbnEnPackage from "@zxcvbn-ts/language-en";

// zxcvbn-ts 4 removed the top-level zxcvbn()/zxcvbnOptions singleton in
// favour of a factory: build it once with the same options object (the
// language packages still export dictionary/adjacencyGraphs/translations
// under those names), then call .check() per password below.
const zxcvbn = new ZxcvbnFactory({
  dictionary: {
    ...zxcvbnCommonPackage.dictionary,
    ...zxcvbnEnPackage.dictionary,
  },
  graphs: zxcvbnCommonPackage.adjacencyGraphs,
  translations: zxcvbnEnPackage.translations,
});

const LEVELS = [
  { label: "Very weak", className: "is-weak" },
  { label: "Weak", className: "is-weak" },
  { label: "Fair", className: "is-fair" },
  { label: "Good", className: "is-good" },
  { label: "Strong", className: "is-strong" },
];

function buildMeter(input) {
  const wrapper = document.createElement("div");
  wrapper.className = "password-strength";
  wrapper.innerHTML = `
    <div class="password-strength-track"><div class="password-strength-fill"></div></div>
    <p class="password-strength-label"></p>
  `;
  input.insertAdjacentElement("afterend", wrapper);
  return {
    fill: wrapper.querySelector(".password-strength-fill"),
    label: wrapper.querySelector(".password-strength-label"),
  };
}

function attach(input) {
  const { fill, label } = buildMeter(input);

  input.addEventListener("input", () => {
    const value = input.value;
    if (!value) {
      fill.style.width = "0%";
      fill.className = "password-strength-fill";
      label.textContent = "";
      return;
    }

    const result = zxcvbn.check(value);
    const level = LEVELS[result.score];
    fill.style.width = `${((result.score + 1) / LEVELS.length) * 100}%`;
    fill.className = `password-strength-fill ${level.className}`;

    const warning = result.feedback.warning ? ` — ${result.feedback.warning}` : "";
    label.textContent = `${level.label}${warning}`;
  });
}

document.querySelectorAll('input[type="password"][id$="password1"]').forEach(attach);
