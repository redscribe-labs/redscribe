from .models import ChecklistItem, ChecklistRun, ChecklistTemplate


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
