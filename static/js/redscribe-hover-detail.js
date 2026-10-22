// Hover/focus detail line for dense visuals (checklist posture map, trend
// charts). An element with data-detail="text" and data-detail-for="<id>"
// writes its text into #<id> while hovered or focused. The same text is
// always in the element's own aria-label/title, so this is a convenience.
(function () {
  var initial = {};

  function target(el) {
    var id = el.getAttribute("data-detail-for");
    var box = id && document.getElementById(id);
    if (box && !(id in initial)) initial[id] = box.textContent;
    return box;
  }

  function show(event) {
    var el = event.target.closest("[data-detail][data-detail-for]");
    var box = el && target(el);
    if (!box) return;
    box.textContent = el.getAttribute("data-detail");
    box.classList.add("text-slate-900");
  }

  function reset(event) {
    var el = event.target.closest("[data-detail][data-detail-for]");
    if (!el || el.contains(event.relatedTarget)) return;
    var box = target(el);
    if (!box) return;
    box.textContent = initial[el.getAttribute("data-detail-for")];
    box.classList.remove("text-slate-900");
  }

  document.addEventListener("mouseover", show);
  document.addEventListener("focusin", show);
  document.addEventListener("mouseout", reset);
  document.addEventListener("focusout", reset);
})();
