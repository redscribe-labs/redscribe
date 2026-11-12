from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.accounts.fields import keep_current_user_selectable

from apps.checklist.models import ChecklistTemplate
from apps.clients.models import Client

from .models import AssetCategory, Engagement, EngagementMembership, ScopeAsset, ScopeChangeRequest

User = get_user_model()

_CLIENT_FIELD_KWARGS = dict(
    queryset=Client.objects.filter(is_active=True), required=False,
    label="Client portal company (optional)",
    help_text="Links this engagement to a client-portal company, so its users can see it. "
    "Separate from the client name above, which is just display text.",
)


def _hide_client_field_for_non_client_managers(form, requesting_user) -> None:
    if requesting_user is None:
        return
    if requesting_user.has_permission("clients.manage"):
        return
    del form.fields["client"]


class _DateRangeCleanMixin:
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "End date can't be earlier than the start date.")
        return cleaned_data


def _set_default_role_field_querysets(form) -> None:
    from apps.findings.review import bulk_eligible_qa_candidates, bulk_eligible_reviewer_candidates

    form.fields["default_reviewer"].queryset = bulk_eligible_reviewer_candidates()
    form.fields["default_reviewer"].help_text = (
        "Auto-assigned to every eligible finding the moment this engagement moves to In Review."
    )
    qa_candidates = bulk_eligible_qa_candidates()
    form.fields["default_qa"].queryset = qa_candidates
    form.fields["default_qa"].help_text = "Auto-assigned to every eligible finding the moment this engagement moves to QA."
    form.fields["default_approver"].queryset = qa_candidates
    form.fields["default_approver"].help_text = (
        "The only person (besides a Superadmin/Team Lead) who can approve this engagement once QA is done."
    )
    # On edit, keep whoever is set now even if they've since been deactivated, so saving the
    # form for another change doesn't clear them. They aren't auto-assigned while inactive.
    instance = form.instance if form.instance.pk else None
    for name in ("default_reviewer", "default_qa", "default_approver"):
        keep_current_user_selectable(form.fields[name], getattr(instance, name) if instance else None)


class EngagementCreateForm(_DateRangeCleanMixin, forms.ModelForm):
    client = forms.ModelChoiceField(
        queryset=Client.objects.filter(is_active=True),
        required=True,
        label="Client",
        help_text="The client-portal company this engagement belongs to.",
    )

    class Meta:
        model = Engagement
        fields = [
            "client", "reference_number", "test_type", "start_date", "end_date",
            "default_reviewer", "default_qa", "default_approver",
        ]
        widgets = {
            "start_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "text", "data-redscribe-datepicker": "true", "autocomplete": "off"},
            ),
            "end_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "text", "data-redscribe-datepicker": "true", "autocomplete": "off"},
            ),
        }

    def __init__(self, *args, requesting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        _hide_client_field_for_non_client_managers(self, requesting_user)
        _set_default_role_field_querysets(self)
        # Not saved on the engagement: the view starts a run from it.
        self.fields["checklist_template"] = forms.ModelChoiceField(
            queryset=ChecklistTemplate.objects.all(), required=False, label="Testing checklist",
            empty_label="Don't start a checklist yet",
            initial=ChecklistTemplate.objects.filter(is_default=True).first(),
            help_text="Starts a checklist run from this template. You can add more runs later from the Checklist tab.",
        )


class EngagementEditForm(_DateRangeCleanMixin, forms.ModelForm):
    client = forms.ModelChoiceField(**_CLIENT_FIELD_KWARGS)

    class Meta:
        model = Engagement
        fields = [
            "client_name", "client", "reference_number", "test_type", "start_date", "end_date",
            "default_reviewer", "default_qa", "default_approver",
        ]
        widgets = {
            "start_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "text", "data-redscribe-datepicker": "true", "autocomplete": "off"},
            ),
            "end_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "text", "data-redscribe-datepicker": "true", "autocomplete": "off"},
            ),
        }

    def __init__(self, *args, requesting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        _hide_client_field_for_non_client_managers(self, requesting_user)
        _set_default_role_field_querysets(self)
        # Keep the linked company choosable after it's deactivated, so saving doesn't unlink it.
        if "client" in self.fields and self.instance.client_id:
            field = self.fields["client"]
            field.queryset = Client.objects.filter(Q(is_active=True) | Q(pk=self.instance.client_id))
            field.label_from_instance = lambda c: str(c) if c.is_active else f"{c} (inactive)"


class ScopeChangeRequestForm(forms.ModelForm):
    class Meta:
        model = ScopeChangeRequest
        fields = ["proposed_scope"]
        widgets = {"proposed_scope": forms.Textarea(attrs={"rows": 5})}


class AssetCategoryForm(forms.ModelForm):
    class Meta:
        model = AssetCategory
        # `order` is intentionally excluded — it's not rendered and defaults to
        # 0 on the model; including it would make it a required form field.
        fields = ["name"]

    def __init__(self, *args, engagement=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.engagement = engagement

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if self.engagement is not None and name:
            clash = AssetCategory.objects.filter(engagement=self.engagement, name__iexact=name)
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise forms.ValidationError("This engagement already has a category with that name.")
        return name


class ScopeAssetForm(forms.ModelForm):
    class Meta:
        model = ScopeAsset
        # `order` excluded for the same reason as AssetCategoryForm.
        fields = ["category", "asset_type", "value", "description"]
        widgets = {
            "value": forms.TextInput(attrs={"placeholder": "e.g. 10.0.0.0/24 or https://app.example.com"}),
            "description": forms.Textarea(attrs={"rows": 2, "placeholder": "Inclusion notes (optional)"}),
        }

    def __init__(self, *args, engagement=None, **kwargs):
        super().__init__(*args, **kwargs)
        if engagement is not None:
            self.fields["category"].queryset = engagement.asset_categories.all()
        self.fields["category"].empty_label = None


class AddMemberForm(forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.none(), label="Add member")

    def __init__(self, *args, engagement=None, **kwargs):
        super().__init__(*args, **kwargs)
        existing_member_ids = EngagementMembership.objects.filter(
            engagement=engagement
        ).values_list("user_id", flat=True)
        self.fields["user"].queryset = (
            User.objects.filter(is_active=True)
            .exclude(id__in=existing_member_ids)
            .exclude(role__slug="client")
            .order_by("username")
        )
