from django.contrib import admin

from .models import (
    Hospital,
    Department,
    Building,
    Floor,
    Ward,
    Room,
    Bed,
)


@admin.register(Hospital)
class HospitalAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "code",
        "registration_number",
        "city",
        "state",
        "phone",
        "is_active",
    )

    list_filter = (
        "is_active",
        "state",
        "city",
    )

    search_fields = (
        "name",
        "code",
        "registration_number",
        "phone",
        "email",
        "city",
    )

    list_editable = (
        "is_active",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Hospital Information",
            {
                "fields": (
                    "name",
                    "code",
                    "registration_number",
                    "logo",
                )
            },
        ),
        (
            "Contact Information",
            {
                "fields": (
                    "email",
                    "phone",
                    "emergency_phone",
                    "website",
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
            "Status",
            {
                "fields": (
                    "is_active",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "code",
        "hospital",
        "head",
        "phone",
        "is_active",
    )

    list_filter = (
        "hospital",
        "is_active",
    )

    search_fields = (
        "name",
        "code",
        "hospital__name",
        "head__username",
        "head__first_name",
        "head__last_name",
    )

    list_editable = (
        "is_active",
    )

    autocomplete_fields = (
        "hospital",
        "head",
    )


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "code",
        "hospital",
        "is_active",
    )

    list_filter = (
        "hospital",
        "is_active",
    )

    search_fields = (
        "name",
        "code",
        "hospital__name",
    )

    list_editable = (
        "is_active",
    )

    autocomplete_fields = (
        "hospital",
    )


@admin.register(Floor)
class FloorAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "number",
        "building",
        "is_active",
    )

    list_filter = (
        "building__hospital",
        "building",
        "is_active",
    )

    search_fields = (
        "name",
        "building__name",
    )

    list_editable = (
        "is_active",
    )

    autocomplete_fields = (
        "building",
    )


@admin.register(Ward)
class WardAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "code",
        "ward_type",
        "floor",
        "department",
        "capacity",
        "is_active",
    )

    list_filter = (
        "ward_type",
        "floor__building__hospital",
        "department",
        "is_active",
    )

    search_fields = (
        "name",
        "code",
        "floor__name",
        "floor__building__name",
        "department__name",
    )

    list_editable = (
        "is_active",
    )

    autocomplete_fields = (
        "floor",
        "department",
    )


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):

    list_display = (
        "room_number",
        "room_type",
        "ward",
        "capacity",
        "is_active",
    )

    list_filter = (
        "room_type",
        "ward__floor__building__hospital",
        "ward",
        "is_active",
    )

    search_fields = (
        "room_number",
        "ward__name",
        "ward__code",
    )

    list_editable = (
        "is_active",
    )

    autocomplete_fields = (
        "ward",
    )


@admin.register(Bed)
class BedAdmin(admin.ModelAdmin):

    list_display = (
        "bed_number",
        "bed_type",
        "status",
        "room",
        "daily_charge",
        "is_active",
    )

    list_filter = (
        "status",
        "bed_type",
        "room__ward__floor__building__hospital",
        "room__ward",
        "is_active",
    )

    search_fields = (
        "bed_number",
        "room__room_number",
        "room__ward__name",
        "room__ward__code",
    )

    list_editable = (
        "status",
        "daily_charge",
        "is_active",
    )

    autocomplete_fields = (
        "room",
    )
