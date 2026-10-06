from django.db import models


class Hospital(models.Model):
    name = models.CharField(
        max_length=255
    )

    code = models.CharField(
        max_length=50,
        unique=True
    )

    registration_number = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True
    )

    logo = models.ImageField(
        upload_to="hospitals/logos/",
        blank=True,
        null=True
    )

    email = models.EmailField(
        blank=True,
        null=True
    )

    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True
    )

    emergency_phone = models.CharField(
        max_length=20,
        blank=True,
        null=True
    )

    website = models.URLField(
        blank=True,
        null=True
    )

    address_line_1 = models.CharField(
        max_length=255
    )

    address_line_2 = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    city = models.CharField(
        max_length=100
    )

    state = models.CharField(
        max_length=100
    )

    country = models.CharField(
        max_length=100,
        default="India"
    )

    postal_code = models.CharField(
        max_length=20
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Hospital"
        verbose_name_plural = "Hospitals"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Department(models.Model):

    hospital = models.ForeignKey(
        Hospital,
        on_delete=models.CASCADE,
        related_name="departments"
    )

    name = models.CharField(
        max_length=150
    )

    code = models.CharField(
        max_length=50
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True
    )

    email = models.EmailField(
        blank=True,
        null=True
    )

    head = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="headed_departments"
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Department"
        verbose_name_plural = "Departments"
        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["hospital", "code"],
                name="unique_department_code_per_hospital"
            )
        ]

    def __str__(self):
        return f"{self.name} - {self.hospital.name}"


class Building(models.Model):

    hospital = models.ForeignKey(
        Hospital,
        on_delete=models.CASCADE,
        related_name="buildings"
    )

    name = models.CharField(
        max_length=150
    )

    code = models.CharField(
        max_length=50
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    is_active = models.BooleanField(
        default=True
    )

    class Meta:
        verbose_name = "Building"
        verbose_name_plural = "Buildings"
        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["hospital", "code"],
                name="unique_building_code_per_hospital"
            )
        ]

    def __str__(self):
        return f"{self.name} - {self.hospital.name}"


class Floor(models.Model):

    building = models.ForeignKey(
        Building,
        on_delete=models.CASCADE,
        related_name="floors"
    )

    name = models.CharField(
        max_length=100
    )

    number = models.IntegerField()

    description = models.TextField(
        blank=True,
        null=True
    )

    is_active = models.BooleanField(
        default=True
    )

    class Meta:
        verbose_name = "Floor"
        verbose_name_plural = "Floors"
        ordering = ["building", "number"]

        constraints = [
            models.UniqueConstraint(
                fields=["building", "number"],
                name="unique_floor_per_building"
            )
        ]

    def __str__(self):
        return f"{self.building.name} - {self.name}"


class Ward(models.Model):

    class WardType(models.TextChoices):
        GENERAL = "GENERAL", "General Ward"
        ICU = "ICU", "ICU"
        NICU = "NICU", "NICU"
        PICU = "PICU", "PICU"
        CCU = "CCU", "CCU"
        PRIVATE = "PRIVATE", "Private Ward"
        SEMI_PRIVATE = "SEMI_PRIVATE", "Semi Private"
        EMERGENCY = "EMERGENCY", "Emergency"
        MATERNITY = "MATERNITY", "Maternity"
        PEDIATRIC = "PEDIATRIC", "Pediatric"
        ISOLATION = "ISOLATION", "Isolation"

    floor = models.ForeignKey(
        Floor,
        on_delete=models.CASCADE,
        related_name="wards"
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="wards"
    )

    name = models.CharField(
        max_length=150
    )

    code = models.CharField(
        max_length=50
    )

    ward_type = models.CharField(
        max_length=30,
        choices=WardType.choices,
        default=WardType.GENERAL
    )

    capacity = models.PositiveIntegerField(
        default=0
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    is_active = models.BooleanField(
        default=True
    )

    class Meta:
        verbose_name = "Ward"
        verbose_name_plural = "Wards"
        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["floor", "code"],
                name="unique_ward_code_per_floor"
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Room(models.Model):

    class RoomType(models.TextChoices):
        GENERAL = "GENERAL", "General"
        PRIVATE = "PRIVATE", "Private"
        SEMI_PRIVATE = "SEMI_PRIVATE", "Semi Private"
        ICU = "ICU", "ICU"
        OPERATION = "OPERATION", "Operation Theatre"
        CONSULTATION = "CONSULTATION", "Consultation"
        PROCEDURE = "PROCEDURE", "Procedure Room"

    ward = models.ForeignKey(
        Ward,
        on_delete=models.CASCADE,
        related_name="rooms"
    )

    room_number = models.CharField(
        max_length=50
    )

    room_type = models.CharField(
        max_length=30,
        choices=RoomType.choices,
        default=RoomType.GENERAL
    )

    floor_number = models.IntegerField(
        default=0
    )

    capacity = models.PositiveIntegerField(
        default=1
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    is_active = models.BooleanField(
        default=True
    )

    class Meta:
        verbose_name = "Room"
        verbose_name_plural = "Rooms"
        ordering = ["room_number"]

        constraints = [
            models.UniqueConstraint(
                fields=["ward", "room_number"],
                name="unique_room_per_ward"
            )
        ]

    def __str__(self):
        return f"Room {self.room_number} - {self.ward.name}"


class Bed(models.Model):

    class BedType(models.TextChoices):
        GENERAL = "GENERAL", "General"
        ICU = "ICU", "ICU"
        PRIVATE = "PRIVATE", "Private"
        SEMI_PRIVATE = "SEMI_PRIVATE", "Semi Private"
        EMERGENCY = "EMERGENCY", "Emergency"
        PEDIATRIC = "PEDIATRIC", "Pediatric"
        MATERNITY = "MATERNITY", "Maternity"

    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        OCCUPIED = "OCCUPIED", "Occupied"
        RESERVED = "RESERVED", "Reserved"
        CLEANING = "CLEANING", "Cleaning"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        BLOCKED = "BLOCKED", "Blocked"

    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name="beds"
    )

    bed_number = models.CharField(
        max_length=50
    )

    bed_type = models.CharField(
        max_length=30,
        choices=BedType.choices,
        default=BedType.GENERAL
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.AVAILABLE
    )

    daily_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Bed"
        verbose_name_plural = "Beds"
        ordering = ["bed_number"]

        constraints = [
            models.UniqueConstraint(
                fields=["room", "bed_number"],
                name="unique_bed_per_room"
            )
        ]

    def __str__(self):
        return f"Bed {self.bed_number} - {self.room.room_number}"