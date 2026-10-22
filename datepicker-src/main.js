import flatpickr from "flatpickr";

// flatpickr shows a second, visible input and hides the original, so a
// <label for> pointing at the original no longer names anything visible.
// Point the label at the visible input instead (or copy its text across).
function labelAltInput(original, alt) {
    if (!alt) return;
    var label = original.id ? document.querySelector('label[for="' + original.id + '"]') : null;
    if (label) {
        alt.id = original.id + "-display";
        label.htmlFor = alt.id;
        return;
    }
    var container = original.parentElement;
    var nearby = container ? container.querySelector("label") : null;
    var text = original.getAttribute("aria-label") || (nearby && nearby.textContent.trim());
    if (text) alt.setAttribute("aria-label", text);
}

function initAll(root) {
    (root || document).querySelectorAll("[data-redscribe-datepicker]").forEach(function (el) {
        if (el._flatpickr) return;
        flatpickr(el, {
            dateFormat: "Y-m-d",
            altInput: true,
            altFormat: "d/m/Y",
            altInputClass: el.className || "field-input",
            allowInput: true,
            onReady: function (_dates, _str, instance) { labelAltInput(el, instance.altInput); },
        });
    });
}

document.addEventListener("DOMContentLoaded", function () {
    initAll();
});

window.RedscribeDatepicker = { init: initAll };
