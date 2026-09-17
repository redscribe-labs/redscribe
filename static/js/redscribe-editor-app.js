(function () {
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

  function renderPanel(panel, threads, { onReply, onToggleResolve, onDelete }) {
    panel.innerHTML = "";
    if (threads.length === 0) {
      panel.innerHTML = '<p class="rte-comments-empty">No comments yet. Select text in the editor and click "Add comment".</p>';
      return;
    }
    for (const thread of threads) {
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
        '<textarea rows="2" class="field-input" placeholder="Reply..."></textarea>' +
        '<button type="submit" class="btn-primary">Reply</button> ' +
        `<button type="button" class="btn-secondary rte-resolve-btn">${thread.resolved ? "Reopen" : "Resolve"}</button>` +
        (thread.can_delete ? ' <button type="button" class="btn-secondary rte-delete-btn">Delete</button>' : "");
      replyForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const textarea = replyForm.querySelector("textarea");
        if (!textarea.value.trim()) return;
        onReply(thread.id, textarea.value.trim());
      });
      replyForm.querySelector(".rte-resolve-btn").addEventListener("click", () => onToggleResolve(thread.id));
      const deleteBtn = replyForm.querySelector(".rte-delete-btn");
      if (deleteBtn) {
        deleteBtn.addEventListener("click", () => {
          if (window.confirm("Delete this comment thread? This can't be undone.")) onDelete(thread.id);
        });
      }
      card.appendChild(replyForm);

      panel.appendChild(card);
    }
  }

  function highlightThreadCard(panel, threadId) {
    panel.querySelectorAll(".rte-thread-card").forEach((card) => {
      card.classList.toggle("rte-thread-focused", card.dataset.threadId === String(threadId));
    });
    const target = panel.querySelector(`.rte-thread-card[data-thread-id="${threadId}"]`);
    if (target) target.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function setupComments(editor, container, fieldName, urls) {
    const panel = document.querySelector(`[data-comments-panel="${fieldName}"]`);
    let threads = [];

    async function refresh() {
      const resp = await fetch(urls.list);
      const data = await resp.json();
      threads = data.threads;
      window.RedscribeEditor.setCommentThreads(editor, threads);
      if (panel) {
        renderPanel(panel, threads, {
          onReply: async (threadId, body) => {
            try {
              await postJson(urls.replyTemplate.replace("THREADID", threadId), { body });
              await refresh();
              toast("Reply posted.", "success");
            } catch (e) {
              toast("Reply couldn't be saved.", "error");
            }
          },
          onToggleResolve: async (threadId) => {
            try {
              const updated = await postJson(urls.resolveTemplate.replace("THREADID", threadId), {});
              await refresh();
              toast(updated.resolved ? "Thread resolved." : "Thread reopened.", "success");
            } catch (e) {
              toast("Couldn't update the thread.", "error");
            }
          },
          onDelete: async (threadId) => {
            try {
              await postJson(urls.deleteTemplate.replace("THREADID", threadId), {});
              await refresh();
              toast("Comment deleted.", "success");
            } catch (e) {
              toast("Comment couldn't be deleted.", "error");
            }
          },
        });
      }
    }

    refresh();

    container.addEventListener("redscribe:comment-thread-click", (event) => {
      if (panel) highlightThreadCard(panel, event.detail.threadId);
    });

    const addBtn = document.querySelector(`[data-add-comment="${fieldName}"]`);
    if (addBtn) {
      addBtn.addEventListener("click", () => {
        const range = window.RedscribeEditor.getSelectionRange(editor);
        if (!range) {
          alert("Select some text in the editor first.");
          return;
        }
        const box = document.querySelector(`[data-new-comment-box="${fieldName}"]`);
        box.hidden = false;
        box.querySelector("textarea").value = "";
        box.querySelector("textarea").focus();
        box.dataset.from = range.from;
        box.dataset.to = range.to;
        box.dataset.text = range.text;
      });
    }

    const newCommentBox = document.querySelector(`[data-new-comment-box="${fieldName}"]`);
    if (newCommentBox) {
      newCommentBox.querySelector("[data-save]").addEventListener("click", async () => {
        const body = newCommentBox.querySelector("textarea").value.trim();
        if (!body) return;
        try {
          await postJson(urls.create, {
            start_pos: Number(newCommentBox.dataset.from),
            end_pos: Number(newCommentBox.dataset.to),
            anchored_text: newCommentBox.dataset.text,
            body,
          });
          newCommentBox.hidden = true;
          await refresh();
          toast("Comment added.", "success");
        } catch (e) {
          toast("Comment couldn't be saved.", "error");
        }
      });
      newCommentBox.querySelector("[data-cancel]").addEventListener("click", () => {
        newCommentBox.hidden = true;
      });
    }
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

  function buildSelectionMenu(editor, fieldContainer) {
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
      btn.textContent = label;
      btn.title = title;
      btn.setAttribute("aria-label", title);
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
    const linkPopover = createLinkPopover(editor);
    addButton("🔗", "Link", () => linkPopover.toggle(), () => editor.isActive("link"));
    menu.appendChild(linkPopover.el);

    document.body.appendChild(menu);

    function refreshActiveStates() {
      for (const [btn, isActive] of activeButtons) btn.classList.toggle("rte-toolbar-btn-active", isActive());
    }

    function position() {
      const { from, to } = editor.state.selection;
      const start = editor.view.coordsAtPos(from);
      const end = editor.view.coordsAtPos(to);
      const selLeft = Math.min(start.left, end.left);
      const selRight = Math.max(start.right, end.right);
      const selTop = Math.min(start.top, end.top);
      const selBottom = Math.max(start.bottom, end.bottom);

      menu.hidden = false;
      const menuRect = menu.getBoundingClientRect();
      let left = (selLeft + selRight) / 2 - menuRect.width / 2;
      left = Math.max(8, Math.min(left, window.innerWidth - menuRect.width - 8));
      let top = selTop - menuRect.height - 8;
      if (top < 8) top = selBottom + 8;
      // Flipping below the selection when there's no room above still isn't
      // enough near the bottom of a tall viewport (or inside the preview
      // pane's own scroll area) — clamp against the bottom edge too, same
      // as left/right above, so the menu is never pushed off-screen.
      top = Math.max(8, Math.min(top, window.innerHeight - menuRect.height - 8));
      menu.style.left = `${left}px`;
      menu.style.top = `${top}px`;
    }

    function hide() {
      if (linkPopover.isOpen()) return;
      menu.hidden = true;
    }

    editor.on("selectionUpdate", () => {
      if (editor.state.selection.empty) {
        hide();
        return;
      }
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
      if (!menu.hidden) position();
    }, true);
    window.addEventListener("resize", () => {
      if (!menu.hidden) position();
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
      btn.textContent = label;
      btn.title = title;
      btn.setAttribute("aria-label", title);
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
      imgBtn.textContent = "🖼";
      imgBtn.title = "Insert image";
      imgBtn.setAttribute("aria-label", "Insert image");
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

    if (editable) {
      buildToolbar(editor, el, { imageUploadUrl: uploadUrl, fieldName, allowPageBreak: el.dataset.rtePageBreaks === "true" });
      buildSelectionMenu(editor, el);
    }

    if (el.dataset.commentsListUrl) {
      setupComments(editor, el, fieldName, {
        list: el.dataset.commentsListUrl,
        create: el.dataset.commentsCreateUrl,
        replyTemplate: el.dataset.commentsReplyTemplate,
        resolveTemplate: el.dataset.commentsResolveTemplate,
        deleteTemplate: el.dataset.commentsDeleteTemplate,
      });
    }

    return editor;
  }

  function updateStickyOffset() {
    const header = document.getElementById("page-sticky-header");
    const height = header ? header.getBoundingClientRect().height : 0;
    document.documentElement.style.setProperty("--rte-sticky-top", height + "px");
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-rte-field]").forEach(initRichTextEditor);
    updateStickyOffset();
    window.addEventListener("resize", updateStickyOffset);
  });

  window.RedscribeEditorApp = { initRichTextEditor };
})();
