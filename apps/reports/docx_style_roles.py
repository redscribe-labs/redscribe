# The fixed set of content roles RedScribe needs a Word style for. Each
# role is mapped, per Report Profile, to one of the *superadmin's own*
# style names discovered from their uploaded .docx (see docx_styles.py) —
# never a style name RedScribe invents or requires them to match exactly.
#
# (role_key, human label shown in the mapping UI, style-type bucket)
STYLE_ROLES = [
    ("body_paragraph", "Body paragraph", "paragraph"),
    ("heading_1", "Heading 1 (e.g. a content-section label)", "paragraph"),
    ("heading_2", "Heading 2", "paragraph"),
    ("heading_3", "Heading 3", "paragraph"),
    ("heading_4", "Heading 4", "paragraph"),
    ("heading_5", "Heading 5", "paragraph"),
    ("heading_6", "Heading 6", "paragraph"),
    ("bullet_list", "Bulleted list item", "paragraph"),
    ("numbered_list", "Numbered list item", "paragraph"),
    ("code_block", "Code block", "paragraph"),
    ("blockquote", "Block quote", "paragraph"),
    ("image_caption", "Image caption", "paragraph"),
    ("table_normal", "Table (breakdown of findings, checklist coverage, document control)", "table"),
    ("table_header_cell_text", "Table header cell text", "paragraph"),
    ("inline_code", "Inline code (character style)", "character"),
]

STYLE_ROLE_KEYS = {role_key for role_key, _label, _bucket in STYLE_ROLES}
