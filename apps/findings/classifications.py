from .models import ClassificationTag


def parse_classification_rows(post_data):
    taxonomies = post_data.getlist("classification_taxonomy")
    values = post_data.getlist("classification_value")
    rows = []
    for taxonomy, value in zip(taxonomies, values):
        taxonomy = taxonomy.strip()
        value = value.strip()
        if not taxonomy and not value:
            continue
        rows.append({"taxonomy": taxonomy, "value": value})
    return rows


def validate_classification_rows(rows, require_at_least_one=True):
    errors = []
    if require_at_least_one and not rows:
        errors.append("Add at least one classification.")
    for row in rows:
        if not row["taxonomy"]:
            errors.append(f"Choose or type a taxonomy for classification '{row['value']}'.")
        if not row["value"]:
            errors.append(f"Add a value for the '{row['taxonomy']}' classification.")
    return errors


def save_classification_rows(rows):
    seen = set()
    tags = []
    for row in rows:
        key = (row["taxonomy"], row["value"])
        if key in seen:
            continue
        seen.add(key)
        tag, _ = ClassificationTag.objects.get_or_create(taxonomy=row["taxonomy"], value=row["value"])
        tags.append(tag)
    return tags


def classification_rows_for(instance):
    return [{"taxonomy": t.taxonomy, "value": t.value} for t in instance.classifications.all()]


def classification_suggestions():
    suggestions = {}
    for taxonomy, value in ClassificationTag.objects.order_by("taxonomy", "value").values_list("taxonomy", "value"):
        suggestions.setdefault(taxonomy, []).append(value)
    return suggestions
