
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from hospitals.models import Bed, Department, Room, Ward
from patients.models import Patient


class IPDAdmission(models.Model):
    class Status(models.TextChoices):
        ADMITTED = "ADMITTED", "Admitted"
        ON_HOLD = "ON_HOLD", "On Hold"
        DISCHARGED = "DISCHARGED", "Discharged"
        CANCELLED = "CANCELLED", "Cancelled"

    class AdmissionType(models.TextChoices):
        EMERGENCY = "EMERGENCY", "Emergency"
        PLANNED = "PLANNED", "Planned"
        REFERRAL = "REFERRAL", "Referral"

    class DischargeDisposition(models.TextChoices):
        HOME = "HOME", "Discharged Home"
        TRANSFER = "TRANSFER", "Transferred to Another Facility"
        LAMA = "LAMA", "Left Against Medical Advice"
        OTHER = "OTHER", "Other"

    admission_number = models.CharField(
        max_length=30,
        unique=True,
        blank=True,
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="ipd_admissions",
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="primary_ipd_admissions",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="ipd_admissions",
    )
    ward = models.ForeignKey(
        Ward,
        on_delete=models.PROTECT,
        related_name="ipd_admissions",
    )
    room = models.ForeignKey(
        Room,
        on_delete=models.PROTECT,
        related_name="ipd_admissions",
    )
    bed = models.ForeignKey(
        Bed,
        on_delete=models.PROTECT,
        related_name="ipd_admissions",
    )

    admission_type = models.CharField(
        max_length=20,
        choices=AdmissionType.choices,
        default=AdmissionType.PLANNED,
    )
    admission_date = models.DateTimeField(default=timezone.now)
    reason_for_admission = models.TextField()
    provisional_diagnosis = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ADMITTED,
    )

    # Discharge information
    discharge_date = models.DateTimeField(
        null=True,
        blank=True,
    )
    final_diagnosis = models.TextField(blank=True)
    treatment_summary = models.TextField(blank=True)
    discharge_instructions = models.TextField(blank=True)
    discharge_disposition = models.CharField(
        max_length=20,
        choices=DischargeDisposition.choices,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_ipd_admissions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()

        if self.doctor_id and getattr(self.doctor, "role", None) != "DOCTOR":
            raise ValidationError({
                "doctor": "Selected user must have the Doctor role."
            })

        if self.room_id and self.ward_id:
            if self.room.ward_id != self.ward_id:
                raise ValidationError({
                    "room": "Selected room does not belong to this ward."
                })

        if self.bed_id and self.room_id:
            if self.bed.room_id != self.room_id:
                raise ValidationError({
                    "bed": "Selected bed does not belong to this room."
                })

        active_statuses = [self.Status.ADMITTED, self.Status.ON_HOLD]

        if self.status in active_statuses and self.bed_id:
            if self.bed.status != "AVAILABLE" and (
                not self.pk or
                not IPDAdmission.objects.filter(
                    pk=self.pk,
                    bed=self.bed,
                    status__in=active_statuses,
                ).exists()
            ):
                raise ValidationError({
                    "bed": "Selected bed is not available."
                })

            duplicate_bed = IPDAdmission.objects.filter(
                bed=self.bed,
                status__in=active_statuses,
            )
            if self.pk:
                duplicate_bed = duplicate_bed.exclude(pk=self.pk)

            if duplicate_bed.exists():
                raise ValidationError({
                    "bed": "This bed is already assigned to another active admission."
                })

            duplicate_patient = IPDAdmission.objects.filter(
                patient=self.patient,
                status__in=active_statuses,
            )
            if self.pk:
                duplicate_patient = duplicate_patient.exclude(pk=self.pk)

            if duplicate_patient.exists():
                raise ValidationError({
                    "patient": "This patient already has an active IPD admission."
                })

        if self.status == self.Status.DISCHARGED:
            required_fields = {
                "final_diagnosis": self.final_diagnosis,
                "treatment_summary": self.treatment_summary,
                "discharge_instructions": self.discharge_instructions,
                "discharge_disposition": self.discharge_disposition,
                "discharge_date": self.discharge_date,
            }
            missing = [
                field for field, value in required_fields.items()
                if not value
            ]
            if missing:
                raise ValidationError({
                    field: "This field is required for discharge."
                    for field in missing
                })

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if not self.admission_number:
                today = timezone.localdate()
                prefix = f"ADM-{today:%Y%m%d}-"
                last_admission = (
                    IPDAdmission.objects
                    .filter(admission_number__startswith=prefix)
                    .order_by("-admission_number")
                    .first()
                )
                next_number = 1
                if last_admission:
                    try:
                        next_number = (
                            int(last_admission.admission_number.split("-")[-1])
                            + 1
                        )
                    except (ValueError, IndexError):
                        next_number = IPDAdmission.objects.filter(
                            admission_number__startswith=prefix
                        ).count() + 1

                self.admission_number = f"{prefix}{next_number:04d}"

            self.full_clean()
            super().save(*args, **kwargs)

            if self.status in (self.Status.ADMITTED, self.Status.ON_HOLD):
                if self.bed.status != "OCCUPIED":
                    self.bed.status = "OCCUPIED"
                    self.bed.save(update_fields=["status"])

            elif self.status in (self.Status.DISCHARGED, self.Status.CANCELLED):
                other_active = IPDAdmission.objects.filter(
                    bed=self.bed,
                    status__in=[self.Status.ADMITTED, self.Status.ON_HOLD],
                ).exclude(pk=self.pk).exists()

                if not other_active and self.bed.status != "AVAILABLE":
                    self.bed.status = "AVAILABLE"
                    self.bed.save(update_fields=["status"])

    def __str__(self):
        return f"{self.admission_number} - {self.patient}"


class IPDBedTransfer(models.Model):
    admission = models.ForeignKey(
        IPDAdmission,
        on_delete=models.PROTECT,
        related_name="bed_transfers",
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="ipd_bed_transfers",
    )
    from_ward = models.ForeignKey(
        Ward,
        on_delete=models.PROTECT,
        related_name="ipd_transfers_from",
    )
    from_room = models.ForeignKey(
        Room,
        on_delete=models.PROTECT,
        related_name="ipd_transfers_from",
    )
    from_bed = models.ForeignKey(
        Bed,
        on_delete=models.PROTECT,
        related_name="ipd_transfers_from",
    )
    to_ward = models.ForeignKey(
        Ward,
        on_delete=models.PROTECT,
        related_name="ipd_transfers_to",
    )
    to_room = models.ForeignKey(
        Room,
        on_delete=models.PROTECT,
        related_name="ipd_transfers_to",
    )
    to_bed = models.ForeignKey(
        Bed,
        on_delete=models.PROTECT,
        related_name="ipd_transfers_to",
    )
    transfer_date = models.DateTimeField(default=timezone.now)
    reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    transferred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ipd_bed_transfers",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()

        if self.admission_id and self.patient_id:
            if self.admission.patient_id != self.patient_id:
                raise ValidationError(
                    "Transfer patient must match the admission patient."
                )

        if self.to_room_id and self.to_ward_id:
            if self.to_room.ward_id != self.to_ward_id:
                raise ValidationError("Destination room does not belong to the ward.")

        if self.to_bed_id and self.to_room_id:
            if self.to_bed.room_id != self.to_room_id:
                raise ValidationError("Destination bed does not belong to the room.")

        if self.to_bed_id and self.to_bed.status != "AVAILABLE":
            raise ValidationError("Destination bed must be available.")

    def __str__(self):
        return f"{self.admission} → {self.to_bed}"


class IPDDoctorAssignment(models.Model):
    class Role(models.TextChoices):
        PRIMARY = "PRIMARY", "Primary"
        CONSULTANT = "CONSULTANT", "Consultant"

    admission = models.ForeignKey(
        IPDAdmission,
        on_delete=models.PROTECT,
        related_name="doctor_assignments",
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ipd_doctor_assignments",
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    assigned_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ipd_doctor_assignments_made",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()

        if self.doctor_id and getattr(self.doctor, "role", None) != "DOCTOR":
            raise ValidationError({"doctor": "Selected user is not a doctor."})

        if self.is_active and self.role == self.Role.PRIMARY:
            duplicate = IPDDoctorAssignment.objects.filter(
                admission=self.admission,
                role=self.Role.PRIMARY,
                is_active=True,
            )
            if self.pk:
                duplicate = duplicate.exclude(pk=self.pk)
            if duplicate.exists():
                raise ValidationError(
                    "Only one active primary doctor is allowed per admission."
                )

    def __str__(self):
        return f"{self.admission} - {self.doctor}"


class IPDDoctorNote(models.Model):
    admission = models.ForeignKey(
        IPDAdmission,
        on_delete=models.PROTECT,
        related_name="doctor_notes",
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ipd_doctor_notes",
    )
    note_date = models.DateTimeField(default=timezone.now)
    note_type = models.CharField(max_length=50, default="Progress Note")
    clinical_note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()

        if self.doctor_id and getattr(self.doctor, "role", None) != "DOCTOR":
            raise ValidationError({"doctor": "Selected user is not a doctor."})

        if self.admission_id and self.doctor_id:
            assigned = IPDDoctorAssignment.objects.filter(
                admission=self.admission,
                doctor=self.doctor,
                is_active=True,
            ).exists()
            if not assigned:
                raise ValidationError(
                    "Doctor must be actively assigned to this admission."
                )

    def __str__(self):
        return f"{self.admission} - {self.note_type}"


class IPDNursingVital(models.Model):
    admission = models.ForeignKey(
        IPDAdmission,
        on_delete=models.PROTECT,
        related_name="nursing_vitals",
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="ipd_nursing_vitals",
    )
    recorded_at = models.DateTimeField(default=timezone.now)
    temperature = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    systolic_bp = models.PositiveSmallIntegerField(null=True, blank=True)
    diastolic_bp = models.PositiveSmallIntegerField(null=True, blank=True)
    pulse = models.PositiveSmallIntegerField(null=True, blank=True)
    respiratory_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    spo2 = models.PositiveSmallIntegerField(null=True, blank=True)
    weight = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    height = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    blood_glucose = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    pain_score = models.PositiveSmallIntegerField(null=True, blank=True)
    nursing_notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ipd_vitals_recorded",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()

        if self.admission_id and self.patient_id:
            if self.admission.patient_id != self.patient_id:
                raise ValidationError("Patient does not match admission.")

        if self.recorded_by_id and getattr(self.recorded_by, "role", None) not in (
            "NURSE", "ADMIN", "STAFF"
        ):
            raise ValidationError("User is not authorized to record vitals.")

        if self.spo2 is not None and not 0 <= self.spo2 <= 100:
            raise ValidationError({"spo2": "SpO2 must be between 0 and 100."})

        if self.pain_score is not None and not 0 <= self.pain_score <= 10:
            raise ValidationError({"pain_score": "Pain score must be between 0 and 10."})

    def __str__(self):
        return f"{self.patient} - {self.recorded_at}"


class IPDNursingNote(models.Model):
    class NoteType(models.TextChoices):
        OBSERVATION = "OBSERVATION", "Observation"
        HANDOVER = "HANDOVER", "Handover"
        OTHER = "OTHER", "Other"

    admission = models.ForeignKey(
        IPDAdmission,
        on_delete=models.PROTECT,
        related_name="nursing_notes",
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="ipd_nursing_notes",
    )
    note_type = models.CharField(
        max_length=20,
        choices=NoteType.choices,
        default=NoteType.OBSERVATION,
    )
    note_date = models.DateTimeField(default=timezone.now)
    notes = models.TextField()
    intake_ml = models.PositiveIntegerField(null=True, blank=True)
    output_ml = models.PositiveIntegerField(null=True, blank=True)
    nurse = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ipd_nursing_notes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()

        if self.admission_id and self.patient_id:
            if self.admission.patient_id != self.patient_id:
                raise ValidationError("Patient does not match admission.")

        if self.nurse_id and getattr(self.nurse, "role", None) not in (
            "NURSE", "ADMIN", "STAFF"
        ):
            raise ValidationError("User is not authorized to create nursing notes.")

        if not self.notes or not self.notes.strip():
            raise ValidationError({"notes": "Notes cannot be empty."})

    def __str__(self):
        return f"{self.patient} - {self.note_type}"


class IPDMedicationOrder(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    class Route(models.TextChoices):
        ORAL = "ORAL", "Oral"
        IV = "IV", "Intravenous"
        IM = "IM", "Intramuscular"
        TOPICAL = "TOPICAL", "Topical"
        OTHER = "OTHER", "Other"

    admission = models.ForeignKey(
        IPDAdmission,
        on_delete=models.PROTECT,
        related_name="medication_orders",
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="ipd_medication_orders",
    )
    medicine = models.ForeignKey(
        "pharmacy.Medicine",
        on_delete=models.PROTECT,
        related_name="ipd_medication_orders",
    )
    prescribed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ipd_medication_orders",
    )
    dose = models.CharField(max_length=100)
    route = models.CharField(max_length=20, choices=Route.choices, default=Route.ORAL)
    frequency = models.CharField(max_length=100)
    duration_days = models.PositiveIntegerField(default=1)
    quantity = models.PositiveIntegerField(default=1)
    start_date = models.DateField()
    end_date = models.DateField()
    instructions = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()

        if self.admission_id and self.patient_id:
            if self.admission.patient_id != self.patient_id:
                raise ValidationError("Patient does not match admission.")

        if self.prescribed_by_id and getattr(self.prescribed_by, "role", None) != "DOCTOR":
            raise ValidationError("Only doctors can prescribe medication.")

        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date cannot precede start date."})

    def __str__(self):
        return f"{self.patient} - {self.medicine}"


class IPDMedicationAdministration(models.Model):
    class Status(models.TextChoices):
        GIVEN = "GIVEN", "Given"
        MISSED = "MISSED", "Missed"
        REFUSED = "REFUSED", "Refused"
        HELD = "HELD", "Held"
        NOT_AVAILABLE = "NOT_AVAILABLE", "Not Available"

    medication_order = models.ForeignKey(
        IPDMedicationOrder,
        on_delete=models.PROTECT,
        related_name="administrations",
    )
    admission = models.ForeignKey(
        IPDAdmission,
        on_delete=models.PROTECT,
        related_name="medication_administrations",
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="ipd_medication_administrations",
    )
    medicine_batch = models.ForeignKey(
        "pharmacy.MedicineBatch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ipd_administrations",
    )
    scheduled_at = models.DateTimeField()
    administered_at = models.DateTimeField(null=True, blank=True)
    administered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ipd_medication_administrations",
    )
    quantity_given = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices)
    reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()

        if self.medication_order_id:
            if self.admission_id and self.medication_order.admission_id != self.admission_id:
                raise ValidationError("Medication order admission mismatch.")
            if self.patient_id and self.medication_order.patient_id != self.patient_id:
                raise ValidationError("Medication order patient mismatch.")

        if self.status == self.Status.GIVEN:
            if not self.administered_by_id:
                raise ValidationError({"administered_by": "Required when medication is given."})
            if not self.administered_at:
                raise ValidationError({"administered_at": "Required when medication is given."})
            if self.quantity_given <= 0:
                raise ValidationError({"quantity_given": "Quantity must be greater than zero."})
            if not self.medicine_batch_id:
                raise ValidationError({"medicine_batch": "Batch is required when medication is given."})

    def __str__(self):
        return f"{self.patient} - {self.status}"