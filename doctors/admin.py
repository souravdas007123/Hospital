from django.contrib import admin

from .models import (
    Doctor,
    DoctorAvailability,
    DoctorSchedule,
)


class DoctorAvailabilityInline(
    admin.TabularInline
):

    model = DoctorAvailability

    extra = 0

    fields = (
        "day_of_week",
        "start_time",
        "end_time",
        "consultation_duration",
        "max_patients",
        "is_available",
    )


class DoctorScheduleInline(
    admin.TabularInline
):

    model = DoctorSchedule

    extra = 0

    fields = (
        "schedule_name",
        "department",
        "day_of_week",
        "start_time",
        "end_time",
        "room_name",
        "max_patients",
        "consultation_duration",
        "is_active",
    )


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):

    list_display = (
        "doctor_id",
        "doctor_name",
        "specialization",
        "department",
        "medical_registration_number",
        "consultation_fee",
        "is_available",
        "is_active",
    )

    list_filter = (
        "department",
        "specialization",
        "is_available",
        "is_active",
    )

    search_fields = (
        "doctor_id",
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
        "medical_registration_number",
        "specialization",
    )

    readonly_fields = (
        "doctor_id",
        "created_at",
        "updated_at",
    )

    autocomplete_fields = (
        "user",
        "department",
    )

    list_editable = (
        "is_available",
        "is_active",
    )

    inlines = [
        DoctorAvailabilityInline,
        DoctorScheduleInline,
    ]

    fieldsets = (

        (
            "Doctor Account",
            {
                "fields": (
                    "user",
                    "doctor_id",
                )
            },
        ),

        (
            "Professional Information",
            {
                "fields": (
                    "department",
                    "specialization",
                    "sub_specialization",
                    "qualification",
                    "medical_registration_number",
                    "medical_registration_council",
                    "experience_years",
                )
            },
        ),

        (
            "Personal Information",
            {
                "fields": (
                    "profile_photo",
                    "gender",
                    "date_of_birth",
                    "bio",
                )
            },
        ),

        (
            "Contact Information",
            {
                "fields": (
                    "phone",
                    "email",
                )
            },
        ),

        (
            "Consultation Fees",
            {
                "fields": (
                    "consultation_fee",
                    "followup_fee",
                    "emergency_fee",
                )
            },
        ),

        (
            "Availability",
            {
                "fields": (
                    "is_available",
                    "is_active",
                )
            },
        ),

        (
            "System Information",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(
        description="Doctor",
        ordering="user__first_name",
    )
    def doctor_name(self, obj):

        name = obj.user.get_full_name()

        if name:
            return f"Dr. {name}"

        return obj.user.username


@admin.register(DoctorAvailability)
class DoctorAvailabilityAdmin(admin.ModelAdmin):

    list_display = (
        "doctor",
        "day_of_week",
        "start_time",
        "end_time",
        "consultation_duration",
        "max_patients",
        "is_available",
    )

    list_filter = (
        "day_of_week",
        "is_available",
        "doctor__department",
    )

    search_fields = (
        "doctor__doctor_id",
        "doctor__user__first_name",
        "doctor__user__last_name",
    )

    autocomplete_fields = (
        "doctor",
    )


@admin.register(DoctorSchedule)
class DoctorScheduleAdmin(admin.ModelAdmin):

    list_display = (
        "schedule_name",
        "doctor",
        "department",
        "day_of_week",
        "start_time",
        "end_time",
        "room_name",
        "max_patients",
        "is_active",
    )

    list_filter = (
        "day_of_week",
        "department",
        "is_active",
    )

    search_fields = (
        "schedule_name",
        "doctor__doctor_id",
        "doctor__user__first_name",
        "doctor__user__last_name",
        "room_name",
    )

    autocomplete_fields = (
        "doctor",
        "department",
    )