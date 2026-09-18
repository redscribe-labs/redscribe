import { Editor, Extension, Node } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import Paragraph from "@tiptap/extension-paragraph";
import Image from "@tiptap/extension-image";
import CodeBlock from "@tiptap/extension-code-block";
import Highlight from "@tiptap/extension-highlight";
import Underline from "@tiptap/extension-underline";
import Link from "@tiptap/extension-link";
import { Table, TableRow, TableHeader, TableCell } from "@tiptap/extension-table";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

const commentPluginKey = new PluginKey("redscribeComments");

const ALLOWED_IMAGE_SRC = /^\/engagements\/[0-9a-fA-F-]{36}\/blobs\/[0-9a-fA-F-]{36}\/?(?:\?.*)?$/;

function isAllowedImageSrc(src) {
  return typeof src === "string" && ALLOWED_IMAGE_SRC.test(src);
}

function stripDisallowedImages(node) {
  if (!node || typeof node !== "object") return node;
  if (Array.isArray(node.content)) {
    node.content = node.content
      .filter((child) => !(child && child.type === "image" && !isAllowedImageSrc(child.attrs && child.attrs.src)))
      .map(stripDisallowedImages);
  }
  return node;
}

function buildDecorations(doc, threads) {
  const decorations = [];
  for (const t of threads || []) {
    if (t.start_pos < t.end_pos && t.end_pos <= doc.content.size) {
      decorations.push(
        Decoration.inline(t.start_pos, t.end_pos, {
          class: t.resolved ? "rte-comment-highlight rte-comment-resolved" : "rte-comment-highlight",
          "data-thread-id": String(t.id),
        })
      );
    }
  }
  return DecorationSet.create(doc, decorations);
}

const CommentHighlight = Extension.create({
  name: "redscribeComments",
  addOptions() {
    return { threads: [] };
  },
  addProseMirrorPlugins() {
    const options = this.options;
    return [
      new Plugin({
        key: commentPluginKey,
        state: {
          init(_, { doc }) {
            return buildDecorations(doc, options.threads);
          },
          apply(tr, old) {
            const threads = tr.getMeta(commentPluginKey);
            if (threads) return buildDecorations(tr.doc, threads);
            return old.map(tr.mapping, tr.doc);
          },
        },
        props: {
          decorations(state) {
            return commentPluginKey.getState(state);
          },
          handleClick(view, _pos, event) {
            const target = event.target.closest && event.target.closest("[data-thread-id]");
            if (target) {
              view.dom.dispatchEvent(
                new CustomEvent("redscribe:comment-thread-click", {
                  detail: { threadId: target.getAttribute("data-thread-id") },
                  bubbles: true,
                })
              );
              return true;
            }
            return false;
          },
        },
      }),
    ];
  },
});

// A paragraph that renders bigger/bolder — "looks like a heading" — but
// carries none of a real heading's structure: assembly.py only ever
// builds a numbered section (with a table-of-contents entry) from a
// node whose type is literally "heading", so this stays invisible to
// numbering, nesting, and the TOC no matter how it's styled.
const LeadParagraph = Paragraph.extend({
  addAttributes() {
    return {
      lead: {
        default: false,
        parseHTML: (element) => element.classList.contains("report-lead"),
        renderHTML: (attrs) => (attrs.lead ? { class: "report-lead" } : {}),
      },
    };
  },
});

const PageBreak = Node.create({
  name: "pageBreak",
  group: "block",
  atom: true,
  selectable: true,
  parseHTML() {
    return [{ tag: "div.rte-page-break" }];
  },
  renderHTML() {
    return ["div", { class: "rte-page-break", contenteditable: "false" }, "Page break"];
  },
});

function mount(element, opts) {
  const { content, editable = true, onImageUpload, onUpdate, commentThreads } = opts;

  const editor = new Editor({
    element,
    editable,
    content: content ? stripDisallowedImages(content) : "",
    editorProps: {
      transformPastedHTML: (html) => html.replace(/<img\b[^>]*>/gi, ""),
    },
    extensions: [
      // v3's StarterKit now bundles Underline and Link itself (in
      // addition to CodeBlock/Paragraph, already disabled below) — both
      // are still added explicitly further down with this app's own
      // config (custom Link protocols/rel/target), so disable
      // StarterKit's copies to avoid a duplicate-extension-name conflict.
      StarterKit.configure({ codeBlock: false, paragraph: false, underline: false, link: false }),
      LeadParagraph,
      CodeBlock.extend({ marks: "bold highlight" }),
      Image,
      Underline,
      Highlight.configure({ multicolor: false }),
      Link.configure({
        openOnClick: false,
        autolink: true,
        protocols: ["http", "https", "mailto"],
        HTMLAttributes: { rel: "noopener noreferrer nofollow", target: "_blank" },
      }),
      Table.configure({ resizable: true, lastColumnResizable: true }),
      TableRow,
      TableHeader,
      TableCell,
      PageBreak,
      CommentHighlight.configure({ threads: commentThreads || [] }),
    ],
    onUpdate: ({ editor }) => {
      if (onUpdate) onUpdate(editor);
    },
  });

  if (editable && onImageUpload) {
    element.addEventListener("paste", (event) => handlePasteOrDrop(event, editor, onImageUpload));
    element.addEventListener("drop", (event) => handlePasteOrDrop(event, editor, onImageUpload));
  }

  return editor;
}

function handlePasteOrDrop(event, editor, onImageUpload) {
  const files = Array.from(event.clipboardData?.files || event.dataTransfer?.files || []);
  const imageFiles = files.filter((f) => f.type.startsWith("image/"));
  if (imageFiles.length === 0) return;

  event.preventDefault();
  for (const file of imageFiles) {
    onImageUpload(file).then((url) => {
      editor.chain().focus().setImage({ src: url }).run();
    });
  }
}

function setCommentThreads(editor, threads) {
  editor.view.dispatch(editor.view.state.tr.setMeta(commentPluginKey, threads));
}

function getSelectionRange(editor) {
  const { from, to } = editor.state.selection;
  if (from === to) return null;
  return { from, to, text: editor.state.doc.textBetween(from, to, " ") };
}

window.RedscribeEditor = { mount, setCommentThreads, getSelectionRange };
