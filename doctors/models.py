from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Doctor(models.Model):

    class Gender(models.TextChoices):
        MALE = "MALE", "Male"
        FEMALE = "FEMALE", "Female"
        OTHER = "OTHER", "Other"

    # ---------------------------------------------------------
    # DOCTOR ACCOUNT
    # ---------------------------------------------------------

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="doctor_profile",
    )

    doctor_id = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
        db_index=True,
    )

    # ---------------------------------------------------------
    # PROFESSIONAL INFORMATION
    # ---------------------------------------------------------

    department = models.ForeignKey(
        "hospitals.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="doctors",
    )

    specialization = models.CharField(
        max_length=150,
    )

    sub_specialization = models.CharField(
        max_length=150,
        blank=True,
        null=True,
    )

    qualification = models.CharField(
        max_length=255,
    )

    medical_registration_number = models.CharField(
        max_length=100,
        unique=True,
    )

    medical_registration_council = models.CharField(
        max_length=150,
        blank=True,
        null=True,
    )

    experience_years = models.PositiveIntegerField(
        default=0,
    )

    # ---------------------------------------------------------
    # PERSONAL INFORMATION
    # ---------------------------------------------------------

    gender = models.CharField(
        max_length=20,
        choices=Gender.choices,
        blank=True,
        null=True,
    )

    date_of_birth = models.DateField(
        blank=True,
        null=True,
    )

    bio = models.TextField(
        blank=True,
        null=True,
    )

    profile_photo = models.ImageField(
        upload_to="doctors/photos/",
        blank=True,
        null=True,
    )

    # ---------------------------------------------------------
    # CONTACT
    # ---------------------------------------------------------

    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
    )

    email = models.EmailField(
        blank=True,
        null=True,
    )

    # ---------------------------------------------------------
    # CONSULTATION
    # ---------------------------------------------------------

    consultation_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[
            MinValueValidator(0)
        ],
    )

    followup_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[
            MinValueValidator(0)
        ],
    )

    emergency_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[
            MinValueValidator(0)
        ],
    )

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    is_available = models.BooleanField(
        default=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    # ---------------------------------------------------------
    # SYSTEM INFORMATION
    # ---------------------------------------------------------

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    # ---------------------------------------------------------
    # SAVE
    # ---------------------------------------------------------

    def save(self, *args, **kwargs):

        if not self.doctor_id:
            last_doctor = (
                Doctor.objects
                .order_by("-id")
                .first()
            )

            if last_doctor and last_doctor.doctor_id:
                try:
                    last_number = int(
                        last_doctor.doctor_id.replace(
                            "DOC-",
                            ""
                        )
                    )
                except ValueError:
                    last_number = 0
            else:
                last_number = 0

            self.doctor_id = f"DOC-{last_number + 1:05d}"

        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Doctor"
        verbose_name_plural = "Doctors"
        ordering = ["user__first_name", "user__last_name"]

    def __str__(self):

        return (
            f"{self.doctor_id} - "
            f"Dr. {self.user.get_full_name()}"
        )


class DoctorAvailability(models.Model):

    class WeekDay(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="availabilities",
    )

    day_of_week = models.PositiveSmallIntegerField(
        choices=WeekDay.choices,
    )

    start_time = models.TimeField()

    end_time = models.TimeField()

    consultation_duration = models.PositiveIntegerField(
        default=15,
        help_text="Duration of one consultation slot in minutes.",
    )

    max_patients = models.PositiveIntegerField(
        default=20,
    )

    is_available = models.BooleanField(
        default=True,
    )

    class Meta:
        verbose_name = "Doctor Availability"
        verbose_name_plural = "Doctor Availability"
        ordering = [
            "doctor",
            "day_of_week",
            "start_time",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "doctor",
                    "day_of_week",
                    "start_time",
                ],
                name="unique_doctor_schedule",
            )
        ]

    def __str__(self):

        return (
            f"{self.doctor} - "
            f"{self.get_day_of_week_display()} "
            f"{self.start_time} - {self.end_time}"
        )    

class DoctorSchedule(models.Model):

    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="opd_schedules",
    )

    department = models.ForeignKey(
        "hospitals.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="doctor_schedules",
    )

    schedule_name = models.CharField(
        max_length=150,
    )

    day_of_week = models.PositiveSmallIntegerField(
        choices=DoctorAvailability.WeekDay.choices,
    )

    start_time = models.TimeField()

    end_time = models.TimeField()

    room_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    max_patients = models.PositiveIntegerField(
        default=20,
    )

    consultation_duration = models.PositiveIntegerField(
        default=15,
        help_text="Duration of each appointment slot in minutes.",
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "Doctor OPD Schedule"
        verbose_name_plural = "Doctor OPD Schedules"
        ordering = [
            "doctor",
            "day_of_week",
            "start_time",
        ]

    def __str__(self):

        return (
            f"{self.schedule_name} - "
            f"{self.doctor}"
        )    