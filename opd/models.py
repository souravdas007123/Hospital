from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class OPDVisit(models.Model):

    class Status(models.TextChoices):
        WAITING = "WAITING", "Waiting"
        VITALS_COMPLETED = "VITALS_COMPLETED", "Vitals Completed"
        IN_CONSULTATION = "IN_CONSULTATION", "In Consultation"
        CONSULTATION_COMPLETED = "CONSULTATION_COMPLETED", "Consultation Completed"
        REFERRED = "REFERRED", "Referred"
        ADMITTED = "ADMITTED", "Admitted"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    visit_number = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
        db_index=True,
    )

    appointment = models.OneToOneField(
        "appointments.Appointment",
        on_delete=models.PROTECT,
        related_name="opd_visit",
    )

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="opd_visits",
    )

    doctor = models.ForeignKey(
        "doctors.Doctor",
        on_delete=models.PROTECT,
        related_name="opd_visits",
    )

    department = models.ForeignKey(
        "hospitals.Department",
        on_delete=models.PROTECT,
        related_name="opd_visits",
    )

    visit_date = models.DateField(
        default=timezone.localdate,
        db_index=True,
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.WAITING,
        db_index=True,
    )

    chief_complaint = models.TextField(
        blank=True,
        null=True,
    )

    notes = models.TextField(
        blank=True,
        null=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_opd_visits",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    completed_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = "OPD Visit"
        verbose_name_plural = "OPD Visits"

        ordering = [
            "-visit_date",
            "-created_at",
        ]

        indexes = [
            models.Index(
                fields=[
                    "visit_date",
                    "status",
                ]
            ),
            models.Index(
                fields=[
                    "patient",
                    "visit_date",
                ]
            ),
            models.Index(
                fields=[
                    "doctor",
                    "visit_date",
                ]
            ),
        ]

    def clean(self):
        errors = {}

        if self.appointment_id:

            appointment = self.appointment

            if appointment.patient_id != self.patient_id:
                errors["patient"] = (
                    "Patient does not match the selected appointment."
                )

            if appointment.doctor_id != self.doctor_id:
                errors["doctor"] = (
                    "Doctor does not match the selected appointment."
                )

            if appointment.department_id != self.department_id:
                errors["department"] = (
                    "Department does not match the selected appointment."
                )

            allowed_statuses = [
                appointment.Status.BOOKED,
                appointment.Status.CONFIRMED,
                appointment.Status.CHECKED_IN,
                appointment.Status.IN_CONSULTATION,
                appointment.Status.COMPLETED,
            ]

            if appointment.status not in allowed_statuses:
                errors["appointment"] = (
                    "This appointment cannot be converted into an OPD visit."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):

        if not self.visit_number:

            today = timezone.localdate()

            prefix = f"OPD-{today.strftime('%Y%m%d')}-"

            last_visit = (
                OPDVisit.objects
                .filter(
                    visit_number__startswith=prefix
                )
                .order_by("-id")
                .first()
            )

            if last_visit:
                try:
                    last_number = int(
                        last_visit.visit_number.split("-")[-1]
                    )
                except (ValueError, IndexError):
                    last_number = 0
            else:
                last_number = 0

            self.visit_number = (
                f"{prefix}{last_number + 1:04d}"
            )

        if self.status == self.Status.COMPLETED:
            if not self.completed_at:
                self.completed_at = timezone.now()

        self.full_clean()

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.visit_number} | "
            f"{self.patient.full_name} | "
            f"Dr. {self.doctor.user.get_full_name()}"
        )


