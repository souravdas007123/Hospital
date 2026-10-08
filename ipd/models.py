from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class IPDAdmission(models.Model):
    """
    Main IPD admission record.

    One patient can have multiple historical admissions,
    but only one active admission at a time.
    """

    class AdmissionType(models.TextChoices):
        EMERGENCY = "EMERGENCY", "Emergency"
        OPD = "OPD", "OPD Referral"
        ELECTIVE = "ELECTIVE", "Elective"
        TRANSFER = "TRANSFER", "Transfer"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        ADMITTED = "ADMITTED", "Admitted"
        ON_HOLD = "ON_HOLD", "On Hold"
        DISCHARGED = "DISCHARGED", "Discharged"
        CANCELLED = "CANCELLED", "Cancelled"

    admission_number = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
    )

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="ipd_admissions",
    )

    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ipd_admissions",
        limit_choices_to={
            "role": "DOCTOR",
        },
    )

    department = models.ForeignKey(
        "hospitals.Department",
        on_delete=models.PROTECT,
        related_name="ipd_admissions",
    )

    ward = models.ForeignKey(
        "hospitals.Ward",
        on_delete=models.PROTECT,
        related_name="ipd_admissions",
    )

    room = models.ForeignKey(
        "hospitals.Room",
        on_delete=models.PROTECT,
        related_name="ipd_admissions",
    )

    bed = models.ForeignKey(
        "hospitals.Bed",
        on_delete=models.PROTECT,
        related_name="ipd_admissions",
    )

    admission_type = models.CharField(
        max_length=20,
        choices=AdmissionType.choices,
        default=AdmissionType.OPD,
    )

    admission_date = models.DateTimeField(
        default=timezone.now,
    )

    reason_for_admission = models.TextField(
        blank=True,
    )

    provisional_diagnosis = models.TextField(
        blank=True,
    )

    notes = models.TextField(
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ADMITTED,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_ipd_admissions",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = [
            "-admission_date",
            "-id",
        ]

    def __str__(self):
        return f"{self.admission_number} - {self.patient}"

    def clean(self):
        """
        Validate patient, doctor, department, ward, room and bed
        relationships.
        """

        errors = {}

        # ---------------------------------------------------------
        # Doctor validation
        # ---------------------------------------------------------

        if self.doctor_id:

            if getattr(self.doctor, "role", None) != "DOCTOR":
                errors["doctor"] = (
                    "Selected user must have Doctor role."
                )

        # ---------------------------------------------------------
        # Department / Ward validation
        # ---------------------------------------------------------

        if self.department_id and self.ward_id:

            if (
                hasattr(self.ward, "department_id")
                and self.ward.department_id
                and self.ward.department_id != self.department_id
            ):
                errors["ward"] = (
                    "Selected ward does not belong to the selected department."
                )

        # ---------------------------------------------------------
        # Ward / Room validation
        # ---------------------------------------------------------

        if self.ward_id and self.room_id:

            if (
                hasattr(self.room, "ward_id")
                and self.room.ward_id
                and self.room.ward_id != self.ward_id
            ):
                errors["room"] = (
                    "Selected room does not belong to the selected ward."
                )

        # ---------------------------------------------------------
        # Room / Bed validation
        # ---------------------------------------------------------

        if self.room_id and self.bed_id:

            if (
                hasattr(self.bed, "room_id")
                and self.bed.room_id
                and self.bed.room_id != self.room_id
            ):
                errors["bed"] = (
                    "Selected bed does not belong to the selected room."
                )

        # ---------------------------------------------------------
        # Bed status validation
        # ---------------------------------------------------------

        if self.bed_id:

            bed_status = getattr(
                self.bed,
                "status",
                None,
            )

            if (
                self.status in [
                    self.Status.ADMITTED,
                    self.Status.ON_HOLD,
                ]
                and bed_status
                and bed_status != "AVAILABLE"
            ):
                errors["bed"] = (
                    "Selected bed is not available."
                )

        # ---------------------------------------------------------
        # One active admission per patient
        # ---------------------------------------------------------

        if self.patient_id:

            active_admission = (
                IPDAdmission.objects
                .filter(
                    patient=self.patient,
                    status__in=[
                        self.Status.ADMITTED,
                        self.Status.ON_HOLD,
                    ],
                )
                .exclude(pk=self.pk)
                .exists()
            )

            if active_admission:
                errors["patient"] = (
                    "This patient already has an active IPD admission."
                )

        # ---------------------------------------------------------
        # One active admission per bed
        # ---------------------------------------------------------

        if self.bed_id:

            active_bed_admission = (
                IPDAdmission.objects
                .filter(
                    bed=self.bed,
                    status__in=[
                        self.Status.ADMITTED,
                        self.Status.ON_HOLD,
                    ],
                )
                .exclude(pk=self.pk)
                .exists()
            )

            if active_bed_admission:
                errors["bed"] = (
                    "This bed is already allocated to another active admission."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):

        if not self.admission_number:

            today = timezone.localdate()

            prefix = f"ADM-{today:%Y%m%d}-"

            last_admission = (
                IPDAdmission.objects
                .filter(
                    admission_number__startswith=prefix
                )
                .order_by("-id")
                .first()
            )

            if last_admission:
                try:
                    last_number = int(
                        last_admission.admission_number.split("-")[-1]
                    )
                except (ValueError, IndexError):
                    last_number = 0
            else:
                last_number = 0

            self.admission_number = (
                f"{prefix}{last_number + 1:04d}"
            )

        self.full_clean()

        super().save(*args, **kwargs)

        # ---------------------------------------------------------
        # Automatically occupy the bed
        # ---------------------------------------------------------

        if self.status in [
            self.Status.ADMITTED,
            self.Status.ON_HOLD,
        ]:
            self._set_bed_occupied()

        elif self.status in [
            self.Status.DISCHARGED,
            self.Status.CANCELLED,
        ]:
            self._set_bed_available()

    def _set_bed_occupied(self):

        if not self.bed_id:
            return

        bed = self.bed

        if hasattr(bed, "status"):

            bed.status = "OCCUPIED"

            bed.save(
                update_fields=[
                    "status",
                ]
            )

    def _set_bed_available(self):

        if not self.bed_id:
            return

        bed = self.bed

        if hasattr(bed, "status"):

            bed.status = "AVAILABLE"

            bed.save(
                update_fields=[
                    "status",
                ]
            )

