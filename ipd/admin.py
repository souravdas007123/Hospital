from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.shortcuts import render
from django.utils.html import format_html

from hospitals.models import Bed, Department, Room, Ward

from .models import (
    IPDAdmission,
    IPDBedTransfer,
    IPDDoctorAssignment,
    IPDDoctorNote,
)
from .services import (
    transfer_patient_bed,
    assign_ipd_doctor,
    remove_ipd_doctor,
    create_ipd_doctor_note,
)


class IPDBedTransferForm(forms.Form):
    """
    Form used from IPD Admission admin to transfer a patient.
    """

    to_ward = forms.ModelChoiceField(
        queryset=Ward.objects.all(),
        label="New Ward",
    )

    to_room = forms.ModelChoiceField(
        queryset=Room.objects.all(),
        label="New Room",
    )

    to_bed = forms.ModelChoiceField(
        queryset=Bed.objects.filter(
            status="AVAILABLE"
        ),
        label="New Bed",
    )

    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
            }
        ),
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()

        ward = cleaned_data.get("to_ward")
        room = cleaned_data.get("to_room")
        bed = cleaned_data.get("to_bed")

        if ward and room:

            if (
                hasattr(room, "ward_id")
                and room.ward_id
                and room.ward_id != ward.pk
            ):
                self.add_error(
                    "to_room",
                    "Selected room does not belong to selected ward.",
                )

        if room and bed:

            if (
                hasattr(bed, "room_id")
                and bed.room_id
                and bed.room_id != room.pk
            ):
                self.add_error(
                    "to_bed",
                    "Selected bed does not belong to selected room.",
                )

        return cleaned_data


