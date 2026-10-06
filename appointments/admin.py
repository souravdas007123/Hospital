from django.contrib import admin

from .models import Appointment


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):

    list_display = (
        "appointment_number",
        "appointment_date",
        "start_time",
        "token_number",
        "patient_display",
        "doctor_display",
        "department",
        "appointment_type",
        "status",
        "booking_source",
    )

    list_filter = (
        "status",
        "appointment_type",
        "booking_source",
        "appointment_date",
        "department",
        "doctor",
    )

    search_fields = (
        "appointment_number",
        "patient__uhid",
        "patient__first_name",
        "patient__middle_name",
        "patient__last_name",
        "patient__phone",
        "doctor__doctor_id",
        "doctor__user__first_name",
        "doctor__user__last_name",
        "token_number",
    )

    autocomplete_fields = (
        "patient",
        "doctor",
        "department",
        "schedule",
        "created_by",
    )

    readonly_fields = (
        "appointment_number",
        "created_at",
        "updated_at",
        "checked_in_at",
        "completed_at",
        "cancelled_at",
    )

    date_hierarchy = "appointment_date"

    ordering = (
        "appointment_date",
        "start_time",
        "token_number",
    )

    list_per_page = 50

    fieldsets = (
        (
            "Appointment Information",
            {
                "fields": (
                    "appointment_number",
                    "patient",
                    "doctor",
                    "department",
                    "schedule",
                )
            },
        ),
        (
            "Appointment Slot",
            {
                "fields": (
                    "appointment_date",
                    "start_time",
                    "end_time",
                    "token_number",
                )
            },
        ),
        (
            "Appointment Details",
            {
                "fields": (
                    "appointment_type",
                    "status",
                    "booking_source",
                    "chief_complaint",
                    "notes",
                )
            },
        ),
        (
            "Cancellation",
            {
                "fields": (
                    "cancellation_reason",
                    "cancelled_at",
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
                    "checked_in_at",
                    "completed_at",
                )
            },
        ),
    )

    @admin.display(
        description="Patient",
        ordering="patient__first_name",
    )
    def patient_display(self, obj):
        return f"{obj.patient.uhid} - {obj.patient.full_name}"

    @admin.display(
        description="Doctor",
        ordering="doctor__user__first_name",
    )
    def doctor_display(self, obj):
        return f"Dr. {obj.doctor.user.get_full_name()}"

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)