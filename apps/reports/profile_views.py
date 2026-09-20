import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import get_valid_filename, slugify

from apps.accounts.permissions import require_permission
from apps.findings.models import Finding

from django.http import HttpResponse
from django.utils import timezone

from .block_registry import BLOCK_REGISTRY
from .docx_placeholders import (
    available_finding_rich_tags,
    available_finding_tags,
    available_text_block_tags,
    available_top_level_loop_tags,
    available_top_level_rich_tags,
    available_top_level_tags,
)
from .docx_styles import discover_styles
from .docx_style_roles import STYLE_ROLES
from .docx_template_validation import DocxTemplateValidationError, dry_run_render, validate_docx_template
from .forms import ExportLimitsForm
from .google_fonts import GoogleFontFetchError, fetch_and_cache_font
from .labels import LABEL_GROUPS
from .models import CachedGoogleFont, PLACEHOLDER_HELP, ReportProfile, ReportSettings, ReportTextBlockDefinition
from .profile_forms import (
    ReportDocxStyleMapForm,
    ReportDocxTemplateUploadForm,
    ReportProfileCreateForm,
    ReportProfileTemplateForm,
    ReportSharedTextBlockContentForm,
    ReportTextBlockCreateForm,
    ReportTextBlockFormSet,
)


def _require(request):
    require_permission(request.user, "report_settings.manage", "manage report profiles")


def _ensure_font_cached(request, family: str, field_label: str):
    if not family or CachedGoogleFont.objects.filter(family=family).exists():
        return
    try:
        fetch_and_cache_font(family)
    except GoogleFontFetchError as exc:
        messages.warning(
            request,
            f'{field_label} "{family}" could not be fetched from Google Fonts ({exc}) — '
            "it'll fall back to whatever's installed wherever the report is viewed.",
        )


def _safe_next(request, profile) -> str:
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}):
        return candidate
    return reverse("report_profiles:edit", args=[profile.pk])


def _text_block_formset_context(request, profile):
    create_form = ReportTextBlockCreateForm(prefix="create")
    formset = ReportTextBlockFormSet(queryset=ReportTextBlockDefinition.objects.filter(profile=profile))

    if request.method == "POST" and request.POST.get("action") == "create_text_block":
        create_form = ReportTextBlockCreateForm(request.POST, prefix="create")
        if create_form.is_valid():
            block = create_form.save(commit=False)
            block.profile = profile
            block.slug = _unique_slug(block.label, profile)
            block.updated_by = request.user
            block.save()
            messages.success(request, f"Text block '{block.label}' added.")
            return create_form, formset, redirect(_safe_next(request, profile))
    elif request.method == "POST" and request.POST.get("action") == "save_text_blocks":
        formset = ReportTextBlockFormSet(request.POST, queryset=ReportTextBlockDefinition.objects.filter(profile=profile))
        if formset.is_valid():
            instances = formset.save(commit=False)
            for instance in instances:
                instance.profile = profile
                instance.updated_by = request.user
                instance.save()
            messages.success(request, "Report text blocks updated.")
            return create_form, formset, redirect(_safe_next(request, profile))

    return create_form, formset, None


def _unique_slug(label: str, profile) -> str:
    base = slugify(label).replace("-", "_")[:64] or "block"
    slug = base
    suffix = 2
    while ReportTextBlockDefinition.objects.filter(profile=profile, slug=slug).exists():
        slug = f"{base[:60]}_{suffix}"
        suffix += 1
    return slug


@login_required
def report_profile_list(request):
    _require(request)
    settings_obj = ReportSettings.get_solo()
    create_form = ReportProfileCreateForm(prefix="create")
    limits_form = ExportLimitsForm(initial={"max_concurrent_report_jobs": settings_obj.max_concurrent_report_jobs})

    if request.method == "POST" and request.POST.get("action") == "create":
        create_form = ReportProfileCreateForm(request.POST, prefix="create")
        if create_form.is_valid():
            profile = create_form.save(commit=False)
            profile.created_by = request.user
            profile.save()
            messages.success(request, f"Profile '{profile.name}' created — write its document to build it.")
            return redirect("report_profiles:edit", pk=profile.pk)
    elif request.method == "POST" and request.POST.get("action") == "export_limits":
        limits_form = ExportLimitsForm(request.POST)
        if limits_form.is_valid():
            if limits_form.cleaned_data["max_concurrent_report_jobs"] is not None:
                settings_obj.max_concurrent_report_jobs = limits_form.cleaned_data["max_concurrent_report_jobs"]
                settings_obj.updated_by = request.user
                settings_obj.save(update_fields=["max_concurrent_report_jobs", "updated_by", "updated_at"])
            messages.success(request, "Export limits updated.")
            return redirect("report_profiles:list")

    return render(
        request, "reports/profile_list.html",
        {
            "profiles": ReportProfile.objects.all(), "create_form": create_form, "limits_form": limits_form,
            "breadcrumbs": [{"label": "Report Profiles"}],
        },
    )


