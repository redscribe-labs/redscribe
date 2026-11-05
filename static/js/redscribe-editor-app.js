(function () {

  // Toolbar buttons show a short glyph ("B", "H1", "+Row"); screen readers get
  // the full name as hidden text instead, so the glyph isn't read out and the
  // accessible name isn't a label that contradicts what's on screen.
  function buttonFace(btn, glyph, name) {
    const visible = document.createElement("span");
    visible.setAttribute("aria-hidden", "true");
    visible.textContent = glyph;
    const spoken = document.createElement("span");
    spoken.className = "sr-only";
    spoken.textContent = name;
    btn.replaceChildren(visible, spoken);
    btn.title = name;
  }

  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
    return match ? decodeURIComponent(match[2]) : null;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  async function uploadImage(uploadUrl, file) {
    const formData = new FormData();
    formData.append("file", file);
    const resp = await fetch(uploadUrl, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken") },
      body: formData,
    });
    if (!resp.ok) throw new Error("Image upload failed: " + (await resp.text()));
    const data = await resp.json();
    return data.url;
  }

  function toast(message, tag) {
    if (window.RedscribeToast) window.RedscribeToast.show(message, tag);
  }

  async function postJson(url, payload) {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) throw new Error("Request failed: " + (await resp.text()));
    return resp.json();
  }

  const mobileQuery = window.matchMedia("(max-width: 767px)");
  const isMobile = () => mobileQuery.matches;

  // One thread, rendered as a card: quoted text, entries, and a reply form
  // with resolve/delete. Used inside the floating/bottom-sheet surface.
  function buildThreadCard(thread, { onReply, onToggleResolve, onDelete }) {
    const card = document.createElement("div");
    card.className = "rte-thread-card" + (thread.resolved ? " rte-thread-resolved" : "");
    card.dataset.threadId = thread.id;

    const quote = document.createElement("blockquote");
    quote.className = "rte-thread-quote";
    quote.textContent = thread.anchored_text;
    card.appendChild(quote);

    for (const entry of thread.entries) {
      const entryEl = document.createElement("div");
      entryEl.className = "rte-thread-entry";
      entryEl.innerHTML =
        `<span class="rte-thread-author">${escapeHtml(entry.author || "Unknown")}</span> ` +
        `<span class="rte-thread-time">${escapeHtml(new Date(entry.created_at).toLocaleString())}</span>` +
        `<p>${escapeHtml(entry.body)}</p>`;
      card.appendChild(entryEl);
    }

    const replyForm = document.createElement("form");
    replyForm.className = "rte-reply-form";
    replyForm.innerHTML =
      '<textarea rows="2" class="field-input" placeholder="Reply..." aria-label="Reply to comment"></textarea>' +
      '<div class="rte-thread-actions">' +
      '<button type="submit" class="btn-primary">Reply</button> ' +
      `<button type="button" class="btn-secondary rte-resolve-btn">${thread.resolved ? "Reopen" : "Resolve"}</button>` +
      (thread.can_delete ? ' <button type="button" class="btn-secondary rte-delete-btn">Delete</button>' : "") +
      "</div>";
    replyForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const textarea = replyForm.querySelector("textarea");
      if (!textarea.value.trim()) return;
      onReply(textarea.value.trim());
    });
    replyForm.querySelector(".rte-resolve-btn").addEventListener("click", () => onToggleResolve());
    const deleteBtn = replyForm.querySelector(".rte-delete-btn");
    if (deleteBtn) {
      deleteBtn.addEventListener("click", async () => {
        const message = "Delete this comment thread? This can't be undone.";
        const ok = window.RedscribeConfirm
          ? await window.RedscribeConfirm(message, { title: "Delete comment thread", confirmLabel: "Delete", danger: true })
          : true;
        if (ok) onDelete();
      });
    }
    card.appendChild(replyForm);
    return card;
  }

  // A floating popover (desktop) / bottom sheet (mobile), one per RTE field,
  // that hosts either the new-comment composer or an existing thread.
  function createCommentSurface() {
    const surface = document.createElement("div");
    surface.className = "rte-comment-surface";
    surface.setAttribute("role", "dialog");
    surface.setAttribute("aria-label", "Comment");
    surface.hidden = true;
    const backdrop = document.createElement("div");
    backdrop.className = "rte-comment-backdrop";
    backdrop.hidden = true;
    document.body.appendChild(backdrop);
    document.body.appendChild(surface);

    const state = { mode: null, pinned: false, anchorRect: null, closeTimer: null, lastFocus: null };

    function cancelClose() {
      if (state.closeTimer) { clearTimeout(state.closeTimer); state.closeTimer = null; }
    }
    function scheduleClose() {
      if (state.pinned) return;
      cancelClose();
      state.closeTimer = setTimeout(close, 300);
    }
    function place() {
      if (isMobile()) {
        surface.classList.add("rte-comment-sheet");
        surface.style.left = surface.style.top = "";
        backdrop.hidden = false;
        return;
      }
      surface.classList.remove("rte-comment-sheet");
      backdrop.hidden = true;
      surface.style.visibility = "hidden";
      surface.hidden = false;
      const r = surface.getBoundingClientRect();
      const a = state.anchorRect || { left: window.innerWidth / 2, right: window.innerWidth / 2, top: window.innerHeight / 2, bottom: window.innerHeight / 2 };
      const left = Math.max(8, Math.min(a.left, window.innerWidth - r.width - 8));
      let top = a.bottom + 8;
      if (top + r.height > window.innerHeight - 8) top = Math.max(8, a.top - r.height - 8);
      surface.style.left = `${left}px`;
      surface.style.top = `${top}px`;
      surface.style.visibility = "";
    }
    function open({ mode, node, pinned, anchorRect, lastFocus }) {
      cancelClose();
      state.mode = mode; state.pinned = !!pinned; state.anchorRect = anchorRect || null;
      state.lastFocus = lastFocus || null;
      // The click/tap that opens a pinned surface keeps bubbling to the
      // document outside-click handler below; ignore that same event so it
      // doesn't close what it just opened.
      state.suppressDocClick = true;
      setTimeout(() => { state.suppressDocClick = false; }, 0);
      surface.replaceChildren(node);
      surface.hidden = false;
      place();
    }
    function close() {
      cancelClose();
      surface.hidden = true;
      backdrop.hidden = true;
      surface.classList.remove("rte-comment-sheet");
      surface.replaceChildren();
      const refocus = state.lastFocus;
      state.mode = null; state.pinned = false; state.anchorRect = null; state.lastFocus = null;
      if (refocus && document.contains(refocus)) {
        // Returning focus to the highlight would otherwise re-fire focusin and
        // re-open the popover we just closed; suppress that one reopen.
        state.suppressReopen = true;
        setTimeout(() => { state.suppressReopen = false; }, 0);
        try { refocus.focus(); } catch (e) { /* gone */ }
      }
    }

    surface.addEventListener("mouseenter", cancelClose);
    surface.addEventListener("mouseleave", scheduleClose);
    // Interacting with the popover (e.g. clicking into the reply box) pins it,
    // so a hover-opened thread doesn't vanish mid-reply when the mouse drifts.
    surface.addEventListener("focusin", () => { state.pinned = true; cancelClose(); });
    surface.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } });
    backdrop.addEventListener("click", close);
    document.addEventListener("click", (e) => {
      if (state.suppressDocClick) return;
      if (surface.hidden || !state.pinned) return;
      if (surface.contains(e.target)) return;
      if (e.target.closest && e.target.closest("[data-thread-id]")) return; // handled as (re)open
      close();
    });
    window.addEventListener("resize", () => { if (!surface.hidden) place(); });

    return {
      el: surface,
      open, close, cancelClose, scheduleClose,
      isOpen: () => !surface.hidden,
      mode: () => state.mode,
      isPinned: () => state.pinned,
      isSuppressingReopen: () => state.suppressReopen,
      pin: () => { state.pinned = true; cancelClose(); },
      focusFirst: () => { const f = surface.querySelector("textarea, button, [href], [tabindex]"); if (f) f.focus(); },
    };
  }

  // Viewport rect spanning the current selection, for anchoring the composer.
  function selectionRect(editor) {
    try {
      const { from, to } = editor.state.selection;
      const a = editor.view.coordsAtPos(from);
      const b = editor.view.coordsAtPos(to);
      return {
        left: Math.min(a.left, b.left), right: Math.max(a.right, b.right),
        top: Math.min(a.top, b.top), bottom: Math.max(a.bottom, b.bottom),
      };
    } catch (e) { return null; }
  }

  function setupComments(editor, container, fieldName, urls) {
    const surface = createCommentSurface();
    const dom = editor.view.dom;
    let byId = new Map();

    async function refresh() {
      const resp = await fetch(urls.list);
      const data = await resp.json();
      byId = new Map((data.threads || []).map((t) => [String(t.id), t]));
      window.RedscribeEditor.setCommentThreads(editor, data.threads || []);
    }
    refresh();

    function anchorElFor(threadId) {
      const sel = window.CSS && CSS.escape ? CSS.escape(String(threadId)) : String(threadId);
      return dom.querySelector(`[data-thread-id="${sel}"]`);
    }
    const rectOf = (el) => (el ? el.getBoundingClientRect() : null);

    function callbacks(threadId) {
      return {
        onReply: async (body) => {
          try {
            await postJson(urls.replyTemplate.replace("THREADID", threadId), { body });
            await refresh();
            openThread(threadId, { pinned: true });
            toast("Reply posted.", "success");
          } catch (e) { toast("Reply couldn't be saved.", "error"); }
        },
        onToggleResolve: async () => {
          try {
            const updated = await postJson(urls.resolveTemplate.replace("THREADID", threadId), {});
            await refresh();
            openThread(threadId, { pinned: true });
            toast(updated.resolved ? "Thread resolved." : "Thread reopened.", "success");
          } catch (e) { toast("Couldn't update the thread.", "error"); }
        },
        onDelete: async () => {
          try {
            await postJson(urls.deleteTemplate.replace("THREADID", threadId), {});
            surface.close();
            await refresh();
            toast("Comment deleted.", "success");
          } catch (e) { toast("Comment couldn't be deleted.", "error"); }
        },
      };
    }

    function openThread(threadId, { pinned, viaKeyboard } = {}) {
      const thread = byId.get(String(threadId));
      if (!thread) return;
      const el = anchorElFor(threadId);
      const card = buildThreadCard(thread, callbacks(threadId));
      surface.open({ mode: "thread", node: card, pinned: pinned, anchorRect: rectOf(el), lastFocus: viaKeyboard ? el : null });
      if (pinned && viaKeyboard) surface.focusFirst();
    }

    function startCompose(range) {
      if (!range) { toast("Select some text to comment on.", "warning"); return; }
      const box = document.createElement("div");
      box.className = "rte-comment-compose";
      const quote = document.createElement("blockquote");
      quote.className = "rte-thread-quote";
      quote.textContent = range.text;
      const textarea = document.createElement("textarea");
      textarea.rows = 3; textarea.className = "field-input";
      textarea.placeholder = "Comment on the selected text...";
      textarea.setAttribute("aria-label", "New comment");
      const actions = document.createElement("div");
      actions.className = "rte-thread-actions";
      actions.innerHTML = '<button type="button" class="btn-primary" data-save>Save comment</button> <button type="button" class="btn-secondary" data-cancel>Cancel</button>';
      box.append(quote, textarea, actions);
      actions.querySelector("[data-cancel]").addEventListener("click", () => surface.close());
      actions.querySelector("[data-save]").addEventListener("click", async () => {
        const body = textarea.value.trim();
        if (!body) return;
        try {
          await postJson(urls.create, { start_pos: range.from, end_pos: range.to, anchored_text: range.text, body });
          surface.close();
          await refresh();
          toast("Comment added.", "success");
        } catch (e) { toast("Comment couldn't be saved.", "error"); }
      });
      surface.open({ mode: "compose", node: box, pinned: true, anchorRect: selectionRect(editor) });
      textarea.focus();
    }

    // Reveal an existing comment in place: hover/focus (desktop) or tap (mobile).
    dom.addEventListener("mouseover", (e) => {
      if (isMobile()) return;
      const el = e.target.closest && e.target.closest("[data-thread-id]");
      if (!el) return;
      surface.cancelClose();
      if (surface.mode() === "compose") return;
      if (surface.mode() === "thread" && surface.isPinned()) return;
      openThread(el.getAttribute("data-thread-id"), { pinned: false });
    });
    dom.addEventListener("mouseout", (e) => {
      if (isMobile()) return;
      if (e.target.closest && e.target.closest("[data-thread-id]")) surface.scheduleClose();
    });
    dom.addEventListener("focusin", (e) => {
      const el = e.target.closest && e.target.closest("[data-thread-id]");
      if (!el || surface.mode() === "compose") return;
      if (surface.isSuppressingReopen()) return;
      openThread(el.getAttribute("data-thread-id"), { pinned: false, viaKeyboard: true });
    });
    dom.addEventListener("focusout", (e) => {
      if (!(e.target.closest && e.target.closest("[data-thread-id]"))) return;
      setTimeout(() => {
        if (surface.isOpen() && !surface.isPinned() && !surface.el.contains(document.activeElement)) surface.close();
      }, 0);
    });
    dom.addEventListener("keydown", (e) => {
      const el = e.target.closest && e.target.closest("[data-thread-id]");
      if (el && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        openThread(el.getAttribute("data-thread-id"), { pinned: true, viaKeyboard: true });
        return;
      }
      if ((e.metaKey || e.ctrlKey) && e.altKey && (e.key === "m" || e.key === "M")) {
        e.preventDefault();
        startCompose(window.RedscribeEditor.getSelectionRange(editor));
      }
    });
    container.addEventListener("redscribe:comment-thread-click", (event) => {
      openThread(event.detail.threadId, { pinned: true });
    });

    return { startCompose };
  }

  function makeRovingToolbar(bar, buttons) {
    function focusable(btn) {
      return !btn.disabled && btn.offsetParent !== null;
    }

    function setCurrent(btn) {
      for (const b of buttons) b.tabIndex = b === btn ? 0 : -1;
    }

    function currentIndex() {
      const idx = buttons.findIndex((b) => b.tabIndex === 0);
      return idx === -1 ? 0 : idx;
    }

    function moveFocus(fromIndex, delta) {
      const candidates = buttons.filter(focusable);
      if (candidates.length === 0) return;
      let idx = buttons.indexOf(buttons[fromIndex]);
      for (let i = 0; i < buttons.length; i++) {
        idx = (idx + delta + buttons.length) % buttons.length;
        if (focusable(buttons[idx])) break;
      }
      setCurrent(buttons[idx]);
      buttons[idx].focus();
    }

    if (buttons.length > 0) setCurrent(buttons.find(focusable) || buttons[0]);

    bar.addEventListener("click", (event) => {
      const btn = buttons.find((b) => b === event.target);
      if (btn && focusable(btn)) setCurrent(btn);
    });

    function ensureCurrent() {
      if (!focusable(buttons[currentIndex()])) {
        const next = buttons.find(focusable);
        if (next) setCurrent(next);
      }
    }

    bar.addEventListener("keydown", (event) => {
      const idx = currentIndex();
      switch (event.key) {
        case "ArrowRight":
        case "ArrowDown":
          event.preventDefault();
          moveFocus(idx, 1);
          break;
        case "ArrowLeft":
        case "ArrowUp":
          event.preventDefault();
          moveFocus(idx, -1);
          break;
        case "Home":
          event.preventDefault();
          moveFocus(-1, 1);
          break;
        case "End":
          event.preventDefault();
          moveFocus(0, -1);
          break;
      }
    });

    return { ensureCurrent };
  }

  function createLinkPopover(editor, { onClose } = {}) {
    const popover = document.createElement("div");
    popover.className = "rte-link-popover";
    popover.hidden = true;
    popover.innerHTML =
      '<input type="url" placeholder="https://..." class="rte-link-input" aria-label="Link URL">' +
      '<button type="button" class="rte-toolbar-btn" data-link-set>Set</button>' +
      '<button type="button" class="rte-toolbar-btn" data-link-unset>Remove</button>' +
      '<button type="button" class="rte-toolbar-btn" data-link-cancel>Cancel</button>';
    const input = popover.querySelector(".rte-link-input");

    function close({ refocus = true } = {}) {
      popover.hidden = true;
      popover.style.left = "";
      popover.style.right = "";
      popover.style.top = "";
      popover.style.bottom = "";
      popover.style.marginTop = "";
      popover.style.marginBottom = "";
      if (onClose) onClose({ refocus });
    }
    function open() {
      input.value = editor.getAttributes("link").href || "";
      popover.hidden = false;
      input.focus();
      // Only meaningful when this popover is absolutely-positioned (the
      // selection-menu's nested variant, see .rte-selection-menu
      // .rte-link-popover) — it's wider than the already viewport-clamped
      // menu it hangs off of, so left:0 alone can push it past the right
      // or bottom edge when that menu sits near either. No-op for the
      // persistent toolbar's own static in-flow copy, since left/right/
      // top/bottom have no effect on a non-positioned element.
      const rect = popover.getBoundingClientRect();
      if (rect.right > window.innerWidth - 8) {
        popover.style.left = "auto";
        popover.style.right = "0";
      }
      if (rect.bottom > window.innerHeight - 8) {
        popover.style.top = "auto";
        popover.style.bottom = "100%";
        popover.style.marginTop = "0";
        popover.style.marginBottom = "0.25rem";
      }
    }
    function toggle() {
      if (popover.hidden) open();
      else close();
    }
    popover.querySelector("[data-link-set]").addEventListener("click", () => {
      const url = input.value.trim();
      if (url) editor.chain().focus().extendMarkRange("link").setLink({ href: url }).run();
      close({ refocus: false });
    });
    popover.querySelector("[data-link-unset]").addEventListener("click", () => {
      editor.chain().focus().unsetLink().run();
      close({ refocus: false });
    });
    popover.querySelector("[data-link-cancel]").addEventListener("click", () => close());
    popover.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target === input) {
        e.preventDefault();
        popover.querySelector("[data-link-set]").click();
      } else if (e.key === "Escape") {
        e.preventDefault();
        close();
      }
    });
    popover.addEventListener("mousedown", (e) => e.stopPropagation());

    return { el: popover, open, close, toggle, isOpen: () => !popover.hidden };
  }

  function buildSelectionMenu(editor, fieldContainer, opts) {
    opts = opts || { formatting: true, onComment: null };
    const menu = document.createElement("div");
    menu.className = "rte-selection-menu";
    menu.hidden = true;
    menu.setAttribute("role", "toolbar");
    menu.setAttribute("aria-label", "Selection formatting");

    const activeButtons = [];
    function addButton(label, title, action, isActive) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "rte-toolbar-btn";
      buttonFace(btn, label, title);
      btn.addEventListener("mousedown", (e) => e.preventDefault());
      btn.addEventListener("click", action);
      if (isActive) activeButtons.push([btn, isActive]);
      menu.appendChild(btn);
      return btn;
    }
    function addDivider() {
      const div = document.createElement("span");
      div.className = "rte-toolbar-divider";
      menu.appendChild(div);
    }

    let linkPopover = null;
    if (opts.formatting) {
      addButton("B", "Bold", () => editor.chain().focus().toggleBold().run(), () => editor.isActive("bold"));
      addButton("I", "Italic", () => editor.chain().focus().toggleItalic().run(), () => editor.isActive("italic"));
      addButton("U", "Underline", () => editor.chain().focus().toggleUnderline().run(), () => editor.isActive("underline"));
      addButton("S", "Strikethrough", () => editor.chain().focus().toggleStrike().run(), () => editor.isActive("strike"));
      addButton("</>", "Inline code", () => editor.chain().focus().toggleCode().run(), () => editor.isActive("code"));
      addButton("✎", "Highlight", () => editor.chain().focus().toggleHighlight().run(), () => editor.isActive("highlight"));
      addDivider();
      for (const level of [1, 2, 3]) {
        addButton(`H${level}`, `Heading ${level}`, () => editor.chain().focus().toggleHeading({ level }).run(), () =>
          editor.isActive("heading", { level })
        );
      }
      addButton("Lead", "Lead text (bigger, not a heading — no numbering or table of contents entry)", () => {
        const isLead = editor.isActive("paragraph", { lead: true });
        editor.chain().focus().updateAttributes("paragraph", { lead: !isLead }).run();
      }, () => editor.isActive("paragraph", { lead: true }));
      addDivider();
      linkPopover = createLinkPopover(editor);
      addButton("🔗", "Link", () => linkPopover.toggle(), () => editor.isActive("link"));
      menu.appendChild(linkPopover.el);
    }
    if (opts.onComment) {
      // Comment on the current selection: the in-place replacement for the old
      // "Add comment" button. The only action in the read-only detail view.
      const commentBtn = addButton("💬", "Add comment", () => {
        const range = window.RedscribeEditor.getSelectionRange(editor);
        hide();
        opts.onComment(range);
      }, null);
      commentBtn.classList.add("rte-toolbar-btn-comment");
    }

    document.body.appendChild(menu);

    function refreshActiveStates() {
      for (const [btn, isActive] of activeButtons) btn.classList.toggle("rte-toolbar-btn-active", isActive());
    }

    // The menu is position: fixed at z-index 55, so clamping it to the
    // viewport alone left it floating over the sticky chrome — the page
    // header, this field's own toolbar, the bottom Cancel/Back bar — once the
    // selection scrolled underneath. Clamp to the region between them (and
    // inside any scrolling ancestor, e.g. the report preview pane) instead,
    // and hide the menu while the selection is outside it.
    const ownToolbar = fieldContainer.previousElementSibling?.classList.contains("rte-toolbar-sticky")
      ? fieldContainer.previousElementSibling
      : null;

    function visibleBounds() {
      let top = 0;
      let bottom = window.innerHeight;
      for (const el of [document.getElementById("page-sticky-header"), ownToolbar]) {
        if (el) top = Math.max(top, el.getBoundingClientRect().bottom);
      }
      // A bottom bar still in normal flow below the fold has top > bottom
      // and is skipped; one stuck to the viewport edge cuts the region.
      for (const bar of document.querySelectorAll(".sticky.bottom-0")) {
        const rect = bar.getBoundingClientRect();
        if (rect.height && rect.top < bottom) bottom = rect.top;
      }
      for (let node = fieldContainer.parentElement; node && node !== document.body; node = node.parentElement) {
        const overflowY = getComputedStyle(node).overflowY;
        if (overflowY === "auto" || overflowY === "scroll") {
          const rect = node.getBoundingClientRect();
          top = Math.max(top, rect.top);
          bottom = Math.min(bottom, rect.bottom);
        }
      }
      return { top, bottom };
    }

    // Whether the menu should be showing at all (non-empty selection, or the
    // link popover open) — separate from menu.hidden, which also goes true
    // while the selection is merely scrolled out of view.
    let active = false;

    function position() {
      const { from, to } = editor.state.selection;
      const start = editor.view.coordsAtPos(from);
      const end = editor.view.coordsAtPos(to);
      const selLeft = Math.min(start.left, end.left);
      const selRight = Math.max(start.right, end.right);
      const selTop = Math.min(start.top, end.top);
      const selBottom = Math.max(start.bottom, end.bottom);

      const bounds = visibleBounds();
      if (selBottom <= bounds.top || selTop >= bounds.bottom) {
        menu.hidden = true;
        return;
      }

      menu.hidden = false;
      const menuRect = menu.getBoundingClientRect();
      let left = (selLeft + selRight) / 2 - menuRect.width / 2;
      left = Math.max(8, Math.min(left, window.innerWidth - menuRect.width - 8));
      let top = selTop - menuRect.height - 8;
      if (top < bounds.top + 8) top = selBottom + 8;
      // Flipping below the selection when there's no room above still isn't
      // enough near the bottom of the visible region — clamp against the
      // bottom edge too, same as left/right above, so the menu never covers
      // the bottom bar or gets pushed off-screen.
      top = Math.max(bounds.top + 8, Math.min(top, bounds.bottom - menuRect.height - 8));
      menu.style.left = `${left}px`;
      menu.style.top = `${top}px`;
    }

    function hide() {
      if (linkPopover && linkPopover.isOpen()) return;
      active = false;
      menu.hidden = true;
    }

    editor.on("selectionUpdate", () => {
      if (editor.state.selection.empty) {
        hide();
        return;
      }
      active = true;
      position();
      refreshActiveStates();
    });
    editor.on("transaction", refreshActiveStates);
    editor.on("blur", () => {
      setTimeout(() => {
        if (!menu.contains(document.activeElement)) hide();
      }, 0);
    });
    window.addEventListener("scroll", () => {
      if (active) position();
    }, true);
    window.addEventListener("resize", () => {
      if (active) position();
    });

    return menu;
  }

  function buildToolbar(editor, el, { imageUploadUrl, fieldName, allowPageBreak }) {
    const bar = document.createElement("div");
    bar.className = "rte-toolbar";
    bar.setAttribute("role", "toolbar");
    bar.setAttribute("aria-label", "Formatting");
    const activeButtons = [];
    const enabledButtons = [];
    const rovingButtons = [];

    function addButton(label, title, action, { isActive, isEnabled, group } = {}) {
      const btn = document.createElement("button");
      btn.type = "button";
      buttonFace(btn, label, title);
      btn.className = "rte-toolbar-btn";
      btn.tabIndex = -1;
      btn.addEventListener("click", action);
      if (isActive) activeButtons.push([btn, isActive]);
      if (isEnabled) enabledButtons.push([btn, isEnabled]);
      rovingButtons.push(btn);
      (group || bar).appendChild(btn);
      return btn;
    }

    function addDivider() {
      const div = document.createElement("span");
      div.className = "rte-toolbar-divider";
      bar.appendChild(div);
    }

    addButton("B", "Bold", () => editor.chain().focus().toggleBold().run(), {
      isActive: () => editor.isActive("bold"),
    });
    addButton("I", "Italic", () => editor.chain().focus().toggleItalic().run(), {
      isActive: () => editor.isActive("italic"),
    });
    addButton("U", "Underline", () => editor.chain().focus().toggleUnderline().run(), {
      isActive: () => editor.isActive("underline"),
    });
    addButton("S", "Strikethrough", () => editor.chain().focus().toggleStrike().run(), {
      isActive: () => editor.isActive("strike"),
    });
    addButton("</>", "Inline code", () => editor.chain().focus().toggleCode().run(), {
      isActive: () => editor.isActive("code"),
    });
    addButton("✎", "Highlight", () => editor.chain().focus().toggleHighlight().run(), {
      isActive: () => editor.isActive("highlight"),
    });
    addDivider();

    for (const level of [1, 2, 3, 4]) {
      addButton(`H${level}`, `Heading ${level}`, () => editor.chain().focus().toggleHeading({ level }).run(), {
        isActive: () => editor.isActive("heading", { level }),
      });
    }
    addButton("Lead", "Lead text (bigger, not a heading — no numbering or table of contents entry)", () => {
      const isLead = editor.isActive("paragraph", { lead: true });
      editor.chain().focus().updateAttributes("paragraph", { lead: !isLead }).run();
    }, {
      isActive: () => editor.isActive("paragraph", { lead: true }),
    });
    addButton("“", "Blockquote", () => editor.chain().focus().toggleBlockquote().run(), {
      isActive: () => editor.isActive("blockquote"),
    });
    addButton("{ }", "Code block", () => editor.chain().focus().toggleCodeBlock().run(), {
      isActive: () => editor.isActive("codeBlock"),
    });
    addButton("—", "Horizontal rule", () => editor.chain().focus().setHorizontalRule().run());
    if (allowPageBreak) {
      addButton("⤓", "Insert page break", () =>
        editor.chain().focus().insertContent({ type: "pageBreak" }).run()
      );
    }
    addDivider();

    addButton("•", "Bullet list", () => editor.chain().focus().toggleBulletList().run(), {
      isActive: () => editor.isActive("bulletList"),
    });
    addButton("1.", "Numbered list", () => editor.chain().focus().toggleOrderedList().run(), {
      isActive: () => editor.isActive("orderedList"),
    });
    addDivider();

    addButton("⊞", "Insert table", () =>
      editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
    );
    addButton("+Row", "Add row below", () => editor.chain().focus().addRowAfter().run(), {
      isEnabled: () => editor.can().addRowAfter(),
    });
    addButton("+Col", "Add column right", () => editor.chain().focus().addColumnAfter().run(), {
      isEnabled: () => editor.can().addColumnAfter(),
    });
    addButton("-Row", "Delete row", () => editor.chain().focus().deleteRow().run(), {
      isEnabled: () => editor.can().deleteRow(),
    });
    addButton("-Col", "Delete column", () => editor.chain().focus().deleteColumn().run(), {
      isEnabled: () => editor.can().deleteColumn(),
    });
    addButton("⊟", "Delete table", () => editor.chain().focus().deleteTable().run(), {
      isEnabled: () => editor.can().deleteTable(),
    });
    addButton("HdrR", "Toggle header row", () => editor.chain().focus().toggleHeaderRow().run(), {
      isEnabled: () => editor.can().toggleHeaderRow(),
    });
    addButton("HdrC", "Toggle header column", () => editor.chain().focus().toggleHeaderColumn().run(), {
      isEnabled: () => editor.can().toggleHeaderColumn(),
    });
    addButton("⊔", "Merge/split cells", () => editor.chain().focus().mergeOrSplit().run(), {
      isEnabled: () => editor.can().mergeCells() || editor.can().splitCell(),
    });
    addDivider();

    let linkBtn;
    const linkPopover = createLinkPopover(editor, {
      onClose: ({ refocus }) => {
        if (refocus) linkBtn.focus();
      },
    });
    linkBtn = addButton("🔗", "Link", () => linkPopover.toggle(), {
      isActive: () => editor.isActive("link"),
    });
    addDivider();

    addButton("↶", "Undo", () => editor.chain().focus().undo().run());
    addButton("↷", "Redo", () => editor.chain().focus().redo().run());

    if (imageUploadUrl) {
      addDivider();
      const imgBtn = document.createElement("button");
      imgBtn.type = "button";
      buttonFace(imgBtn, "🖼", "Insert image");
      imgBtn.className = "rte-toolbar-btn";
      imgBtn.tabIndex = -1;
      rovingButtons.push(imgBtn);
      const fileInput = document.createElement("input");
      fileInput.type = "file";
      fileInput.accept = "image/png,image/jpeg,image/gif,image/webp";
      fileInput.hidden = true;
      fileInput.addEventListener("change", async () => {
        if (fileInput.files[0]) {
          const url = await uploadImage(imageUploadUrl, fileInput.files[0]);
          editor.chain().focus().setImage({ src: url }).run();
        }
        fileInput.value = "";
      });
      imgBtn.addEventListener("click", () => fileInput.click());
      bar.appendChild(imgBtn);
      bar.appendChild(fileInput);
    }

    const stickyWrap = document.createElement("div");
    stickyWrap.className = "rte-toolbar-sticky";
    stickyWrap.appendChild(bar);
    stickyWrap.appendChild(linkPopover.el);
    el.parentNode.insertBefore(stickyWrap, el);
    if (scrollingAncestor(stickyWrap)) stickyWrap.style.top = "0px";

    const rovingToolbar = makeRovingToolbar(bar, rovingButtons);

    function refreshActiveStates() {
      for (const [btn, isActive] of activeButtons) {
        btn.classList.toggle("rte-toolbar-btn-active", isActive());
      }
      for (const [btn, isEnabled] of enabledButtons) {
        btn.disabled = !isEnabled();
      }
      rovingToolbar.ensureCurrent();
    }
    editor.on("transaction", refreshActiveStates);
    editor.on("selectionUpdate", refreshActiveStates);
    refreshActiveStates();
  }

  // The editable area is a contenteditable with role="textbox"; give it the
  // field's name: data-rte-label, else the hidden input's <label>, else the
  // heading of the panel it sits in.
  function nameEditor(el, hiddenInput) {
    const area = el.querySelector("[contenteditable]");
    if (!area || area.hasAttribute("aria-label") || area.hasAttribute("aria-labelledby")) return;
    let name = el.dataset.rteLabel;
    if (!name && hiddenInput && hiddenInput.id) {
      const label = document.querySelector(`label[for="${hiddenInput.id}"]`);
      if (label) name = label.textContent.trim();
    }
    if (!name) {
      const panel = el.closest("section, details, .panel, .card, fieldset");
      const heading = panel && panel.querySelector("h2, h3, legend, summary, label");
      if (heading) name = heading.textContent.trim().replace(/\s+/g, " ");
    }
    if (name) area.setAttribute("aria-label", name);
  }

  function initRichTextEditor(el) {
    const fieldName = el.dataset.rteField;
    const editable = el.dataset.rteEditable !== "false";
    let initialContent = null;
    if (el.dataset.rteInitial) {
      try {
        initialContent = JSON.parse(el.dataset.rteInitial);
      } catch (e) {
        initialContent = null;
      }
    }

    const hiddenInput = document.querySelector(`[data-rte-hidden="${fieldName}"]`);
    const uploadUrl = el.dataset.uploadUrl;

    const editor = window.RedscribeEditor.mount(el, {
      content: initialContent,
      editable,
      onImageUpload: uploadUrl ? (file) => uploadImage(uploadUrl, file) : undefined,
      onUpdate: hiddenInput ? (ed) => {
        hiddenInput.value = JSON.stringify(ed.getJSON());
        hiddenInput.dispatchEvent(new Event("input", { bubbles: true }));
      } : undefined,
    });

    if (hiddenInput) hiddenInput.value = JSON.stringify(editor.getJSON());
    nameEditor(el, hiddenInput);

    const comments = el.dataset.commentsListUrl
      ? setupComments(editor, el, fieldName, {
          list: el.dataset.commentsListUrl,
          create: el.dataset.commentsCreateUrl,
          replyTemplate: el.dataset.commentsReplyTemplate,
          resolveTemplate: el.dataset.commentsResolveTemplate,
          deleteTemplate: el.dataset.commentsDeleteTemplate,
        })
      : null;

    if (editable) {
      buildToolbar(editor, el, { imageUploadUrl: uploadUrl, fieldName, allowPageBreak: el.dataset.rtePageBreaks === "true" });
      buildSelectionMenu(editor, el, { formatting: true, onComment: comments ? comments.startCompose : null });
    } else if (comments) {
      // Read-only detail view: selection shows a comment-only bubble (no formatting).
      buildSelectionMenu(editor, el, { formatting: false, onComment: comments.startCompose });
    }

    return editor;
  }

  // Pin toolbars just below all the sticky chrome above them: the topbar,
  // then the page header (engagement tabs), which itself sticks below the
  // topbar rather than at 0, so its own height alone isn't enough.
  function updateStickyOffset() {
    const topbar = document.querySelector(".topbar");
    const header = document.getElementById("page-sticky-header");
    let offset = topbar ? topbar.getBoundingClientRect().height : 0;
    if (header && header.offsetHeight) {
      offset = (parseFloat(getComputedStyle(header).top) || offset) + header.getBoundingClientRect().height;
    }
    document.documentElement.style.setProperty("--rte-sticky-top", offset + "px");

    // A toolbar inside its own scrolling box (e.g. the xl rail, which scrolls
    // independently) sticks to that box's top edge, not below the page chrome.
    // Rechecked on resize since the rail only scrolls at xl.
    for (const toolbar of document.querySelectorAll(".rte-toolbar-sticky")) {
      toolbar.style.top = scrollingAncestor(toolbar) ? "0px" : "";
    }
  }

  function scrollingAncestor(el) {
    for (let node = el.parentElement; node && node !== document.body; node = node.parentElement) {
      const overflowY = getComputedStyle(node).overflowY;
      if (overflowY === "auto" || overflowY === "scroll" || overflowY === "hidden") return node;
    }
    return null;
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-rte-field]").forEach(initRichTextEditor);
    updateStickyOffset();
    window.addEventListener("resize", updateStickyOffset);
  });

  window.RedscribeEditorApp = { initRichTextEditor };
})();
