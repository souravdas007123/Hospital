from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User


@receiver(post_save, sender=User)
def assign_user_role_group(sender, instance, created, **kwargs):

    if not instance.role:
        return

    role_group_names = {
        "ADMIN": "Administrator",
        "DOCTOR": "Doctor",
        "NURSE": "Nurse",
        "RECEPTIONIST": "Receptionist",
        "LAB_TECHNICIAN": "Lab Technician",
        "PHARMACIST": "Pharmacist",
        "ACCOUNTANT": "Accountant",
        "HR": "HR",
        "MANAGER": "Hospital Manager",
        "STAFF": "Staff",
    }

    group_name = role_group_names.get(instance.role)

    if not group_name:
        return

    try:
        group = instance.groups.model.objects.get(
            name=group_name
        )
    except instance.groups.model.DoesNotExist:
        return

    # User ke old role groups remove
    instance.groups.remove(
        *instance.groups.model.objects.exclude(
            name=group_name
        )
    )

    # Current role group add
    instance.groups.add(group)