@login_required
def report_profile_set_default(request, pk):
    _require(request)
    profile = get_object_or_404(ReportProfile, pk=pk)
    if request.method == "POST":
        with transaction.atomic():
            ReportProfile.objects.filter(is_default=True).exclude(pk=profile.pk).update(is_default=False)
            profile.is_default = True
            profile.save(update_fields=["is_default"])
        messages.success(request, f"'{profile.name}' is now the default report profile.")
    return redirect("report_profiles:list")


@login_required
def report_profile_delete(request, pk):
    _require(request)
    profile = get_object_or_404(ReportProfile, pk=pk)

    if profile.is_default:
        messages.error(
            request,
            f"'{profile.name}' is the default profile — set a different profile as default before deleting it.",
        )
        return redirect("report_profiles:list")

    if request.method == "POST":
        if ReportProfile.objects.count() <= 1:
            messages.error(request, "Can't delete the only remaining report profile.")
            return redirect("report_profiles:list")
        name = profile.name
        profile.delete()
        messages.success(request, f"Profile '{name}' deleted.")
        return redirect("report_profiles:list")

    return render(
        request, "reports/profile_delete_confirm.html",
        {"profile": profile, "breadcrumbs": [
            {"label": "Report Profiles", "url": reverse("report_profiles:list")}, {"label": f"Delete {profile.name}"},
        ]},
    )


@login_required
def report_profile_edit(request, pk):
    _require(request)
    profile = get_object_or_404(ReportProfile, pk=pk)

    text_block_create_form, text_block_formset, _response = _text_block_formset_context(request, profile)

    if request.method == "POST":
        form = ReportProfileTemplateForm(request.POST, request.FILES, profile=profile)
        if form.is_valid():
            raw_template = form.cleaned_data["template"]
            try:
                parsed_template = json.loads(raw_template) if raw_template else {}
            except (TypeError, ValueError):
                parsed_template = {}
            profile.template = parsed_template if isinstance(parsed_template, dict) else {}
            profile.cover_title = form.cleaned_data["cover_title"]
            profile.classification_label = form.cleaned_data["classification_label"]
            profile.finding_id_prefix = form.cleaned_data["finding_id_prefix"]
            profile.body_font = form.cleaned_data["body_font"]
            profile.monospace_font = form.cleaned_data["monospace_font"]
            profile.bullet_character = form.cleaned_data["bullet_character"]
            profile.table_header_color = form.cleaned_data["table_header_color"] or "rgba(248,250,252,1)"
            profile.empty_cell_background_color = (
                form.cleaned_data["empty_cell_background_color"] or "rgba(237,238,238,1)"
            )
            profile.finding_table_layout = (
                form.cleaned_data["finding_table_layout"] or ReportProfile.FindingTableLayout.TABLE
            )
            severity_colors = {}
            for severity, _label in Finding.Severity.choices:
                severity_colors[severity] = {
                    "open": form.cleaned_data[f"severity_color__{severity}__open"],
                    "closed": form.cleaned_data[f"severity_color__{severity}__closed"],
                }
            profile.severity_colors = severity_colors
            from .labels import LABEL_DEFAULTS

            profile.labels = {
                key: form.cleaned_data[f"label__{key}"] for key in LABEL_DEFAULTS if form.cleaned_data[f"label__{key}"]
            }
            profile.save()
            _ensure_font_cached(request, profile.body_font, "Body font")
            _ensure_font_cached(request, profile.monospace_font, "Monospace font")
            messages.success(request, f"Profile '{profile.name}' updated.")
            return redirect("report_profiles:edit", pk=profile.pk)
    else:
        initial = {
            "template": json.dumps(profile.template) if profile.template else "",
            "cover_title": profile.cover_title,
            "classification_label": profile.classification_label,
            "finding_id_prefix": profile.finding_id_prefix,
            "body_font": profile.body_font,
            "monospace_font": profile.monospace_font,
            "bullet_character": profile.bullet_character,
            "table_header_color": profile.table_header_color,
            "empty_cell_background_color": profile.empty_cell_background_color,
            "finding_table_layout": profile.finding_table_layout,
        }
        form = ReportProfileTemplateForm(initial=initial, profile=profile)

    return render(
        request, "reports/profile_edit.html",
        {
            "profile": profile, "form": form,
            "structural_tags": sorted(BLOCK_REGISTRY),
            "custom_tags": form.text_blocks,
            "placeholders": PLACEHOLDER_HELP,
            "text_block_create_form": text_block_create_form,
            "text_block_formset": text_block_formset,
            "text_block_manage_url": reverse("report_profiles:text_blocks", args=[profile.pk]),
            "severity_color_fields": [
                (label, form[f"severity_color__{severity}__open"], form[f"severity_color__{severity}__closed"])
                for severity, label in Finding.Severity.choices
            ],
            "label_groups": [
                (group_title, [(field_label, form[f"label__{key}"]) for key, field_label in fields])
                for group_title, fields in LABEL_GROUPS
            ],
            "docx_upload_form": ReportDocxTemplateUploadForm(),
            "docx_top_level_tags": available_top_level_tags(profile),
            "docx_top_level_rich_tags": available_top_level_rich_tags(profile),
            "docx_top_level_loop_tags": available_top_level_loop_tags(profile),
            "docx_text_block_tags": available_text_block_tags(profile),
            "docx_finding_tags": available_finding_tags(profile),
            "docx_finding_rich_tags": available_finding_rich_tags(profile),
            "breadcrumbs": [
                {"label": "Report Profiles", "url": reverse("report_profiles:list")}, {"label": profile.name},
            ],
        },
    )


