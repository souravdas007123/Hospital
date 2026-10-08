from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class LabCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=30, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "01. Lab Category"
        verbose_name_plural = "01. Lab Categories"
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class SampleType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=30, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "02. Sample Type"
        verbose_name_plural = "02. Sample Types"
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class LabTest(models.Model):
    class ResultType(models.TextChoices):
        NUMERIC = "NUMERIC", "Numeric"
        TEXT = "TEXT", "Text"
        POSITIVE_NEGATIVE = "POSITIVE_NEGATIVE", "Positive / Negative"
        CHOICE = "CHOICE", "Choice"

    test_code = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
    )

    name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=100, blank=True)

    category = models.ForeignKey(
        LabCategory,
        on_delete=models.PROTECT,
        related_name="tests",
    )

    sample_type = models.ForeignKey(
        SampleType,
        on_delete=models.PROTECT,
        related_name="tests",
    )

    result_type = models.CharField(
        max_length=30,
        choices=ResultType.choices,
        default=ResultType.NUMERIC,
    )

    unit = models.CharField(
        max_length=50,
        blank=True,
        help_text="Example: mg/dL, g/dL, %, cells/µL",
    )

    specimen_volume = models.CharField(
        max_length=50,
        blank=True,
        help_text="Example: 2 mL",
    )

    methodology = models.CharField(
        max_length=200,
        blank=True,
        help_text="Example: CLIA, ELISA, ISE",
    )

    instructions = models.TextField(
        blank=True,
        help_text="Patient/sample preparation instructions.",
    )

    description = models.TextField(blank=True)

    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    turnaround_time_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Expected report completion time in minutes.",
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "03. Lab Test"
        verbose_name_plural = "03. Lab Tests"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.test_code:
            last_test = (
                LabTest.objects
                .filter(test_code__startswith="LAB-")
                .order_by("-id")
                .first()
            )

            sequence = 1

            if last_test:
                try:
                    sequence = int(last_test.test_code.split("-")[-1]) + 1
                except (ValueError, IndexError):
                    sequence = 1

            self.test_code = f"LAB-{sequence:05d}"

        super().save(*args, **kwargs)

    def clean(self):
        super().clean()

        if self.price < 0:
            raise ValidationError("Test price cannot be negative.")

        if self.turnaround_time_minutes <= 0:
            raise ValidationError(
                "Turnaround time must be greater than zero."
            )

    def __str__(self):
        return f"{self.test_code} - {self.name}"


class LabReferenceRange(models.Model):
    class Gender(models.TextChoices):
        ALL = "ALL", "All"
        MALE = "MALE", "Male"
        FEMALE = "FEMALE", "Female"

    test = models.ForeignKey(
        LabTest,
        on_delete=models.CASCADE,
        related_name="reference_ranges",
    )

    gender = models.CharField(
        max_length=10,
        choices=Gender.choices,
        default=Gender.ALL,
    )

    age_min = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    age_max = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )

    normal_min = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
    )

    normal_max = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
    )

    critical_low = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
    )

    critical_high = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
    )

    normal_text = models.CharField(
        max_length=255,
        blank=True,
        help_text="For text-based tests.",
    )

    interpretation = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "04. Reference Range"
        verbose_name_plural = "04. Reference Ranges"
        ordering = ["test", "age_min"]

    def clean(self):
        super().clean()

        if self.age_min < 0:
            raise ValidationError("Minimum age cannot be negative.")

        if self.age_max is not None and self.age_max < self.age_min:
            raise ValidationError(
                "Maximum age cannot be less than minimum age."
            )

        if (
            self.normal_min is not None
            and self.normal_max is not None
            and self.normal_max < self.normal_min
        ):
            raise ValidationError(
                "Normal maximum cannot be less than normal minimum."
            )

    def __str__(self):
        return f"{self.test.name} - {self.get_gender_display()}"


