from django import forms
from django.contrib.auth import get_user_model

from apps.clients.models import Client

from .models import Engagement, EngagementMembership, ScopeChangeRequest

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
            "client", "reference_number", "scope", "start_date", "end_date",
            "default_reviewer", "default_qa", "default_approver",
        ]
        widgets = {
            "scope": forms.Textarea(attrs={"rows": 5}),
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


class EngagementEditForm(_DateRangeCleanMixin, forms.ModelForm):
    client = forms.ModelChoiceField(**_CLIENT_FIELD_KWARGS)

    class Meta:
        model = Engagement
        fields = [
            "client_name", "client", "reference_number", "start_date", "end_date",
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


class ScopeChangeRequestForm(forms.ModelForm):
    class Meta:
        model = ScopeChangeRequest
        fields = ["proposed_scope"]
        widgets = {"proposed_scope": forms.Textarea(attrs={"rows": 5})}


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
