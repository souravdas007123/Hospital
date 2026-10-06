from django.contrib import admin

from .models import Patient, PatientDocument


class PatientDocumentInline(admin.TabularInline):

    model = PatientDocument

    extra = 0

    fields = (
        "document_type",
        "title",
        "file",
        "description",
        "uploaded_by",
        "uploaded_at",
    )

    readonly_fields = (
        "uploaded_at",
    )


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):

    list_display = (
        "uhid",
        "full_name_display",
        "gender",
        "date_of_birth",
        "blood_group",
        "phone",
        "city",
        "registration_date",
        "is_active",
    )

    list_filter = (
        "gender",
        "blood_group",
        "is_active",
        "state",
        "city",
    )

    search_fields = (
        "uhid",
        "first_name",
        "middle_name",
        "last_name",
        "phone",
        "alternate_phone",
        "email",
        "national_id",
        "emergency_contact_name",
        "emergency_contact_phone",
    )

    readonly_fields = (
        "uhid",
        "registration_date",
        "created_at",
        "updated_at",
    )

    list_per_page = 25

    autocomplete_fields = (
        "created_by",
    )

    inlines = [
        PatientDocumentInline,
    ]

    fieldsets = (

        (
            "Patient Identification",
            {
                "fields": (
                    "uhid",
                    "registration_date",
                )
            },
        ),

        (
            "Personal Information",
            {
                "fields": (
                    "photo",
                    "first_name",
                    "middle_name",
                    "last_name",
                    "date_of_birth",
                    "gender",
                    "blood_group",
                )
            },
        ),

        (
            "Contact Information",
            {
                "fields": (
                    "phone",
                    "alternate_phone",
                    "email",
                )
            },
        ),

        (
            "Address",
            {
                "fields": (
                    "address_line_1",
                    "address_line_2",
                    "city",
                    "state",
                    "country",
                    "postal_code",
                )
            },
        ),

        (
            "Emergency Contact",
            {
                "fields": (
                    "emergency_contact_name",
                    "emergency_contact_relation",
                    "emergency_contact_phone",
                )
            },
        ),

        (
            "Medical Information",
            {
                "fields": (
                    "allergies",
                    "chronic_conditions",
                    "medical_history",
                    "current_medications",
                )
            },
        ),

        (
            "Identification",
            {
                "fields": (
                    "national_id",
                )
            },
        ),

        (
            "System Information",
            {
                "fields": (
                    "is_active",
                    "created_by",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(
        description="Patient Name",
        ordering="first_name",
    )
    def full_name_display(self, obj):
        return obj.full_name


@admin.register(PatientDocument)
class PatientDocumentAdmin(admin.ModelAdmin):

    list_display = (
        "patient",
        "document_type",
        "title",
        "uploaded_by",
        "uploaded_at",
    )

    list_filter = (
        "document_type",
        "uploaded_at",
    )

    search_fields = (
        "patient__uhid",
        "patient__first_name",
        "patient__last_name",
        "title",
    )

    autocomplete_fields = (
        "patient",
        "uploaded_by",
    )

    readonly_fields = (
        "uploaded_at",
    )