class LabPackage(models.Model):
    package_code = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
    )

    name = models.CharField(max_length=200)

    description = models.TextField(blank=True)

    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "05. Lab Package"
        verbose_name_plural = "05. Lab Packages"
        ordering = ["name"]

    @property
    def final_price(self):
        return self.price - self.discount

    def clean(self):
        super().clean()

        if self.price < 0:
            raise ValidationError("Package price cannot be negative.")

        if self.discount < 0:
            raise ValidationError("Package discount cannot be negative.")

        if self.discount > self.price:
            raise ValidationError(
                "Package discount cannot be greater than package price."
            )

    def save(self, *args, **kwargs):
        if not self.package_code:
            last_package = (
                LabPackage.objects
                .filter(package_code__startswith="PKG-")
                .order_by("-id")
                .first()
            )

            sequence = 1

            if last_package:
                try:
                    sequence = (
                        int(last_package.package_code.split("-")[-1]) + 1
                    )
                except (ValueError, IndexError):
                    sequence = 1

            self.package_code = f"PKG-{sequence:05d}"

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.package_code} - {self.name}"


class LabPackageItem(models.Model):
    package = models.ForeignKey(
        LabPackage,
        on_delete=models.CASCADE,
        related_name="items",
    )

    test = models.ForeignKey(
        LabTest,
        on_delete=models.PROTECT,
        related_name="package_items",
    )

    class Meta:
        verbose_name = "06. Lab Package Item"
        verbose_name_plural = "06. Lab Package Items"
        constraints = [
            models.UniqueConstraint(
                fields=["package", "test"],
                name="unique_lab_package_test",
            )
        ]

    def __str__(self):
        return f"{self.package.name} - {self.test.name}"


class LabOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ORDERED = "ORDERED", "Ordered"
        SAMPLE_PENDING = "SAMPLE_PENDING", "Sample Pending"
        SAMPLE_COLLECTED = "SAMPLE_COLLECTED", "Sample Collected"
        PROCESSING = "PROCESSING", "Processing"
        PARTIAL = "PARTIAL", "Partially Completed"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    order_number = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
    )

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="lab_orders",
    )

    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ordered_lab_orders",
        limit_choices_to={"role": "DOCTOR"},
    )

    opd_visit = models.ForeignKey(
        "opd.OPDVisit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lab_orders",
    )

    order_date = models.DateTimeField(default=timezone.now)

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    clinical_notes = models.TextField(blank=True)

    priority = models.BooleanField(
        default=False,
        help_text="Mark as urgent/stat laboratory order.",
    )

    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_lab_orders",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "07. Lab Order"
        verbose_name_plural = "07. Lab Orders"
        ordering = ["-order_date", "-id"]

    def save(self, *args, **kwargs):
        if not self.order_number:
            today = timezone.localdate()
            prefix = f"LABORD-{today.strftime('%Y%m%d')}-"

            last_order = (
                LabOrder.objects
                .filter(order_number__startswith=prefix)
                .order_by("-id")
                .first()
            )

            sequence = 1

            if last_order:
                try:
                    sequence = (
                        int(last_order.order_number.split("-")[-1]) + 1
                    )
                except (ValueError, IndexError):
                    sequence = 1

            self.order_number = f"{prefix}{sequence:04d}"

        super().save(*args, **kwargs)

    def calculate_total(self):
        return sum(
            item.total_amount
            for item in self.items.all()
        )

    def clean(self):
        super().clean()

        if self.opd_visit_id:
            if self.opd_visit.patient_id != self.patient_id:
                raise ValidationError(
                    "Selected OPD visit does not belong to this patient."
                )

    def __str__(self):
        return f"{self.order_number} - {self.patient}"


