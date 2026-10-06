from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType


# ============================================================
# ROLE → APP ACCESS CONFIGURATION
# ============================================================

ROLE_PERMISSIONS = {

    "Administrator": {
        "apps": [
            "accounts",
            "hospitals",
            "patients",
            "doctors",
            "appointments",
            "opd",
            "ipd",
            "emergency",
            "nursing",
            "laboratory",
            "pharmacy",
            "billing",
            "insurance",
        ],
        "actions": ["view", "add", "change", "delete"],
    },

    "Doctor": {
        "apps": [
            "patients",
            "doctors",
            "appointments",
            "opd",
            "ipd",
            "emergency",
            "laboratory",
        ],
        "actions": ["view", "add", "change"],
    },

    "Nurse": {
        "apps": [
            "patients",
            "appointments",
            "opd",
            "ipd",
            "emergency",
            "nursing",
        ],
        "actions": ["view", "add", "change"],
    },

    "Receptionist": {
        "apps": [
            "patients",
            "appointments",
            "opd",
        ],
        "actions": ["view", "add", "change"],
    },

    "Lab Technician": {
        "apps": [
            "patients",
            "laboratory",
        ],
        "actions": ["view", "add", "change"],
    },

    "Pharmacist": {
        "apps": [
            "patients",
            "pharmacy",
        ],
        "actions": ["view", "add", "change"],
    },

    "Accountant": {
        "apps": [
            "patients",
            "billing",
            "insurance",
        ],
        "actions": ["view", "add", "change"],
    },

    "HR": {
        "apps": [
            "accounts",
            "hospitals",
        ],
        "actions": ["view", "add", "change"],
    },

    "Hospital Manager": {
        "apps": [
            "accounts",
            "hospitals",
            "patients",
            "doctors",
            "appointments",
            "opd",
            "ipd",
            "emergency",
            "nursing",
            "laboratory",
            "pharmacy",
            "billing",
            "insurance",
        ],
        "actions": ["view", "add", "change"],
    },

    "Staff": {
        "apps": [
            "patients",
            "appointments",
        ],
        "actions": ["view"],
    },
}


# ============================================================
# CREATE GROUPS
# ============================================================

def create_role_groups():

    for role_name, config in ROLE_PERMISSIONS.items():

        group, created = Group.objects.get_or_create(
            name=role_name
        )

        # Existing permissions clear kar do
        group.permissions.clear()

        permissions = Permission.objects.filter(
            content_type__app_label__in=config["apps"]
        )

        permissions = permissions.filter(
            codename__regex=r"^("
            + "|".join(config["actions"])
            + r")_"
        )

        group.permissions.set(permissions)

        group.save()

        if created:
            print(f"Created group: {role_name}")
        else:
            print(f"Updated group: {role_name}")

    print("All HMS role groups configured successfully.")