@login_required
def report_profile_text_blocks(request, pk):
    _require(request)
    profile = get_object_or_404(ReportProfile, pk=pk)
    _create_form, _formset, response = _text_block_formset_context(request, profile)
    if response is not None:
        return response
    return redirect("report_profiles:edit", pk=profile.pk)


@login_required
def report_profile_text_block_edit(request, pk, block_pk):
    _require(request)
    profile = get_object_or_404(ReportProfile, pk=pk)
    block = get_object_or_404(ReportTextBlockDefinition, pk=block_pk, profile=profile)

    current = profile.block_defaults.get(block.slug, "") if isinstance(profile.block_defaults, dict) else ""

    if request.method == "POST":
        form = ReportSharedTextBlockContentForm(request.POST)
        if form.is_valid():
            block_defaults = dict(profile.block_defaults) if isinstance(profile.block_defaults, dict) else {}
            block_defaults[block.slug] = form.cleaned_data["content"]
            profile.block_defaults = block_defaults
            profile.save(update_fields=["block_defaults"])
            messages.success(request, f"'{block.label}' updated.")
            return redirect(f"{reverse('report_profiles:edit', args=[profile.pk])}#section-manage-text-blocks")
    else:
        form = ReportSharedTextBlockContentForm(initial={"content": current})

    return render(
        request, "reports/profile_text_block_edit.html",
        {
            "profile": profile, "block": block, "form": form,
            "breadcrumbs": [
                {"label": "Report Profiles", "url": reverse("report_profiles:list")},
                {"label": profile.name, "url": reverse("report_profiles:edit", args=[profile.pk])},
                {"label": block.label},
            ],
        },
    )




@login_required
def report_text_block_delete(request, pk):
    _require(request)
    block = get_object_or_404(ReportTextBlockDefinition, pk=pk)
    next_url = _safe_next(request, block.profile)
    if request.method == "POST":
        label = block.label
        block.delete()
        messages.success(
            request,
            f"Text block '{label}' deleted — a '{{{{ {block.slug} }}}}' placeholder still in "
            f"'{block.profile.name}'s template is now skipped at render time, not shown as an error.",
        )
        return HttpResponseRedirect(next_url)
    breadcrumbs = [
        {"label": "Report Profiles", "url": reverse("report_profiles:list")},
        {"label": block.profile.name, "url": reverse("report_profiles:edit", args=[block.profile.pk])},
        {"label": f"Delete {block.label}"},
    ]
    return render(
        request, "reports/text_block_delete_confirm.html",
        {"block": block, "next": next_url, "breadcrumbs": breadcrumbs},
    )


