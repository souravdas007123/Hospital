
from django import forms

from ipd.models import IPDAdmission


class IPDDischargeForm(forms.Form):
    final_diagnosis = forms.CharField(
        label="Final Diagnosis",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    treatment_summary = forms.CharField(
        label="Treatment Summary",
        widget=forms.Textarea(attrs={"rows": 5}),
    )

    discharge_instructions = forms.CharField(
        label="Discharge Instructions",
        widget=forms.Textarea(attrs={"rows": 5}),
    )

    discharge_disposition = forms.ChoiceField(
        label="Discharge Disposition",
        choices=IPDAdmission.DischargeDisposition.choices,
    )