class IPDBedTransfer(models.Model):
    """
    Stores complete history of patient bed transfers.
    """

    admission = models.ForeignKey(
        IPDAdmission,
        on_delete=models.PROTECT,
        related_name="bed_transfers",
    )

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="ipd_bed_transfers",
    )

    from_ward = models.ForeignKey(
        "hospitals.Ward",
        on_delete=models.PROTECT,
        related_name="ipd_transfers_from_ward",
        null=True,
        blank=True,
    )

    from_room = models.ForeignKey(
        "hospitals.Room",
        on_delete=models.PROTECT,
        related_name="ipd_transfers_from_room",
        null=True,
        blank=True,
    )

    from_bed = models.ForeignKey(
        "hospitals.Bed",
        on_delete=models.PROTECT,
        related_name="ipd_transfers_from_bed",
        null=True,
        blank=True,
    )

    to_ward = models.ForeignKey(
        "hospitals.Ward",
        on_delete=models.PROTECT,
        related_name="ipd_transfers_to_ward",
    )

    to_room = models.ForeignKey(
        "hospitals.Room",
        on_delete=models.PROTECT,
        related_name="ipd_transfers_to_room",
    )

    to_bed = models.ForeignKey(
        "hospitals.Bed",
        on_delete=models.PROTECT,
        related_name="ipd_transfers_to_bed",
    )

    transfer_date = models.DateTimeField(
        default=timezone.now,
    )

    reason = models.TextField(
        blank=True,
    )

    notes = models.TextField(
        blank=True,
    )

    transferred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="performed_ipd_bed_transfers",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = (
            "-transfer_date",
            "-id",
        )

    def __str__(self):
        return (
            f"{self.patient} - "
            f"{self.from_bed or 'Initial'} → "
            f"{self.to_bed}"
        )

    def clean(self):
        errors = {}

        # ---------------------------------------------------------
        # Admission validation
        # ---------------------------------------------------------

        if self.admission_id:

            if self.admission.status not in [
                IPDAdmission.Status.ADMITTED,
                IPDAdmission.Status.ON_HOLD,
            ]:
                errors["admission"] = (
                    "Only an active IPD admission can be transferred."
                )

            if (
                self.patient_id
                and self.admission.patient_id != self.patient_id
            ):
                errors["patient"] = (
                    "Patient does not match the selected admission."
                )

        # ---------------------------------------------------------
        # Destination ward / room / bed validation
        # ---------------------------------------------------------

        if self.to_ward_id and self.to_room_id:

            if (
                hasattr(self.to_room, "ward_id")
                and self.to_room.ward_id
                and self.to_room.ward_id != self.to_ward_id
            ):
                errors["to_room"] = (
                    "Selected room does not belong to selected ward."
                )

        if self.to_room_id and self.to_bed_id:

            if (
                hasattr(self.to_bed, "room_id")
                and self.to_bed.room_id
                and self.to_bed.room_id != self.to_room_id
            ):
                errors["to_bed"] = (
                    "Selected bed does not belong to selected room."
                )

        # ---------------------------------------------------------
        # Destination bed must be available
        # ---------------------------------------------------------

        if self.to_bed_id:

            bed_status = getattr(
                self.to_bed,
                "status",
                None,
            )

            if (
                bed_status
                and bed_status != "AVAILABLE"
            ):
                errors["to_bed"] = (
                    "Destination bed is not available."
                )

            active_transfer_admission = (
                IPDAdmission.objects
                .filter(
                    bed=self.to_bed,
                    status__in=[
                        IPDAdmission.Status.ADMITTED,
                        IPDAdmission.Status.ON_HOLD,
                    ],
                )
                .exclude(
                    pk=self.admission_id
                )
                .exists()
            )

            if active_transfer_admission:
                errors["to_bed"] = (
                    "Destination bed is already allocated."
                )

        # ---------------------------------------------------------
        # Destination cannot be same as current bed
        # ---------------------------------------------------------

        if (
            self.admission_id
            and self.to_bed_id
            and self.admission.bed_id == self.to_bed_id
        ):
            errors["to_bed"] = (
                "Destination bed must be different from current bed."
            )

        if errors:
            raise ValidationError(errors)  