class LabOrderItem(models.Model):
    class ItemType(models.TextChoices):
        TEST = "TEST", "Test"
        PACKAGE = "PACKAGE", "Package"

    class Status(models.TextChoices):
        ORDERED = "ORDERED", "Ordered"
        SAMPLE_PENDING = "SAMPLE_PENDING", "Sample Pending"
        SAMPLE_COLLECTED = "SAMPLE_COLLECTED", "Sample Collected"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    order = models.ForeignKey(
        LabOrder,
        on_delete=models.CASCADE,
        related_name="items",
    )

    item_type = models.CharField(
        max_length=20,
        choices=ItemType.choices,
        default=ItemType.TEST,
    )

    test = models.ForeignKey(
        LabTest,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="order_items",
    )

    package = models.ForeignKey(
        LabPackage,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="order_items",
    )

    quantity = models.PositiveIntegerField(default=1)

    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.ORDERED,
    )

    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "08. Lab Order Item"
        verbose_name_plural = "08. Lab Order Items"

    @property
    def subtotal(self):
        return self.quantity * self.price

    @property
    def total_amount(self):
        return self.subtotal - self.discount

    def clean(self):
        super().clean()

        if self.quantity <= 0:
            raise ValidationError("Quantity must be greater than zero.")

        if self.price < 0:
            raise ValidationError("Price cannot be negative.")

        if self.discount < 0:
            raise ValidationError("Discount cannot be negative.")

        if self.discount > self.subtotal:
            raise ValidationError(
                "Discount cannot be greater than subtotal."
            )

        if self.item_type == self.ItemType.TEST:
            if not self.test_id:
                raise ValidationError(
                    "Test is required for a TEST item."
                )

            if self.package_id:
                raise ValidationError(
                    "Package must be empty for a TEST item."
                )

        elif self.item_type == self.ItemType.PACKAGE:
            if not self.package_id:
                raise ValidationError(
                    "Package is required for a PACKAGE item."
                )

            if self.test_id:
                raise ValidationError(
                    "Test must be empty for a PACKAGE item."
                )

    def save(self, *args, **kwargs):
        if self.item_type == self.ItemType.TEST and self.test_id:
            if not self.price:
                self.price = self.test.price

        if self.item_type == self.ItemType.PACKAGE and self.package_id:
            if not self.price:
                self.price = self.package.final_price

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        if self.test_id:
            return f"{self.order.order_number} - {self.test.name}"

        if self.package_id:
            return f"{self.order.order_number} - {self.package.name}"

        return self.order.order_number


class LabSample(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COLLECTED = "COLLECTED", "Collected"
        RECEIVED = "RECEIVED", "Received"
        REJECTED = "REJECTED", "Rejected"
        PROCESSED = "PROCESSED", "Processed"

    sample_number = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
    )

    order = models.ForeignKey(
        LabOrder,
        on_delete=models.PROTECT,
        related_name="samples",
    )

    order_item = models.ForeignKey(
        LabOrderItem,
        on_delete=models.PROTECT,
        related_name="samples",
    )

    sample_type = models.ForeignKey(
        SampleType,
        on_delete=models.PROTECT,
        related_name="samples",
    )

    collected_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    received_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    collected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="collected_lab_samples",
    )

    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_lab_samples",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    rejection_reason = models.TextField(blank=True)

    barcode = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
    )

    remarks = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "09. Lab Sample"
        verbose_name_plural = "09. Lab Samples"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.sample_number:
            today = timezone.localdate()
            prefix = f"SMP-{today.strftime('%Y%m%d')}-"

            last_sample = (
                LabSample.objects
                .filter(sample_number__startswith=prefix)
                .order_by("-id")
                .first()
            )

            sequence = 1

            if last_sample:
                try:
                    sequence = (
                        int(last_sample.sample_number.split("-")[-1]) + 1
                    )
                except (ValueError, IndexError):
                    sequence = 1

            self.sample_number = f"{prefix}{sequence:04d}"

        if not self.barcode:
            self.barcode = self.sample_number

        super().save(*args, **kwargs)

    def clean(self):
        super().clean()

        if self.order_item_id:
            if self.order_id != self.order_item.order_id:
                raise ValidationError(
                    "Sample order and order item do not match."
                )

    def __str__(self):
        return f"{self.sample_number} - {self.sample_type.name}"


