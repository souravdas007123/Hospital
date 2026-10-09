from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from hospitals.models import Bed, Room, Ward

from .models import (
    IPDAdmission,
    IPDBedTransfer,
    IPDDoctorAssignment,
    IPDDoctorNote,
    IPDNursingVital,
    IPDNursingNote,
    IPDMedicationOrder,
    IPDMedicationAdministration,
)

from .services import (
    transfer_patient_bed,
    assign_ipd_doctor,
    remove_ipd_doctor,
    create_ipd_doctor_note,
    discharge_ipd_patient,
)


ACTIVE_STATUSES = ("ADMITTED", "ON_HOLD")


# ============================================================
# BED TRANSFER FORM
# ============================================================

class IPDBedTransferForm(forms.Form):
    to_ward = forms.ModelChoiceField(
        queryset=Ward.objects.all(),
        label="New Ward",
    )

    to_room = forms.ModelChoiceField(
        queryset=Room.objects.all(),
        label="New Room",
    )

    to_bed = forms.ModelChoiceField(
        queryset=Bed.objects.filter(status="AVAILABLE"),
        label="New Bed",
    )

    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def clean(self):
        cleaned_data = super().clean()

        ward = cleaned_data.get("to_ward")
        room = cleaned_data.get("to_room")
        bed = cleaned_data.get("to_bed")

        if ward and room and room.ward_id != ward.pk:
            self.add_error(
                "to_room",
                "Selected room does not belong to selected ward.",
            )

        if room and bed and bed.room_id != room.pk:
            self.add_error(
                "to_bed",
                "Selected bed does not belong to selected room.",
            )

        return cleaned_data


# ============================================================
# DISCHARGE FORM
# ============================================================

