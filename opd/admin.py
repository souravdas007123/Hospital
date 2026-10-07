from django.contrib import admin

from .models import (
    OPDVisit,
    PatientVital,
    OPDConsultation,
    OPDDiagnosis,
    OPDFollowUp,
)


class PatientVitalInline(admin.StackedInline):
    model = PatientVital
    extra = 0
    max_num = 1

    readonly_fields = (
        "recorded_at",
        "updated_at",
    )


class OPDConsultationInline(admin.StackedInline):
    model = OPDConsultation
    extra = 0
    max_num = 1

    readonly_fields = (
        "consultation_start",
        "consultation_end",
        "created_at",
        "updated_at",
    )


class OPDDiagnosisInline(admin.TabularInline):
    model = OPDDiagnosis
    extra = 0

    autocomplete_fields = (
        "diagnosed_by",
    )

    readonly_fields = (
        "created_at",
    )


class OPDFollowUpInline(admin.TabularInline):
    model = OPDFollowUp
    extra = 0

    autocomplete_fields = (
        "patient",
        "doctor",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(OPDVisit)
class OPDVisitAdmin(admin.ModelAdmin):

    list_display = (
        "visit_number",
        "visit_date",
        "patient_display",
        "doctor_display",
        "department",
        "appointment",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
        "visit_date",
        "department",
        "doctor",
    )

    search_fields = (
        "visit_number",
        "appointment__appointment_number",
        "patient__uhid",
        "patient__first_name",
        "patient__middle_name",
        "patient__last_name",
        "patient__phone",
        "doctor__doctor_id",
        "doctor__user__first_name",
        "doctor__user__last_name",
    )

    autocomplete_fields = (
        "appointment",
        "patient",
        "doctor",
        "department",
        "created_by",
    )

    readonly_fields = (
        "visit_number",
        "created_at",
        "updated_at",
        "completed_at",
    )

    date_hierarchy = "visit_date"

    ordering = (
        "-visit_date",
        "-created_at",
    )

    list_per_page = 50

    fieldsets = (
        (
            "OPD Visit Information",
            {
                "fields": (
                    "visit_number",
                    "appointment",
                    "patient",
                    "doctor",
                    "department",
                    "visit_date",
                    "status",
                )
            },
        ),
        (
            "Patient Complaint",
            {
                "fields": (
                    "chief_complaint",
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
                    "completed_at",
                )
            },
        ),
    )

    inlines = (
        PatientVitalInline,
        OPDConsultationInline,
        OPDDiagnosisInline,
        OPDFollowUpInline,
    )

    @admin.display(
        description="Patient",
        ordering="patient__first_name",
    )
    def patient_display(self, obj):
        return (
            f"{obj.patient.uhid} - "
            f"{obj.patient.full_name}"
        )

    @admin.display(
        description="Doctor",
        ordering="doctor__user__first_name",
    )
    def doctor_display(self, obj):
        return (
            f"Dr. "
            f"{obj.doctor.user.get_full_name()}"
        )

    def save_model(self, request, obj, form, change):

        if not obj.created_by_id:
            obj.created_by = request.user

        super().save_model(
            request,
            obj,
            form,
            change,
        )


@admin.register(PatientVital)
class PatientVitalAdmin(admin.ModelAdmin):

    list_display = (
        "opd_visit",
        "patient_display",
        "temperature",
        "blood_pressure",
        "pulse_rate",
        "spo2",
        "weight",
        "recorded_by",
        "recorded_at",
    )

    list_filter = (
        "recorded_at",
    )

    search_fields = (
        "opd_visit__visit_number",
        "opd_visit__patient__uhid",
        "opd_visit__patient__first_name",
        "opd_visit__patient__last_name",
    )

    autocomplete_fields = (
        "opd_visit",
        "recorded_by",
    )

    readonly_fields = (
        "recorded_at",
        "updated_at",
    )

    @admin.display(
        description="Patient",
    )
    def patient_display(self, obj):
        return obj.opd_visit.patient.full_name

    @admin.display(
        description="Blood Pressure",
    )
    def blood_pressure(self, obj):

        if obj.systolic_bp and obj.diastolic_bp:
            return f"{obj.systolic_bp}/{obj.diastolic_bp}"

        return "-"


@admin.register(OPDConsultation)
class OPDConsultationAdmin(admin.ModelAdmin):

    list_display = (
        "opd_visit",
        "patient_display",
        "doctor_display",
        "consultation_start",
        "consultation_end",
        "created_at",
    )

    search_fields = (
        "opd_visit__visit_number",
        "opd_visit__patient__uhid",
        "opd_visit__patient__first_name",
        "opd_visit__patient__last_name",
        "opd_visit__doctor__doctor_id",
        "opd_visit__doctor__user__first_name",
        "opd_visit__doctor__user__last_name",
    )

    autocomplete_fields = (
        "opd_visit",
    )

    readonly_fields = (
        "consultation_start",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Visit",
            {
                "fields": (
                    "opd_visit",
                )
            },
        ),
        (
            "Clinical Information",
            {
                "fields": (
                    "symptoms",
                    "clinical_findings",
                    "examination",
                    "diagnosis_summary",
                    "treatment_plan",
                    "advice",
                    "doctor_notes",
                )
            },
        ),
        (
            "Consultation Time",
            {
                "fields": (
                    "consultation_start",
                    "consultation_end",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(
        description="Patient",
    )
    def patient_display(self, obj):
        return obj.opd_visit.patient.full_name

    @admin.display(
        description="Doctor",
    )
    def doctor_display(self, obj):
        return (
            f"Dr. "
            f"{obj.opd_visit.doctor.user.get_full_name()}"
        )


@admin.register(OPDDiagnosis)
class OPDDiagnosisAdmin(admin.ModelAdmin):

    list_display = (
        "opd_visit",
        "patient_display",
        "diagnosis_type",
        "diagnosis",
        "diagnosed_by",
        "created_at",
    )

    list_filter = (
        "diagnosis_type",
        "created_at",
    )

    search_fields = (
        "diagnosis",
        "opd_visit__visit_number",
        "opd_visit__patient__uhid",
        "opd_visit__patient__first_name",
        "opd_visit__patient__last_name",
    )

    autocomplete_fields = (
        "opd_visit",
        "diagnosed_by",
    )

    readonly_fields = (
        "created_at",
    )

    @admin.display(
        description="Patient",
    )
    def patient_display(self, obj):
        return obj.opd_visit.patient.full_name


@admin.register(OPDFollowUp)
class OPDFollowUpAdmin(admin.ModelAdmin):

    list_display = (
        "followup_date",
        "patient",
        "doctor",
        "opd_visit",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
        "followup_date",
    )

    search_fields = (
        "patient__uhid",
        "patient__first_name",
        "patient__last_name",
        "doctor__doctor_id",
        "doctor__user__first_name",
        "doctor__user__last_name",
        "opd_visit__visit_number",
    )

    autocomplete_fields = (
        "opd_visit",
        "patient",
        "doctor",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    date_hierarchy = "followup_date"