class IPDDoctorAssignment(models.Model):
    """
    Stores doctors assigned to an IPD admission.
    """

    class DoctorRole(models.TextChoices):
        PRIMARY = "PRIMARY", "Primary / Attending Doctor"
        CONSULTANT = "CONSULTANT", "Consulting Doctor"

    admission = models.ForeignKey(
        IPDAdmission,
        on_delete=models.PROTECT,
        related_name="doctor_assignments",
    )

    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ipd_doctor_assignments",
        limit_choices_to={
            "role": "DOCTOR",
        },
    )

    role = models.CharField(
        max_length=20,
        choices=DoctorRole.choices,
        default=DoctorRole.CONSULTANT,
    )

    assigned_date = models.DateTimeField(
        default=timezone.now,
    )

    end_date = models.DateTimeField(
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    reason = models.TextField(
        blank=True,
    )

    notes = models.TextField(
        blank=True,
    )

    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_ipd_doctors",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = (
            "-assigned_date",
            "-id",
        )

    def __str__(self):
        return (
            f"{self.admission.admission_number} - "
            f"{self.doctor} - "
            f"{self.get_role_display()}"
        )

    def clean(self):

        errors = {}

        # ---------------------------------------------------------
        # Doctor must be a doctor
        # ---------------------------------------------------------

        if self.doctor_id:

            if getattr(self.doctor, "role", None) != "DOCTOR":
                errors["doctor"] = (
                    "Selected user must have Doctor role."
                )

        # ---------------------------------------------------------
        # Admission must be active
        # ---------------------------------------------------------

        if self.admission_id:

            if self.is_active:

                if self.admission.status not in [
                    IPDAdmission.Status.ADMITTED,
                    IPDAdmission.Status.ON_HOLD,
                ]:
                    errors["admission"] = (
                        "Doctor can only be actively assigned "
                        "to an active IPD admission."
                    )

        # ---------------------------------------------------------
        # End date validation
        # ---------------------------------------------------------

        if self.end_date:

            if self.end_date < self.assigned_date:
                errors["end_date"] = (
                    "End date cannot be before assigned date."
                )

        # ---------------------------------------------------------
        # Only one active primary doctor
        # ---------------------------------------------------------

        if (
            self.is_active
            and self.role == self.DoctorRole.PRIMARY
            and self.admission_id
        ):

            existing_primary = (
                IPDDoctorAssignment.objects
                .filter(
                    admission=self.admission,
                    role=self.DoctorRole.PRIMARY,
                    is_active=True,
                )
                .exclude(
                    pk=self.pk
                )
                .exists()
            )

            if existing_primary:
                errors["role"] = (
                    "This admission already has an active "
                    "primary doctor."
                )

        if errors:
            raise ValidationError(errors)


class IPDDoctorNote(models.Model):
    """
    Clinical notes written by doctors during IPD stay.
    """

    admission = models.ForeignKey(
        IPDAdmission,
        on_delete=models.PROTECT,
        related_name="doctor_notes",
    )

    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ipd_doctor_notes",
        limit_choices_to={
            "role": "DOCTOR",
        },
    )

    note_date = models.DateTimeField(
        default=timezone.now,
    )

    note_type = models.CharField(
        max_length=50,
        default="Progress Note",
    )

    clinical_note = models.TextField()

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = (
            "-note_date",
            "-id",
        )

    def __str__(self):
        return (
            f"{self.admission.admission_number} - "
            f"{self.doctor} - "
            f"{self.note_date:%d-%m-%Y %H:%M}"
        )

    def clean(self):

        if self.doctor_id:

            if getattr(self.doctor, "role", None) != "DOCTOR":
                raise ValidationError(
                    {
                        "doctor": (
                            "Selected user must have Doctor role."
                        )
                    }
                )

        if self.admission_id:

            assigned = (
                IPDDoctorAssignment.objects
                .filter(
                    admission=self.admission,
                    doctor=self.doctor,
                    is_active=True,
                )
                .exists()
            )

            if not assigned:
                raise ValidationError(
                    {
                        "doctor": (
                            "Doctor must be actively assigned "
                            "to this IPD admission."
                        )
                    }
                )                  