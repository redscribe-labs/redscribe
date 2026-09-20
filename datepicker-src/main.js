import flatpickr from "flatpickr";

function initAll(root) {
    (root || document).querySelectorAll("[data-redscribe-datepicker]").forEach(function (el) {
        if (el._flatpickr) return;
        flatpickr(el, {
            dateFormat: "Y-m-d",
            altInput: true,
            altFormat: "d/m/Y",
            altInputClass: el.className || "field-input",
            allowInput: true,
        });
    });
}

document.addEventListener("DOMContentLoaded", function () {
    initAll();
});

window.RedscribeDatepicker = { init: initAll };
