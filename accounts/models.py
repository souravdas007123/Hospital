from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrator"
        DOCTOR = "DOCTOR", "Doctor"
        NURSE = "NURSE", "Nurse"
        RECEPTIONIST = "RECEPTIONIST", "Receptionist"
        LAB_TECHNICIAN = "LAB_TECHNICIAN", "Lab Technician"
        PHARMACIST = "PHARMACIST", "Pharmacist"
        ACCOUNTANT = "ACCOUNTANT", "Accountant"
        HR = "HR", "HR"
        MANAGER = "MANAGER", "Hospital Manager"
        STAFF = "STAFF", "Staff"

    role = models.CharField(
        max_length=30,
        choices=Role.choices,
        default=Role.STAFF,
    )

    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
    )

    employee_id = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
    )

    department = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.username} - {self.get_role_display()}"