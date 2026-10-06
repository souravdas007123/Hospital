from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):

    list_display = (
        "username",
        "employee_id",
        "first_name",
        "last_name",
        "role",
        "department",
        "phone",
        "is_active",
        "is_staff",
    )

    list_filter = (
        "role",
        "department",
        "is_active",
        "is_staff",
    )

    search_fields = (
        "username",
        "employee_id",
        "first_name",
        "last_name",
        "email",
        "phone",
    )

    ordering = ("username",)

    fieldsets = UserAdmin.fieldsets + (
        (
            "Hospital Information",
            {
                "fields": (
                    "employee_id",
                    "role",
                    "phone",
                    "department",
                )
            },
        ),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Hospital Information",
            {
                "fields": (
                    "employee_id",
                    "role",
                    "phone",
                    "department",
                )
            },
        ),
    )