class PatientVital(models.Model):

    opd_visit = models.OneToOneField(
        OPDVisit,
        on_delete=models.CASCADE,
        related_name="vitals",
    )

    temperature = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Temperature in °F",
    )

    systolic_bp = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Systolic blood pressure",
    )

    diastolic_bp = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Diastolic blood pressure",
    )

    pulse_rate = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Pulse rate per minute",
    )

    respiratory_rate = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Respiratory rate per minute",
    )

    spo2 = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Oxygen saturation percentage",
    )

    weight = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Weight in kilograms",
    )

    height = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Height in centimeters",
    )

    blood_glucose = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Blood glucose",
    )

    pain_score = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Pain score from 0 to 10",
    )

    notes = models.TextField(
        blank=True,
        null=True,
    )

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_patient_vitals",
    )

    recorded_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "Patient Vital"
        verbose_name_plural = "Patient Vitals"
        ordering = ["-recorded_at"]

    def clean(self):

        errors = {}

        if self.spo2 is not None:
            if self.spo2 < 0 or self.spo2 > 100:
                errors["spo2"] = (
                    "SpO2 must be between 0 and 100."
                )

        if self.pain_score is not None:
            if self.pain_score > 10:
                errors["pain_score"] = (
                    "Pain score must be between 0 and 10."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Vitals - {self.opd_visit.visit_number}"


class OPDConsultation(models.Model):

    opd_visit = models.OneToOneField(
        OPDVisit,
        on_delete=models.CASCADE,
        related_name="consultation",
    )

    symptoms = models.TextField(
        blank=True,
        null=True,
    )

    clinical_findings = models.TextField(
        blank=True,
        null=True,
    )

    examination = models.TextField(
        blank=True,
        null=True,
    )

    diagnosis_summary = models.TextField(
        blank=True,
        null=True,
    )

    treatment_plan = models.TextField(
        blank=True,
        null=True,
    )

    doctor_notes = models.TextField(
        blank=True,
        null=True,
    )

    advice = models.TextField(
        blank=True,
        null=True,
    )

    consultation_start = models.DateTimeField(
        blank=True,
        null=True,
    )

    consultation_end = models.DateTimeField(
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "OPD Consultation"
        verbose_name_plural = "OPD Consultations"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):

        if not self.consultation_start:
            self.consultation_start = timezone.now()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Consultation - {self.opd_visit.visit_number}"


class OPDDiagnosis(models.Model):

    class DiagnosisType(models.TextChoices):
        PRIMARY = "PRIMARY", "Primary Diagnosis"
        SECONDARY = "SECONDARY", "Secondary Diagnosis"
        DIFFERENTIAL = "DIFFERENTIAL", "Differential Diagnosis"
        PROVISIONAL = "PROVISIONAL", "Provisional Diagnosis"

    opd_visit = models.ForeignKey(
        OPDVisit,
        on_delete=models.CASCADE,
        related_name="diagnoses",
    )

    diagnosis_type = models.CharField(
        max_length=20,
        choices=DiagnosisType.choices,
        default=DiagnosisType.PRIMARY,
    )

    diagnosis = models.CharField(
        max_length=255,
    )

    clinical_notes = models.TextField(
        blank=True,
        null=True,
    )

    diagnosed_by = models.ForeignKey(
        "doctors.Doctor",
        on_delete=models.PROTECT,
        related_name="opd_diagnoses",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "OPD Diagnosis"
        verbose_name_plural = "OPD Diagnoses"
        ordering = ["-created_at"]

    def clean(self):

        if self.opd_visit_id and self.diagnosed_by_id:

            if self.opd_visit.doctor_id != self.diagnosed_by_id:
                raise ValidationError(
                    {
                        "diagnosed_by": (
                            "Diagnosis doctor must match the OPD visit doctor."
                        )
                    }
                )

    def __str__(self):
        return (
            f"{self.opd_visit.visit_number} - "
            f"{self.diagnosis}"
        )


class OPDFollowUp(models.Model):

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    opd_visit = models.ForeignKey(
        OPDVisit,
        on_delete=models.CASCADE,
        related_name="follow_ups",
    )

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="opd_followups",
    )

    doctor = models.ForeignKey(
        "doctors.Doctor",
        on_delete=models.PROTECT,
        related_name="opd_followups",
    )

    followup_date = models.DateField(
        db_index=True,
    )

    instructions = models.TextField(
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "OPD Follow-up"
        verbose_name_plural = "OPD Follow-ups"
        ordering = ["followup_date"]

        indexes = [
            models.Index(
                fields=[
                    "followup_date",
                    "status",
                ]
            ),
            models.Index(
                fields=[
                    "patient",
                    "followup_date",
                ]
            ),
        ]

    def clean(self):

        errors = {}

        if self.opd_visit_id:

            if self.patient_id != self.opd_visit.patient_id:
                errors["patient"] = (
                    "Patient must match the OPD visit patient."
                )

            if self.doctor_id != self.opd_visit.doctor_id:
                errors["doctor"] = (
                    "Doctor must match the OPD visit doctor."
                )

        if self.followup_date:

            if self.followup_date < timezone.localdate():

                if self.status != self.Status.CANCELLED:
                    errors["followup_date"] = (
                        "Follow-up date cannot be in the past."
                    )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.patient.full_name} - "
            f"{self.followup_date}"
        )