@login_required
def report_profile_docx_template(request, pk):
    _require(request)
    profile = get_object_or_404(ReportProfile, pk=pk)

    if request.method == "POST":
        if request.POST.get("action") == "remove":
            profile.docx_template = None
            profile.docx_template_filename = ""
            profile.docx_template_content_type = ""
            profile.docx_template_uploaded_at = None
            profile.docx_style_map = {}
            profile.save(update_fields=[
                "docx_template", "docx_template_filename", "docx_template_content_type",
                "docx_template_uploaded_at", "docx_style_map",
            ])
            messages.success(request, "Word template removed.")
            return redirect(f"{reverse('report_profiles:edit', args=[profile.pk])}#section-docx-template")

        form = ReportDocxTemplateUploadForm(request.POST, request.FILES)
        if form.is_valid():
            upload = form.cleaned_data["docx_template"]
            data = upload.read()
            try:
                validate_docx_template(data)
                # Stash on a throwaway copy so a bad upload never touches
                # the persisted template — dry_run_render needs a saved
                # profile.docx_template to build a DocxTemplate from.
                candidate = ReportProfile(
                    pk=profile.pk, docx_template=data, docx_style_map=profile.docx_style_map,
                    cover_title=profile.cover_title, classification_label=profile.classification_label,
                )
                # pk is set (matching the real, already-saved profile) but this instance is
                # never itself .save()d — dry_run_render's text-block lookup needs a real pk
                # to query profile.text_blocks against, but nothing here touches the DB with
                # the candidate's own (possibly-invalid) field values.
                dry_run_render(candidate)
            except DocxTemplateValidationError as exc:
                messages.error(request, str(exc))
                return redirect(f"{reverse('report_profiles:edit', args=[profile.pk])}#section-docx-template")

            profile.docx_template = data
            profile.docx_template_filename = upload.name
            profile.docx_template_content_type = (
                upload.content_type or "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            profile.docx_template_uploaded_at = timezone.now()
            # A re-upload can change/remove styles the old map pointed at —
            # start the mapping fresh rather than silently keep stale names.
            profile.docx_style_map = {}
            profile.save(update_fields=[
                "docx_template", "docx_template_filename", "docx_template_content_type",
                "docx_template_uploaded_at", "docx_style_map",
            ])
            messages.success(request, "Word template uploaded — now map its styles below.")
            return redirect("report_profiles:docx_style_map", pk=profile.pk)
        messages.error(request, "Couldn't upload that file.")

    return redirect(f"{reverse('report_profiles:edit', args=[profile.pk])}#section-docx-template")


@login_required
def report_profile_docx_style_map(request, pk):
    _require(request)
    profile = get_object_or_404(ReportProfile, pk=pk)
    if not profile.docx_template:
        messages.error(request, "Upload a Word template before mapping its styles.")
        return redirect(f"{reverse('report_profiles:edit', args=[profile.pk])}#section-docx-template")

    discovered = discover_styles(bytes(profile.docx_template))

    if request.method == "POST":
        form = ReportDocxStyleMapForm(request.POST, discovered_styles=discovered, current_map=profile.docx_style_map)
        if form.is_valid():
            style_map = {}
            for role_key, _label, _bucket in STYLE_ROLES:
                value = form.cleaned_data.get(f"role__{role_key}")
                if value:
                    style_map[role_key] = value
            profile.docx_style_map = style_map
            profile.save(update_fields=["docx_style_map"])
            messages.success(request, "Word template style mapping saved.")
            return redirect(f"{reverse('report_profiles:edit', args=[profile.pk])}#section-docx-template")
    else:
        form = ReportDocxStyleMapForm(discovered_styles=discovered, current_map=profile.docx_style_map)

    role_fields = [(label, form[f"role__{role_key}"]) for role_key, label, _bucket in STYLE_ROLES]

    return render(
        request, "reports/profile_docx_style_map.html",
        {
            "profile": profile, "form": form, "role_fields": role_fields,
            "breadcrumbs": [
                {"label": "Report Profiles", "url": reverse("report_profiles:list")},
                {"label": profile.name, "url": reverse("report_profiles:edit", args=[profile.pk])},
                {"label": "Map Word styles"},
            ],
        },
    )


@login_required
def report_profile_docx_template_download(request, pk):
    _require(request)
    profile = get_object_or_404(ReportProfile, pk=pk)
    if not profile.docx_template:
        messages.error(request, "This profile has no Word template uploaded.")
        return redirect(f"{reverse('report_profiles:edit', args=[profile.pk])}#section-docx-template")
    response = HttpResponse(
        bytes(profile.docx_template),
        content_type=profile.docx_template_content_type
        or "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    # docx_template_filename is the original upload's name, stored verbatim
    # (profile_views.py's upload handler) — sanitize before it goes into a
    # header value, since an unescaped `"` in it could break out of the
    # quoted-string filename parameter.
    filename = get_valid_filename(profile.docx_template_filename or "template.docx")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response
