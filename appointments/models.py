from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Appointment(models.Model):

    class AppointmentType(models.TextChoices):
        NEW = "NEW", "New Consultation"
        FOLLOW_UP = "FOLLOW_UP", "Follow-up"
        EMERGENCY = "EMERGENCY", "Emergency"
        PROCEDURE = "PROCEDURE", "Procedure"
        REVIEW = "REVIEW", "Review"

    class Status(models.TextChoices):
        BOOKED = "BOOKED", "Booked"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CHECKED_IN = "CHECKED_IN", "Checked In"
        IN_CONSULTATION = "IN_CONSULTATION", "In Consultation"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"
        NO_SHOW = "NO_SHOW", "No Show"

    class BookingSource(models.TextChoices):
        RECEPTION = "RECEPTION", "Reception"
        ONLINE = "ONLINE", "Online"
        PHONE = "PHONE", "Phone"
        WALK_IN = "WALK_IN", "Walk-in"
        REFERRAL = "REFERRAL", "Referral"

    appointment_number = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
        db_index=True,
    )

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="appointments",
    )

    doctor = models.ForeignKey(
        "doctors.Doctor",
        on_delete=models.PROTECT,
        related_name="appointments",
    )

    department = models.ForeignKey(
        "hospitals.Department",
        on_delete=models.PROTECT,
        related_name="appointments",
    )

    schedule = models.ForeignKey(
        "doctors.DoctorSchedule",
        on_delete=models.PROTECT,
        related_name="appointments",
        null=True,
        blank=True,
    )

    appointment_date = models.DateField(
        db_index=True,
    )

    start_time = models.TimeField()

    end_time = models.TimeField()

    token_number = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        db_index=True,
    )

    appointment_type = models.CharField(
        max_length=20,
        choices=AppointmentType.choices,
        default=AppointmentType.NEW,
    )

    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.BOOKED,
        db_index=True,
    )

    booking_source = models.CharField(
        max_length=20,
        choices=BookingSource.choices,
        default=BookingSource.RECEPTION,
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
        related_name="created_appointments",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    checked_in_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    completed_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    cancelled_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    cancellation_reason = models.TextField(
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = "Appointment"
        verbose_name_plural = "Appointments"
        ordering = [
            "appointment_date",
            "start_time",
            "token_number",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "doctor",
                    "appointment_date",
                    "start_time",
                ],
                name="unique_doctor_appointment_slot",
            ),
            models.UniqueConstraint(
                fields=[
                    "doctor",
                    "appointment_date",
                    "token_number",
                ],
                name="unique_doctor_daily_token",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "appointment_date",
                    "doctor",
                ]
            ),
            models.Index(
                fields=[
                    "appointment_date",
                    "department",
                ]
            ),
            models.Index(
                fields=[
                    "patient",
                    "appointment_date",
                ]
            ),
        ]

    def clean(self):
        errors = {}

        # -------------------------------------------------
        # Doctor must be active
        # -------------------------------------------------
        if self.doctor_id:
            if not self.doctor.is_active:
                errors["doctor"] = "Selected doctor is inactive."

            if not self.doctor.is_available:
                errors["doctor"] = "Selected doctor is currently unavailable."

        # -------------------------------------------------
        # Department validation
        # -------------------------------------------------
        if self.doctor_id and self.department_id:

            if self.doctor.department_id:
                if self.doctor.department_id != self.department_id:
                    errors["department"] = (
                        "Selected department does not match the doctor's department."
                    )

        # -------------------------------------------------
        # Schedule validation
        # -------------------------------------------------
        if self.schedule_id:

            if self.schedule.doctor_id != self.doctor_id:
                errors["schedule"] = (
                    "Selected schedule does not belong to the selected doctor."
                )

            if self.schedule.department_id:
                if self.schedule.department_id != self.department_id:
                    errors["schedule"] = (
                        "Selected schedule does not belong to the selected department."
                    )

            if not self.schedule.is_active:
                errors["schedule"] = "Selected doctor schedule is inactive."

            if self.appointment_date:

                weekday = self.appointment_date.weekday()

                if weekday != self.schedule.day_of_week:
                    errors["appointment_date"] = (
                        "Appointment date does not match the selected schedule day."
                    )

            if self.start_time and self.end_time:

                if self.start_time < self.schedule.start_time:
                    errors["start_time"] = (
                        "Appointment start time is before the doctor's schedule."
                    )

                if self.end_time > self.schedule.end_time:
                    errors["end_time"] = (
                        "Appointment end time is after the doctor's schedule."
                    )

        # -------------------------------------------------
        # Time validation
        # -------------------------------------------------
        if self.start_time and self.end_time:

            if self.start_time >= self.end_time:
                errors["end_time"] = (
                    "Appointment end time must be after start time."
                )

        # -------------------------------------------------
        # Date validation
        # -------------------------------------------------
        if self.appointment_date:

            if (
                self.appointment_date < timezone.localdate()
                and self.status
                not in [
                    self.Status.CANCELLED,
                    self.Status.NO_SHOW,
                ]
            ):
                errors["appointment_date"] = (
                    "Appointment date cannot be in the past."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):

        if not self.appointment_number:
            today = timezone.localdate()

            prefix = f"APT-{today.strftime('%Y%m%d')}-"

            last_appointment = (
                Appointment.objects
                .filter(appointment_number__startswith=prefix)
                .order_by("-id")
                .first()
            )

            if last_appointment:
                try:
                    last_number = int(
                        last_appointment.appointment_number.split("-")[-1]
                    )
                except (ValueError, IndexError):
                    last_number = 0
            else:
                last_number = 0

            self.appointment_number = (
                f"{prefix}{last_number + 1:04d}"
            )

        self.full_clean()

        # ---------------------------------------------
        # Automatically maintain timestamps
        # ---------------------------------------------

        if self.status == self.Status.CHECKED_IN:
            if not self.checked_in_at:
                self.checked_in_at = timezone.now()

        elif self.status == self.Status.COMPLETED:
            if not self.completed_at:
                self.completed_at = timezone.now()

        elif self.status == self.Status.CANCELLED:
            if not self.cancelled_at:
                self.cancelled_at = timezone.now()

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.appointment_number} | "
            f"{self.patient.full_name} | "
            f"Dr. {self.doctor.user.get_full_name()}"
        )