class IPDDischargeForm(forms.Form):
    final_diagnosis = forms.CharField(
        label="Final Diagnosis",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    treatment_summary = forms.CharField(
        label="Treatment Summary",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    discharge_instructions = forms.CharField(
        label="Discharge Instructions",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    discharge_disposition = forms.ChoiceField(
        label="Discharge Disposition",
        choices=IPDAdmission.DischargeDisposition.choices,
    )


# ============================================================
# IPD ADMISSION ADMIN
# ============================================================

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
        "discharge_date",
        "status_badge",
        "discharge_action",
    )

    list_filter = (
        "status",
        "admission_type",
        "department",
        "ward",
        "admission_date",
        "discharge_disposition",
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
        "discharge_date",
        "final_diagnosis",
        "treatment_summary",
        "discharge_instructions",
        "discharge_disposition",
    )

    date_hierarchy = "admission_date"
    ordering = ("-admission_date", "-id")
    actions = ("transfer_selected_patients",)

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
            "Discharge Information",
            {
                "fields": (
                    "discharge_date",
                    "final_diagnosis",
                    "treatment_summary",
                    "discharge_instructions",
                    "discharge_disposition",
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

    def get_readonly_fields(self, request, obj=None):
        fields = list(
            super().get_readonly_fields(request, obj)
        )

        # Existing admission status must be changed through
        # controlled workflows, not directly in the edit form.
        if obj:
            fields.append("status")

        # Closed admissions cannot be edited.
        if obj and obj.status in (
            IPDAdmission.Status.DISCHARGED,
            IPDAdmission.Status.CANCELLED,
        ):
            fields.extend(
                [
                    "patient",
                    "doctor",
                    "department",
                    "ward",
                    "room",
                    "bed",
                    "admission_type",
                    "admission_date",
                    "reason_for_admission",
                    "provisional_diagnosis",
                    "notes",
                ]
            )

        return tuple(dict.fromkeys(fields))

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

    @admin.display(description="Status")
    def status_badge(self, obj):
        styles = {
            IPDAdmission.Status.ADMITTED: (
                "#198754",
                "ADMITTED",
            ),
            IPDAdmission.Status.ON_HOLD: (
                "#ffc107",
                "ON HOLD",
            ),
            IPDAdmission.Status.DISCHARGED: (
                "#0d6efd",
                "DISCHARGED",
            ),
            IPDAdmission.Status.CANCELLED: (
                "#dc3545",
                "CANCELLED",
            ),
        }

        color, label = styles.get(
            obj.status,
            ("#6c757d", str(obj.status)),
        )

        text_color = (
            "#212529"
            if color == "#ffc107"
            else "#ffffff"
        )

        return format_html(
            '<span style="background:{};color:{};'
            'padding:4px 9px;border-radius:12px;'
            'font-weight:600;">{}</span>',
            color,
            text_color,
            label,
        )

    @admin.display(description="Discharge")
    def discharge_action(self, obj):
        if obj.status not in ACTIVE_STATUSES:
            return "—"

        url = reverse(
            "admin:ipd_ipdadmission_discharge",
            args=[obj.pk],
        )

        return format_html(
            '<a class="button" href="{}">Discharge</a>',
            url,
        )

    # --------------------------------------------------------
    # BED TRANSFER ACTION
    # --------------------------------------------------------

    @admin.action(
        description="Transfer selected patient to another bed"
    )
    def transfer_selected_patients(self, request, queryset):
        admissions = queryset.filter(
            status__in=ACTIVE_STATUSES
        )

        if admissions.count() != 1 or queryset.count() != 1:
            self.message_user(
                request,
                "Please select exactly one active admission.",
                level=messages.ERROR,
            )
            return None

        admission = admissions.first()

        if request.POST.get("confirm_transfer"):
            form = IPDBedTransferForm(request.POST)

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

                except (ValidationError, ValueError) as exc:
                    form.add_error(None, str(exc))

                else:
                    self.message_user(
                        request,
                        f"Patient transferred to {transfer.to_bed}.",
                        level=messages.SUCCESS,
                    )

                    return redirect(
                        reverse("admin:ipd_ipdadmission_changelist")
                    )
        else:
            form = IPDBedTransferForm()

        context = {
            **self.admin_site.each_context(request),
            "title": "Transfer Patient Bed",
            "admission": admission,
            "form": form,
            "opts": self.model._meta,
        }

        return render(
            request,
            "admin/ipd/ipdadmission/transfer_bed.html",
            context,
        )

    # --------------------------------------------------------
    # CUSTOM ADMIN URLS
    # --------------------------------------------------------

    
def get_urls(self):
    urls = super().get_urls()

    custom_urls = [
        path(
            "<int:admission_id>/discharge/",
            self.admin_site.admin_view(self.discharge_view),
            name="ipd_ipdadmission_discharge",
        ),
        path(
            "<int:admission_id>/discharge-pdf/",
            self.admin_site.admin_view(self.discharge_pdf_view),
            name="ipd_ipdadmission_discharge_pdf",
        ),
    ]

    return custom_urls + urls

    # --------------------------------------------------------
    # DISCHARGE VIEW
    # --------------------------------------------------------

    def discharge_view(self, request, admission_id):
        admission = get_object_or_404(
            IPDAdmission,
            pk=admission_id,
        )

        if not self.has_change_permission(request, admission):
            self.message_user(
                request,
                "You do not have permission to discharge this admission.",
                level=messages.ERROR,
            )
            return redirect(
                reverse("admin:ipd_ipdadmission_changelist")
            )

        if admission.status not in ACTIVE_STATUSES:
            self.message_user(
                request,
                "Only an active admission can be discharged.",
                level=messages.ERROR,
            )
            return redirect(
                reverse(
                    "admin:ipd_ipdadmission_change",
                    args=[admission.pk],
                )
            )

        if request.method == "POST":
            form = IPDDischargeForm(request.POST)

            if form.is_valid():
                try:
                    discharge_ipd_patient(
                        admission=admission,
                        user=request.user,
                        **form.cleaned_data,
                    )

                except (ValidationError, ValueError) as exc:
                    if hasattr(exc, "messages"):
                        form.add_error(None, " ".join(exc.messages))
                    else:
                        form.add_error(None, str(exc))

                else:
                    self.message_user(
                        request,
                        "Patient discharged successfully. "
                        "Please verify the bed is now available.",
                        level=messages.SUCCESS,
                    )

                    return redirect(
                        reverse(
                            "admin:ipd_ipdadmission_change",
                            args=[admission.pk],
                        )
                    )
        else:
            form = IPDDischargeForm()

        context = {
            **self.admin_site.each_context(request),
            "title": f"Discharge {admission.admission_number}",
            "admission": admission,
            "form": form,
            "opts": self.model._meta,
        }

        return TemplateResponse(
            request,
            "admin/ipd/ipdadmission/discharge.html",
            context,
        )

    def discharge_pdf_action(self, obj):
        if not obj:
            return "—"

        url = reverse(
            "admin:ipd_ipdadmission_discharge_pdf",
            args=[obj.pk],
        )
        return format_html('<a class="button" href="{}" target="_blank">View PDF</a>', url)


    discharge_pdf_action.short_description = "Discharge PDF"


    
def discharge_pdf_view(self, request, admission_id):
    from django.core.exceptions import PermissionDenied
    from django.shortcuts import get_object_or_404
    from .pdf_utils import discharge_pdf_response

    if not self.has_view_or_change_permission(request):
        raise PermissionDenied

    admission = get_object_or_404(IPDAdmission, pk=admission_id)

    if admission.status != IPDAdmission.Status.DISCHARGED:
        self.message_user(
            request,
            "PDF sirf discharged patient ke liye available hai.",
            level=messages.WARNING,
        )
        return redirect(
            reverse("admin:ipd_ipdadmission_change", args=[admission.pk])
        )

    return discharge_pdf_response(admission)

# ============================================================
# BED TRANSFER ADMIN
# ============================================================


@admin.register(IPDBedTransfer)
class IPDBedTransferAdmin(admin.ModelAdmin):

    list_display = (
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
    ordering = ("-transfer_date", "-id")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ============================================================
# DOCTOR ASSIGNMENT ADMIN
# ============================================================

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

    ordering = ("-assigned_date", "-id")

    @admin.display(description="Patient")
    def patient_name(self, obj):
        return obj.admission.patient

    @admin.display(description="Status")
    def active_badge(self, obj):
        color = "#198754" if obj.is_active else "#6c757d"
        label = "ACTIVE" if obj.is_active else "ENDED"

        return format_html(
            '<span style="background:{};color:#fff;'
            'padding:4px 9px;border-radius:12px;'
            'font-weight:600;">{}</span>',
            color,
            label,
        )

    def save_model(self, request, obj, form, change):
        if not change and not obj.assigned_by_id:
            obj.assigned_by = request.user

        super().save_model(request, obj, form, change)


# ============================================================
# DOCTOR NOTE ADMIN
# ============================================================

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
    ordering = ("-note_date", "-id")

    @admin.display(description="Patient")
    def patient_name(self, obj):
        return obj.admission.patient


# ============================================================
# NURSING VITAL ADMIN
# ============================================================

@admin.register(IPDNursingVital)
class IPDNursingVitalAdmin(admin.ModelAdmin):

    list_display = (
        "admission",
        "patient",
        "recorded_at",
        "temperature",
        "systolic_bp",
        "diastolic_bp",
        "pulse",
        "spo2",
        "recorded_by",
    )

    list_filter = (
        "recorded_at",
        "recorded_by",
    )

    search_fields = (
        "admission__admission_number",
        "patient__uhid",
        "patient__first_name",
        "patient__last_name",
    )

    autocomplete_fields = (
        "admission",
        "patient",
        "recorded_by",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    date_hierarchy = "recorded_at"
    list_per_page = 25


# ============================================================
# NURSING NOTE ADMIN
# ============================================================

@admin.register(IPDNursingNote)
class IPDNursingNoteAdmin(admin.ModelAdmin):

    list_display = (
        "admission",
        "patient",
        "note_type",
        "note_date",
        "nurse",
    )

    list_filter = (
        "note_type",
        "note_date",
        "nurse",
    )

    search_fields = (
        "admission__admission_number",
        "patient__uhid",
        "patient__first_name",
        "patient__last_name",
        "notes",
    )

    autocomplete_fields = (
        "admission",
        "patient",
        "nurse",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    date_hierarchy = "note_date"
    list_per_page = 25


# ============================================================
# MEDICATION ORDER ADMIN
# ============================================================

@admin.register(IPDMedicationOrder)
class IPDMedicationOrderAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "admission",
        "patient",
        "medicine",
        "dose",
        "frequency",
        "start_date",
        "end_date",
        "status",
    )

    list_filter = (
        "status",
        "route",
        "start_date",
    )

    search_fields = (
        "admission__admission_number",
        "patient__uhid",
        "patient__first_name",
        "patient__last_name",
        "medicine__name",
    )

    autocomplete_fields = (
        "admission",
        "patient",
        "medicine",
        "prescribed_by",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    date_hierarchy = "start_date"
    list_per_page = 25


# ============================================================
# MEDICATION ADMINISTRATION ADMIN
# ============================================================

@admin.register(IPDMedicationAdministration)
class IPDMedicationAdministrationAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "admission",
        "patient",
        "medication_order",
        "scheduled_at",
        "status",
        "quantity_given",
        "administered_by",
    )

    list_filter = (
        "status",
        "scheduled_at",
    )

    search_fields = (
        "admission__admission_number",
        "patient__uhid",
        "patient__first_name",
        "patient__last_name",
        "medication_order__medicine__name",
    )

    autocomplete_fields = (
        "medication_order",
        "admission",
        "patient",
        "medicine_batch",
        "administered_by",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    date_hierarchy = "scheduled_at"
    list_per_page = 25