@admin.register(IPDAdmission)
class IPDAdmissionAdmin(admin.ModelAdmin):

    list_display = (
        "admission_number",
        "patient",
        "doctor",
        "department",
        "ward",
        "room",
        "bed",
        "admission_type",
        "admission_date",
        "status_badge",
    )

    list_filter = (
        "status",
        "admission_type",
        "department",
        "ward",
        "admission_date",
    )

    search_fields = (
        "admission_number",
        "patient__uhid",
        "patient__first_name",
        "patient__last_name",
        "patient__phone",
        "doctor__username",
        "doctor__first_name",
        "doctor__last_name",
        "bed__name",
        "room__name",
        "ward__name",
    )

    autocomplete_fields = (
        "patient",
        "doctor",
        "department",
        "ward",
        "room",
        "bed",
    )

    readonly_fields = (
        "admission_number",
        "created_by",
        "created_at",
        "updated_at",
    )

    date_hierarchy = "admission_date"

    ordering = (
        "-admission_date",
        "-id",
    )

    actions = (
        "transfer_selected_patients",
    )

    fieldsets = (
        (
            "Admission Information",
            {
                "fields": (
                    "admission_number",
                    "patient",
                    "admission_type",
                    "admission_date",
                    "status",
                )
            },
        ),
        (
            "Doctor & Department",
            {
                "fields": (
                    "doctor",
                    "department",
                )
            },
        ),
        (
            "Bed Allocation",
            {
                "fields": (
                    "ward",
                    "room",
                    "bed",
                )
            },
        ),
        (
            "Clinical Information",
            {
                "fields": (
                    "reason_for_admission",
                    "provisional_diagnosis",
                    "notes",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def save_model(
        self,
        request,
        obj,
        form,
        change,
    ):

        if not change and not obj.created_by:
            obj.created_by = request.user

        super().save_model(
            request,
            obj,
            form,
            change,
        )

    @admin.display(
        description="Status",
    )
    def status_badge(self, obj):

        if obj.status == IPDAdmission.Status.ADMITTED:

            return format_html(
                '<span style="'
                'background:#198754;'
                'color:white;'
                'padding:4px 9px;'
                'border-radius:12px;'
                'font-weight:600;'
                '">'
                'ADMITTED'
                '</span>'
            )

        if obj.status == IPDAdmission.Status.ON_HOLD:

            return format_html(
                '<span style="'
                'background:#ffc107;'
                'color:#212529;'
                'padding:4px 9px;'
                'border-radius:12px;'
                'font-weight:600;'
                '">'
                'ON HOLD'
                '</span>'
            )

        if obj.status == IPDAdmission.Status.DISCHARGED:

            return format_html(
                '<span style="'
                'background:#0d6efd;'
                'color:white;'
                'padding:4px 9px;'
                'border-radius:12px;'
                'font-weight:600;'
                '">'
                'DISCHARGED'
                '</span>'
            )

        return format_html(
            '<span style="'
            'background:#dc3545;'
            'color:white;'
            'padding:4px 9px;'
            'border-radius:12px;'
            'font-weight:600;'
            '">'
            'CANCELLED'
            '</span>'
        )

    @admin.action(
        description="Transfer selected patient(s) to another bed"
    )
    def transfer_selected_patients(
        self,
        request,
        queryset,
    ):

        admissions = queryset.filter(
            status__in=[
                IPDAdmission.Status.ADMITTED,
                IPDAdmission.Status.ON_HOLD,
            ]
        )

        if not admissions.exists():

            self.message_user(
                request,
                "Please select at least one active IPD admission.",
                level=messages.ERROR,
            )

            return None

        if admissions.count() > 1:

            self.message_user(
                request,
                "Please transfer one patient at a time.",
                level=messages.ERROR,
            )

            return None

        admission = admissions.first()

        if request.POST.get("confirm_transfer"):

            form = IPDBedTransferForm(
                request.POST
            )

            if form.is_valid():

                try:

                    transfer = transfer_patient_bed(
                        admission=admission,
                        to_ward=form.cleaned_data["to_ward"],
                        to_room=form.cleaned_data["to_room"],
                        to_bed=form.cleaned_data["to_bed"],
                        user=request.user,
                        reason=form.cleaned_data["reason"],
                        notes=form.cleaned_data["notes"],
                    )

                    self.message_user(
                        request,
                        (
                            f"Patient {transfer.patient} successfully "
                            f"transferred to "
                            f"{transfer.to_bed}."
                        ),
                        level=messages.SUCCESS,
                    )

                    return None

                except ValidationError as exc:

                    self.message_user(
                        request,
                        exc.message
                        if hasattr(exc, "message")
                        else str(exc),
                        level=messages.ERROR,
                    )

                    return None

        else:

            form = IPDBedTransferForm()

        context = {
            **self.admin_site.each_context(request),
            "title": "Transfer Patient Bed",
            "admission": admission,
            "form": form,
            "opts": self.model._meta,
            "has_view_permission": True,
        }

        return render(
            request,
            "admin/ipd/ipdadmission/transfer_bed.html",
            context,
        )


@admin.register(IPDBedTransfer)
class IPDBedTransferAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "admission",
        "patient",
        "from_bed",
        "to_bed",
        "transfer_date",
        "transferred_by",
    )

    list_filter = (
        "transfer_date",
        "to_ward",
        "to_room",
    )

    search_fields = (
        "admission__admission_number",
        "patient__uhid",
        "patient__first_name",
        "patient__last_name",
        "patient__phone",
        "from_bed__name",
        "to_bed__name",
    )

    autocomplete_fields = (
        "admission",
        "patient",
        "from_ward",
        "from_room",
        "from_bed",
        "to_ward",
        "to_room",
        "to_bed",
        "transferred_by",
    )

    readonly_fields = (
        "transfer_date",
        "created_at",
        "transferred_by",
    )

    date_hierarchy = "transfer_date"

    ordering = (
        "-transfer_date",
        "-id",
    )

    fieldsets = (
        (
            "Admission",
            {
                "fields": (
                    "admission",
                    "patient",
                )
            },
        ),
        (
            "Previous Location",
            {
                "fields": (
                    "from_ward",
                    "from_room",
                    "from_bed",
                )
            },
        ),
        (
            "New Location",
            {
                "fields": (
                    "to_ward",
                    "to_room",
                    "to_bed",
                )
            },
        ),
        (
            "Transfer Details",
            {
                "fields": (
                    "transfer_date",
                    "reason",
                    "notes",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "transferred_by",
                    "created_at",
                )
            },
        ),
    )

    def has_add_permission(
        self,
        request,
    ):
        return False

    def has_change_permission(
        self,
        request,
        obj=None,
    ):
        return False

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        return False


@admin.register(IPDDoctorAssignment)
class IPDDoctorAssignmentAdmin(admin.ModelAdmin):

    list_display = (
        "admission",
        "patient_name",
        "doctor",
        "role",
        "assigned_date",
        "end_date",
        "active_badge",
    )

    list_filter = (
        "role",
        "is_active",
        "assigned_date",
    )

    search_fields = (
        "admission__admission_number",
        "admission__patient__uhid",
        "admission__patient__first_name",
        "admission__patient__last_name",
        "doctor__username",
        "doctor__first_name",
        "doctor__last_name",
    )

    autocomplete_fields = (
        "admission",
        "doctor",
        "assigned_by",
    )

    readonly_fields = (
        "assigned_date",
        "end_date",
        "assigned_by",
        "created_at",
        "updated_at",
    )

    ordering = (
        "-assigned_date",
        "-id",
    )

    @admin.display(
        description="Patient"
    )
    def patient_name(self, obj):
        return obj.admission.patient

    @admin.display(
        description="Status"
    )
    def active_badge(self, obj):

        if obj.is_active:

            return format_html(
                '<span style="'
                'background:#198754;'
                'color:white;'
                'padding:4px 9px;'
                'border-radius:12px;'
                'font-weight:600;'
                '">'
                'ACTIVE'
                '</span>'
            )

        return format_html(
            '<span style="'
            'background:#6c757d;'
            'color:white;'
            'padding:4px 9px;'
            'border-radius:12px;'
            'font-weight:600;'
            '">'
            'ENDED'
            '</span>'
        )

    def save_model(
        self,
        request,
        obj,
        form,
        change,
    ):

        if not change and not obj.assigned_by:
            obj.assigned_by = request.user

        super().save_model(
            request,
            obj,
            form,
            change,
        )


@admin.register(IPDDoctorNote)
class IPDDoctorNoteAdmin(admin.ModelAdmin):

    list_display = (
        "admission",
        "patient_name",
        "doctor",
        "note_type",
        "note_date",
    )

    list_filter = (
        "note_type",
        "note_date",
    )

    search_fields = (
        "admission__admission_number",
        "admission__patient__uhid",
        "admission__patient__first_name",
        "admission__patient__last_name",
        "doctor__username",
        "doctor__first_name",
        "doctor__last_name",
        "clinical_note",
    )

    autocomplete_fields = (
        "admission",
        "doctor",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    date_hierarchy = "note_date"

    ordering = (
        "-note_date",
        "-id",
    )

    @admin.display(
        description="Patient"
    )
    def patient_name(self, obj):
        return obj.admission.patient    