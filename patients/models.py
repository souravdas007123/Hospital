import uuid

from django.conf import settings
from django.db import models


class Patient(models.Model):

    class Gender(models.TextChoices):
        MALE = "MALE", "Male"
        FEMALE = "FEMALE", "Female"
        OTHER = "OTHER", "Other"

    class BloodGroup(models.TextChoices):
        A_POSITIVE = "A+", "A+"
        A_NEGATIVE = "A-", "A-"
        B_POSITIVE = "B+", "B+"
        B_NEGATIVE = "B-", "B-"
        AB_POSITIVE = "AB+", "AB+"
        AB_NEGATIVE = "AB-", "AB-"
        O_POSITIVE = "O+", "O+"
        O_NEGATIVE = "O-", "O-"
        UNKNOWN = "UNKNOWN", "Unknown"

    # ---------------------------------------------------------
    # PATIENT IDENTITY
    # ---------------------------------------------------------

    uhid = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
        db_index=True,
    )

    registration_date = models.DateTimeField(
        auto_now_add=True
    )

    # ---------------------------------------------------------
    # PERSONAL INFORMATION
    # ---------------------------------------------------------

    first_name = models.CharField(
        max_length=100
    )

    middle_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    last_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    date_of_birth = models.DateField(
        blank=True,
        null=True,
    )

    gender = models.CharField(
        max_length=20,
        choices=Gender.choices,
    )

    blood_group = models.CharField(
        max_length=10,
        choices=BloodGroup.choices,
        default=BloodGroup.UNKNOWN,
    )

    photo = models.ImageField(
        upload_to="patients/photos/",
        blank=True,
        null=True,
    )

    # ---------------------------------------------------------
    # CONTACT INFORMATION
    # ---------------------------------------------------------

    phone = models.CharField(
        max_length=20,
        db_index=True,
    )

    alternate_phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
    )

    email = models.EmailField(
        blank=True,
        null=True,
    )

    # ---------------------------------------------------------
    # ADDRESS
    # ---------------------------------------------------------

    address_line_1 = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    address_line_2 = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    city = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    state = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    country = models.CharField(
        max_length=100,
        default="India",
    )

    postal_code = models.CharField(
        max_length=20,
        blank=True,
        null=True,
    )

    # ---------------------------------------------------------
    # EMERGENCY CONTACT
    # ---------------------------------------------------------

    emergency_contact_name = models.CharField(
        max_length=150,
        blank=True,
        null=True,
    )

    emergency_contact_relation = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    emergency_contact_phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
    )

    # ---------------------------------------------------------
    # MEDICAL INFORMATION
    # ---------------------------------------------------------

    allergies = models.TextField(
        blank=True,
        null=True,
        help_text="Known drug, food or other allergies.",
    )

    chronic_conditions = models.TextField(
        blank=True,
        null=True,
        help_text="Known long-term medical conditions.",
    )

    medical_history = models.TextField(
        blank=True,
        null=True,
    )

    current_medications = models.TextField(
        blank=True,
        null=True,
    )

    # ---------------------------------------------------------
    # IDENTIFICATION
    # ---------------------------------------------------------

    national_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
    )

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    is_active = models.BooleanField(
        default=True
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="registered_patients",
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    # ---------------------------------------------------------
    # META
    # ---------------------------------------------------------

    class Meta:
        verbose_name = "Patient"
        verbose_name_plural = "Patients"
        ordering = ["-registration_date"]

    # ---------------------------------------------------------
    # METHODS
    # ---------------------------------------------------------

    def save(self, *args, **kwargs):

        if not self.uhid:
            self.uhid = self.generate_uhid()

        super().save(*args, **kwargs)

    @staticmethod
    def generate_uhid():

        return f"UHID-{uuid.uuid4().hex[:10].upper()}"

    @property
    def full_name(self):

        parts = [
            self.first_name,
            self.middle_name,
            self.last_name,
        ]

        return " ".join(
            part for part in parts if part
        )

    def __str__(self):

        return f"{self.uhid} - {self.full_name}"


class PatientDocument(models.Model):

    class DocumentType(models.TextChoices):
        ID_PROOF = "ID_PROOF", "ID Proof"
        INSURANCE = "INSURANCE", "Insurance"
        MEDICAL_REPORT = "MEDICAL_REPORT", "Medical Report"
        PRESCRIPTION = "PRESCRIPTION", "Prescription"
        LAB_REPORT = "LAB_REPORT", "Lab Report"
        DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY", "Discharge Summary"
        OTHER = "OTHER", "Other"

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="documents",
    )

    document_type = models.CharField(
        max_length=50,
        choices=DocumentType.choices,
    )

    title = models.CharField(
        max_length=255,
    )

    file = models.FileField(
        upload_to="patients/documents/",
    )

    description = models.TextField(
        blank=True,
        null=True,
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="uploaded_patient_documents",
    )

    uploaded_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "Patient Document"
        verbose_name_plural = "Patient Documents"
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.patient.uhid} - {self.title}"   