class LabResult(models.Model):
    class ResultStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ENTERED = "ENTERED", "Entered"
        VERIFIED = "VERIFIED", "Verified"
        AMENDED = "AMENDED", "Amended"
        CANCELLED = "CANCELLED", "Cancelled"

    sample = models.ForeignKey(
        LabSample,
        on_delete=models.PROTECT,
        related_name="results",
    )

    order_item = models.ForeignKey(
        LabOrderItem,
        on_delete=models.PROTECT,
        related_name="results",
    )

    test = models.ForeignKey(
        LabTest,
        on_delete=models.PROTECT,
        related_name="results",
    )

    result_value = models.CharField(
        max_length=500,
        blank=True,
    )

    numeric_value = models.DecimalField(
        max_digits=15,
        decimal_places=5,
        null=True,
        blank=True,
    )

    unit = models.CharField(
        max_length=50,
        blank=True,
    )

    reference_range = models.CharField(
        max_length=255,
        blank=True,
    )

    interpretation = models.TextField(blank=True)

    is_abnormal = models.BooleanField(default=False)

    is_critical = models.BooleanField(default=False)

    status = models.CharField(
        max_length=20,
        choices=ResultStatus.choices,
        default=ResultStatus.PENDING,
    )

    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entered_lab_results",
    )

    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_lab_results",
    )

    entered_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    remarks = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "10. Lab Result"
        verbose_name_plural = "10. Lab Results"
        ordering = ["test__name"]

    def clean(self):
        super().clean()

        if self.sample_id and self.order_item_id:
            if self.sample.order_item_id != self.order_item_id:
                raise ValidationError(
                    "Sample and order item do not match."
                )

        if self.order_item_id and self.test_id:
            if (
                self.order_item.test_id
                and self.order_item.test_id != self.test_id
            ):
                raise ValidationError(
                    "Result test does not match the order item."
                )

        if self.numeric_value is not None:
            if self.numeric_value < 0:
                raise ValidationError(
                    "Numeric result cannot be negative."
                )

    def save(self, *args, **kwargs):
        if self.test_id:
            if not self.unit:
                self.unit = self.test.unit

        if self.numeric_value is not None:
            self.result_value = str(self.numeric_value)

        if self.status == self.ResultStatus.ENTERED:
            if not self.entered_at:
                self.entered_at = timezone.now()

        if self.status == self.ResultStatus.VERIFIED:
            if not self.verified_at:
                self.verified_at = timezone.now()

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.test.name} - {self.result_value}"


class LabReport(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        READY = "READY", "Ready"
        VERIFIED = "VERIFIED", "Verified"
        FINAL = "FINAL", "Final"
        AMENDED = "AMENDED", "Amended"
        CANCELLED = "CANCELLED", "Cancelled"

    report_number = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
    )

    order = models.OneToOneField(
        LabOrder,
        on_delete=models.PROTECT,
        related_name="report",
    )

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="lab_reports",
    )

    report_date = models.DateTimeField(default=timezone.now)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    clinical_summary = models.TextField(blank=True)

    report_notes = models.TextField(blank=True)

    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prepared_lab_reports",
    )

    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_lab_reports",
    )

    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="finalized_lab_reports",
    )

    verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    finalized_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "11. Lab Report"
        verbose_name_plural = "11. Lab Reports"
        ordering = ["-report_date"]

    def save(self, *args, **kwargs):
        if not self.report_number:
            today = timezone.localdate()
            prefix = f"RPT-{today.strftime('%Y%m%d')}-"

            last_report = (
                LabReport.objects
                .filter(report_number__startswith=prefix)
                .order_by("-id")
                .first()
            )

            sequence = 1

            if last_report:
                try:
                    sequence = (
                        int(last_report.report_number.split("-")[-1]) + 1
                    )
                except (ValueError, IndexError):
                    sequence = 1

            self.report_number = f"{prefix}{sequence:04d}"

        if self.order_id:
            self.patient_id = self.order.patient_id

        if self.status == self.Status.VERIFIED:
            if not self.verified_at:
                self.verified_at = timezone.now()

        if self.status == self.Status.FINAL:
            if not self.finalized_at:
                self.finalized_at = timezone.now()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.report_number} - {self.patient}"
