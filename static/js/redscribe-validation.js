(function () {
  "use strict";

  var SKIP_TYPES = ["submit", "button", "reset", "image", "hidden"];

  function isValidatable(field) {
    if (typeof field.checkValidity !== "function") return false;
    if (field.disabled || field.hasAttribute("data-no-validate")) return false;
    if (SKIP_TYPES.indexOf(field.type) !== -1) return false;
    return true;
  }

  function labelFor(field) {
    if (field.id) {
      var label = field.form && field.form.querySelector('label[for="' + cssEscape(field.id) + '"]');
      if (label) return label.textContent.replace(/\s+/g, " ").trim();
    }
    return (field.name || "This field").replace(/_/g, " ");
  }

  function cssEscape(id) {
    return window.CSS && CSS.escape ? CSS.escape(id) : id.replace(/([^\w-])/g, "\\$1");
  }

  function fieldByIdRef(field, id) {
    return field.form ? field.form.querySelector("#" + cssEscape(id)) : null;
  }

  function password1CounterpartId(field) {
    var m = /^(.*password)2$/i.exec(field.id || "");
    return m ? m[1] + "1" : null;
  }

  function messageFor(field) {
    var v = field.validity;
    if (v.valid) return "";

    if (v.valueMissing) return field.getAttribute("data-error-required") || (labelFor(field) + " is required.");
    if (v.typeMismatch) {
      if (field.type === "email") return field.getAttribute("data-error-type") || "Enter a valid email address.";
      if (field.type === "url") return field.getAttribute("data-error-type") || "Enter a valid URL.";
      return field.getAttribute("data-error-type") || field.validationMessage;
    }
    if (v.tooShort) return field.getAttribute("data-error-length") || (labelFor(field) + " must be at least " + field.minLength + " characters.");
    if (v.tooLong) return field.getAttribute("data-error-length") || (labelFor(field) + " must be no more than " + field.maxLength + " characters.");
    if (v.rangeUnderflow) return field.getAttribute("data-error-range") || (labelFor(field) + " must be " + field.min + " or more.");
    if (v.rangeOverflow) return field.getAttribute("data-error-range") || (labelFor(field) + " must be " + field.max + " or less.");
    if (v.stepMismatch || v.badInput) return field.getAttribute("data-error-type") || field.validationMessage || (labelFor(field) + " is not valid.");
    if (v.patternMismatch) return field.getAttribute("data-error-pattern") || (labelFor(field) + " is not in the expected format.");
    return field.validationMessage || (labelFor(field) + " is not valid.");
  }

  function crossFieldError(field) {
    var matchId = field.getAttribute("data-match") || password1CounterpartId(field);
    if (matchId) {
      var other = fieldByIdRef(field, matchId);
      if (other && field.value && other.value && field.value !== other.value) {
        return field.getAttribute("data-error-match") || ("Doesn't match " + labelFor(other) + ".");
      }
    }

    var afterId = field.getAttribute("data-after");
    if (!afterId && (field.name === "end_date" || field.id === "id_end_date")) {
      var candidate = fieldByIdRef(field, "id_start_date") ||
        (field.form ? field.form.querySelector('[name="start_date"]') : null);
      if (candidate) afterId = candidate.id;
    }
    if (afterId) {
      var ref = fieldByIdRef(field, afterId);
      if (ref && field.value && ref.value && field.value < ref.value) {
        return field.getAttribute("data-error-after") || ("Can't be earlier than " + labelFor(ref) + ".");
      }
    }

    return "";
  }

  function visibleAnchor(field) {
    return (field._flatpickr && field._flatpickr.altInput) || field;
  }

  function errorNodeFor(field) {
    var el = visibleAnchor(field).nextElementSibling;
    if (el && el.classList && el.classList.contains("field-error")) return el;
    return null;
  }

  function showError(field, message) {
    var anchor = visibleAnchor(field);
    anchor.classList.add("is-invalid");
    field.setAttribute("aria-invalid", "true");
    var node = errorNodeFor(field);
    if (!node) {
      node = document.createElement("p");
      node.className = "field-error";
      anchor.insertAdjacentElement("afterend", node);
    }
    node.textContent = message;
    if (!field.id) field.id = "field-" + Math.random().toString(36).slice(2);
    node.id = field.id + "-error";
    field.setAttribute("aria-describedby", node.id);
  }

  function clearError(field) {
    visibleAnchor(field).classList.remove("is-invalid");
    field.removeAttribute("aria-invalid");
    field.removeAttribute("aria-describedby");
    var node = errorNodeFor(field);
    if (node) node.remove();
  }

  function validateField(field, show) {
    if (!isValidatable(field)) return true;

    field.setCustomValidity("");
    var native = !field.checkValidity();
    var message = native ? messageFor(field) : crossFieldError(field);
    var valid = !message;

    if (!show && !field.hasAttribute("data-touched")) return valid;

    if (valid) {
      clearError(field);
    } else {
      showError(field, message);
    }
    return valid;
  }

  function attachForm(form) {
    if (form.hasAttribute("data-no-validate") || form.hasAttribute("data-validation-bound")) return;
    form.setAttribute("data-validation-bound", "1");
    form.setAttribute("novalidate", "novalidate");

    var fields = form.querySelectorAll("input, select, textarea");
    fields.forEach(function (field) {
      if (!isValidatable(field)) return;
      field.addEventListener("blur", function () {
        field.setAttribute("data-touched", "1");
        validateField(field, true);
      });
      field.addEventListener("input", function () {
        if (field.hasAttribute("data-touched")) validateField(field, true);
      });
      field.addEventListener("change", function () {
        if (field.hasAttribute("data-touched")) validateField(field, true);
      });
    });

    form.addEventListener("submit", function (e) {
      var firstInvalid = null;
      fields.forEach(function (field) {
        field.setAttribute("data-touched", "1");
        if (!validateField(field, true) && !firstInvalid) firstInvalid = field;
      });
      if (firstInvalid) {
        e.preventDefault();
        firstInvalid.focus();
        if (firstInvalid.scrollIntoView) firstInvalid.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
  }

  function init() {
    document.querySelectorAll("form").forEach(attachForm);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
