from django.utils import timezone

from apps.crypto.services import decrypt_or_blank, encrypt_bytes, record_aad

from .models import ChecklistItem, ChecklistItemEvent, ChecklistRun, ChecklistTemplate


def instantiate_checklist(
    engagement, template: ChecklistTemplate | None = None, label: str = "", created_by=None,
) -> ChecklistRun:
    if template is None:
        template = ChecklistTemplate.objects.filter(is_default=True).first()
    if template is None:
        raise ValueError("No checklist template is set as default.")

    label = (label.strip() or template.name)[:255]
    run = ChecklistRun.objects.create(
        engagement=engagement, template=template, label=label, created_by=created_by,
    )
    items = [
        ChecklistItem(
            run=run,
            category=ti.category,
            code=ti.code,
            title=ti.title,
            reference_info=ti.reference_info,
            order=ti.order,
        )
        for ti in template.items.all()
    ]
    ChecklistItem.objects.bulk_create(items)
    return run


def encrypt_item_text(item, field, text, project_key):
    """Ciphertext for one of a checklist item's encrypted text fields, bound to
    the item and field name so it can't be swapped onto another row."""
    if not text:
        return None
    return encrypt_bytes(text.encode("utf-8"), project_key, associated_data=record_aad("checklistitem", item.pk, field))


def decrypt_item_text(item, field, project_key):
    ciphertext = getattr(item, f"{field}_ciphertext")
    return decrypt_or_blank(ciphertext, project_key, associated_data=record_aad("checklistitem", item.pk, field))


def link_raised_finding(item: ChecklistItem, finding, actor) -> None:
    """Links a finding raised from this check and, if the check hadn't been
    tested yet, marks it "Finding raised". Both are recorded in its activity."""
    before = item.findings.count()
    item.findings.add(finding)
    events = [ChecklistItemEvent(
        item=item, actor=actor, kind=ChecklistItemEvent.Kind.FINDINGS,
        from_value=str(before), to_value=str(before + 1),
    )]
    if item.status == ChecklistItem.Status.NOT_TESTED:
        labels = dict(ChecklistItem.Status.choices)
        events.append(ChecklistItemEvent(
            item=item, actor=actor, kind=ChecklistItemEvent.Kind.STATUS,
            from_value=labels[item.status], to_value=labels[ChecklistItem.Status.TESTED_FINDING_RAISED],
        ))
        item.status = ChecklistItem.Status.TESTED_FINDING_RAISED
        item.tested_by, item.tested_at = actor, timezone.now()
        item.save(update_fields=["status", "tested_by", "tested_at", "updated_at"])
    ChecklistItemEvent.objects.bulk_create(events)
