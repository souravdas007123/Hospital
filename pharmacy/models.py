from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from doctors.models import Doctor
from opd.models import OPDVisit
from patients.models import Patient


# ============================================================
# MEDICINE CATEGORY
# ============================================================

class MedicineCategory(models.Model):
    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=30, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Medicine Category"
        verbose_name_plural = "Medicine Categories"

    def __str__(self):
        return f"{self.code} - {self.name}"


# ============================================================
# MANUFACTURER
# ============================================================

class Manufacturer(models.Model):
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=30, unique=True)

    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)

    address = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return f"{self.code} - {self.name}"


# ============================================================
# MEDICINE
# ============================================================

class Medicine(models.Model):

    class DosageForm(models.TextChoices):
        TABLET = "TABLET", "Tablet"
        CAPSULE = "CAPSULE", "Capsule"
        SYRUP = "SYRUP", "Syrup"
        INJECTION = "INJECTION", "Injection"
        CREAM = "CREAM", "Cream"
        OINTMENT = "OINTMENT", "Ointment"
        DROPS = "DROPS", "Drops"
        INHALER = "INHALER", "Inhaler"
        POWDER = "POWDER", "Powder"
        SUSPENSION = "SUSPENSION", "Suspension"
        SOLUTION = "SOLUTION", "Solution"
        OTHER = "OTHER", "Other"

    medicine_code = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        db_index=True,
    )

    category = models.ForeignKey(
        MedicineCategory,
        on_delete=models.PROTECT,
        related_name="medicines",
    )

    manufacturer = models.ForeignKey(
        Manufacturer,
        on_delete=models.PROTECT,
        related_name="medicines",
        blank=True,
        null=True,
    )

    name = models.CharField(max_length=255)
    generic_name = models.CharField(max_length=255, blank=True)
    brand_name = models.CharField(max_length=255, blank=True)
    strength = models.CharField(max_length=100, blank=True)

    dosage_form = models.CharField(
        max_length=30,
        choices=DosageForm.choices,
        default=DosageForm.TABLET,
    )

    unit = models.CharField(max_length=50, default="Unit")

    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    reorder_level = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.medicine_code:
            last = Medicine.objects.order_by("-id").first()

            if last and last.medicine_code.startswith("MED-"):
                try:
                    number = int(last.medicine_code.split("-")[-1]) + 1
                except ValueError:
                    number = self.pk or 1
            else:
                number = 1

            self.medicine_code = f"MED-{number:05d}"

        super().save(*args, **kwargs)

    @property
    def current_stock(self):
        total = self.batches.filter(
            is_active=True
        ).aggregate(
            total=models.Sum("available_quantity")
        )["total"]

        return total or Decimal("0.00")

    @property
    def is_low_stock(self):
        return self.current_stock <= self.reorder_level

    def __str__(self):
        return f"{self.medicine_code} - {self.name}"


# ============================================================
# MEDICINE BATCH
# ============================================================

class MedicineBatch(models.Model):
    medicine = models.ForeignKey(
        Medicine,
        on_delete=models.PROTECT,
        related_name="batches",
    )

    batch_number = models.CharField(max_length=100)

    manufacturing_date = models.DateField(
        blank=True,
        null=True,
    )

    expiry_date = models.DateField()

    purchase_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    selling_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    quantity_received = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    available_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    received_date = models.DateField(
        default=timezone.localdate,
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("expiry_date", "batch_number")
        constraints = [
            models.UniqueConstraint(
                fields=("medicine", "batch_number"),
                name="unique_medicine_batch",
            )
        ]

    def clean(self):
        if self.expiry_date and self.expiry_date < timezone.localdate():
            raise ValidationError(
                "Expired medicine batch cannot be created."
            )

        if self.available_quantity > self.quantity_received:
            raise ValidationError(
                "Available quantity cannot be greater than received quantity."
            )

        if self.available_quantity < 0:
            raise ValidationError(
                "Available quantity cannot be negative."
            )

    def save(self, *args, **kwargs):
        if not self.pk:
            self.available_quantity = self.quantity_received

        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return self.expiry_date < timezone.localdate()

    @property
    def is_near_expiry(self):
        if self.is_expired:
            return False

        days = (self.expiry_date - timezone.localdate()).days
        return days <= 90

    def __str__(self):
        return f"{self.medicine.name} - {self.batch_number}"


# ============================================================
# STOCK TRANSACTION
# ============================================================

class StockTransaction(models.Model):

    class TransactionType(models.TextChoices):
        OPENING = "OPENING", "Opening Stock"
        PURCHASE = "PURCHASE", "Purchase"
        DISPENSE = "DISPENSE", "Dispense"
        RETURN = "RETURN", "Return"
        EXPIRED = "EXPIRED", "Expired"
        DAMAGED = "DAMAGED", "Damaged"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    medicine_batch = models.ForeignKey(
        MedicineBatch,
        on_delete=models.PROTECT,
        related_name="stock_transactions",
    )

    transaction_type = models.CharField(
        max_length=20,
        choices=TransactionType.choices,
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    reference_number = models.CharField(
        max_length=100,
        blank=True,
    )

    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pharmacy_stock_transactions",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return (
            f"{self.medicine_batch} - "
            f"{self.get_transaction_type_display()} - "
            f"{self.quantity}"
        )


# ============================================================
# SUPPLIER
# ============================================================

class Supplier(models.Model):
    supplier_code = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        db_index=True,
    )

    name = models.CharField(max_length=255)

    gstin = models.CharField(
        max_length=20,
        blank=True,
    )

    contact_person = models.CharField(
        max_length=150,
        blank=True,
    )

    phone = models.CharField(
        max_length=30,
        blank=True,
    )

    alternate_phone = models.CharField(
        max_length=30,
        blank=True,
    )

    email = models.EmailField(blank=True)

    address = models.TextField(blank=True)

    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def save(self, *args, **kwargs):
        if not self.supplier_code:
            last = Supplier.objects.order_by("-id").first()

            if last and last.supplier_code.startswith("SUP-"):
                try:
                    number = int(last.supplier_code.split("-")[-1]) + 1
                except ValueError:
                    number = self.pk or 1
            else:
                number = 1

            self.supplier_code = f"SUP-{number:05d}"

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.supplier_code} - {self.name}"


# ============================================================
# PHARMACY PURCHASE / GRN
# ============================================================

class PharmacyPurchase(models.Model):

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        RECEIVED = "RECEIVED", "Received"
        CANCELLED = "CANCELLED", "Cancelled"

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIAL = "PARTIAL", "Partially Paid"
        PAID = "PAID", "Paid"

    grn_number = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        db_index=True,
    )

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="purchases",
    )

    grn_date = models.DateField(
        default=timezone.localdate,
    )

    invoice_number = models.CharField(
        max_length=100,
        blank=True,
    )

    invoice_date = models.DateField(
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
    )

    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pharmacy_purchases_created",
    )

    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pharmacy_purchases_received",
    )

    received_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    stock_processed = models.BooleanField(
        default=False,
        editable=False,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-grn_date", "-id")
        verbose_name = "Pharmacy Purchase / GRN"
        verbose_name_plural = "Pharmacy Purchases / GRNs"

    def save(self, *args, **kwargs):
        if not self.grn_number:
            today = timezone.localdate()
            prefix = f"GRN-{today.strftime('%Y%m%d')}-"

            last = (
                PharmacyPurchase.objects
                .filter(grn_number__startswith=prefix)
                .order_by("-id")
                .first()
            )

            if last:
                try:
                    number = int(last.grn_number.split("-")[-1]) + 1
                except ValueError:
                    number = 1
            else:
                number = 1

            self.grn_number = f"{prefix}{number:04d}"

        if self.status == self.Status.RECEIVED and not self.received_at:
            self.received_at = timezone.now()

        super().save(*args, **kwargs)

    @property
    def grand_total(self):
        return sum(
            (item.total_amount for item in self.items.all()),
            Decimal("0.00"),
        )

    def __str__(self):
        return f"{self.grn_number} - {self.supplier.name}"


# ============================================================
# PHARMACY PURCHASE / GRN ITEM
# ============================================================

class PharmacyPurchaseItem(models.Model):
    purchase = models.ForeignKey(
        PharmacyPurchase,
        on_delete=models.CASCADE,
        related_name="items",
    )

    medicine = models.ForeignKey(
        Medicine,
        on_delete=models.PROTECT,
        related_name="purchase_items",
    )

    batch_number = models.CharField(
        max_length=100,
    )

    manufacturing_date = models.DateField(
        blank=True,
        null=True,
    )

    expiry_date = models.DateField()

    quantity_received = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    purchase_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    selling_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    stock_processed = models.BooleanField(
        default=False,
        editable=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ("id",)

    def clean(self):
        if self.quantity_received <= 0:
            raise ValidationError(
                "Received quantity must be greater than zero."
            )

        if self.expiry_date < timezone.localdate():
            raise ValidationError(
                f"Medicine batch {self.batch_number} is already expired."
            )

        if self.purchase_price < 0:
            raise ValidationError(
                "Purchase price cannot be negative."
            )

        if self.selling_price < 0:
            raise ValidationError(
                "Selling price cannot be negative."
            )

        if self.gst_rate < 0 or self.gst_rate > 100:
            raise ValidationError(
                "GST rate must be between 0 and 100."
            )

    @property
    def subtotal(self):
        return (
            self.quantity_received * self.purchase_price
        )

    @property
    def taxable_amount(self):
        return self.subtotal - self.discount

    @property
    def gst_amount(self):
        return (
            self.taxable_amount * self.gst_rate / Decimal("100")
        )

    @property
    def total_amount(self):
        return self.taxable_amount + self.gst_amount

    def __str__(self):
        return (
            f"{self.purchase.grn_number} - "
            f"{self.medicine.name} - "
            f"{self.batch_number}"
        )


# ============================================================
# PRESCRIPTION
# ============================================================

class Prescription(models.Model):

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        PARTIALLY_DISPENSED = (
            "PARTIALLY_DISPENSED",
            "Partially Dispensed",
        )
        DISPENSED = "DISPENSED", "Dispensed"
        CANCELLED = "CANCELLED", "Cancelled"

    prescription_number = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        db_index=True,
    )

    opd_visit = models.OneToOneField(
        OPDVisit,
        on_delete=models.PROTECT,
        related_name="prescription",
    )

    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="prescriptions",
    )

    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        related_name="prescriptions",
    )

    prescription_date = models.DateField(
        default=timezone.localdate,
    )

    diagnosis_summary = models.TextField(blank=True)
    instructions = models.TextField(blank=True)

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prescriptions_created",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-prescription_date", "-id")

    def clean(self):
        if self.opd_visit_id:
            if self.patient_id != self.opd_visit.patient_id:
                raise ValidationError(
                    "Prescription patient must match OPD visit patient."
                )

            if self.doctor_id != self.opd_visit.doctor_id:
                raise ValidationError(
                    "Prescription doctor must match OPD visit doctor."
                )

        if self.status == self.Status.CANCELLED:
            return

    def save(self, *args, **kwargs):
        if not self.prescription_number:
            today = timezone.localdate()
            prefix = f"RX-{today.strftime('%Y%m%d')}-"

            last = (
                Prescription.objects
                .filter(
                    prescription_number__startswith=prefix
                )
                .order_by("-id")
                .first()
            )

            if last:
                try:
                    number = int(
                        last.prescription_number.split("-")[-1]
                    ) + 1
                except ValueError:
                    number = 1
            else:
                number = 1

            self.prescription_number = f"{prefix}{number:04d}"

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.prescription_number


# ============================================================
# PRESCRIPTION ITEM
# ============================================================

class PrescriptionItem(models.Model):

    class DurationUnit(models.TextChoices):
        DAY = "DAY", "Day"
        WEEK = "WEEK", "Week"
        MONTH = "MONTH", "Month"

    class Route(models.TextChoices):
        ORAL = "ORAL", "Oral"
        IV = "IV", "IV"
        IM = "IM", "IM"
        SC = "SC", "SC"
        TOPICAL = "TOPICAL", "Topical"
        INHALATION = "INHALATION", "Inhalation"
        OPHTHALMIC = "OPHTHALMIC", "Ophthalmic"
        OTIC = "OTIC", "Otic"
        NASAL = "NASAL", "Nasal"
        RECTAL = "RECTAL", "Rectal"
        OTHER = "OTHER", "Other"

    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.CASCADE,
        related_name="items",
    )

    medicine = models.ForeignKey(
        Medicine,
        on_delete=models.PROTECT,
        related_name="prescription_items",
    )

    dose = models.CharField(
        max_length=100,
    )

    frequency = models.CharField(
        max_length=100,
    )

    duration_value = models.PositiveIntegerField()

    duration_unit = models.CharField(
        max_length=10,
        choices=DurationUnit.choices,
        default=DurationUnit.DAY,
    )

    route = models.CharField(
        max_length=20,
        choices=Route.choices,
        default=Route.ORAL,
    )

    quantity_prescribed = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    instructions = models.TextField(
        blank=True,
    )

    is_discontinued = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def clean(self):
        if self.medicine_id and not self.medicine.is_active:
            raise ValidationError(
                "Inactive medicine cannot be prescribed."
            )

        if self.quantity_prescribed <= 0:
            raise ValidationError(
                "Prescribed quantity must be greater than zero."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.prescription.prescription_number} - "
            f"{self.medicine.name}"
        )


# ============================================================
# PHARMACY DISPENSING
# ============================================================

class PharmacyDispensing(models.Model):

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PARTIALLY_DISPENSED = (
            "PARTIALLY_DISPENSED",
            "Partially Dispensed",
        )
        DISPENSED = "DISPENSED", "Dispensed"
        CANCELLED = "CANCELLED", "Cancelled"

    dispensing_number = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        db_index=True,
    )

    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.PROTECT,
        related_name="dispensings",
    )

    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="pharmacy_dispensings",
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
    )

    notes = models.TextField(blank=True)

    dispensed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pharmacy_dispensings",
    )

    dispensed_at = models.DateTimeField(
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
        ordering = ("-created_at",)

    def clean(self):
        if self.prescription_id and self.patient_id:
            if self.patient_id != self.prescription.patient_id:
                raise ValidationError(
                    "Dispensing patient must match prescription patient."
                )

    def save(self, *args, **kwargs):
        if not self.dispensing_number:
            today = timezone.localdate()
            prefix = f"DISP-{today.strftime('%Y%m%d')}-"

            last = (
                PharmacyDispensing.objects
                .filter(
                    dispensing_number__startswith=prefix
                )
                .order_by("-id")
                .first()
            )

            if last:
                try:
                    number = int(
                        last.dispensing_number.split("-")[-1]
                    ) + 1
                except ValueError:
                    number = 1
            else:
                number = 1

            self.dispensing_number = f"{prefix}{number:04d}"

        if (
            self.status == self.Status.DISPENSED
            and not self.dispensed_at
        ):
            self.dispensed_at = timezone.now()

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.dispensing_number


# ============================================================
# PHARMACY DISPENSING ITEM
# ============================================================

class PharmacyDispensingItem(models.Model):

    dispensing = models.ForeignKey(
        PharmacyDispensing,
        on_delete=models.CASCADE,
        related_name="items",
    )

    prescription_item = models.ForeignKey(
        PrescriptionItem,
        on_delete=models.PROTECT,
        related_name="dispensing_items",
    )

    medicine_batch = models.ForeignKey(
        MedicineBatch,
        on_delete=models.PROTECT,
        related_name="dispensing_items",
    )

    quantity_dispensed = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    selling_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    stock_applied = models.BooleanField(
        default=False,
        editable=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ("-created_at",)

    def clean(self):
        if self.prescription_item_id and self.medicine_batch_id:
            if (
                self.prescription_item.medicine_id
                != self.medicine_batch.medicine_id
            ):
                raise ValidationError(
                    "Medicine batch must match prescription medicine."
                )

        if self.medicine_batch_id:
            if self.medicine_batch.is_expired:
                raise ValidationError(
                    f"Batch {self.medicine_batch.batch_number} is expired."
                )

            if (
                self.quantity_dispensed
                > self.medicine_batch.available_quantity
            ):
                raise ValidationError(
                    "Insufficient medicine stock."
                )

        if self.quantity_dispensed <= 0:
            raise ValidationError(
                "Dispensed quantity must be greater than zero."
            )

    def save(self, *args, **kwargs):
        if self.medicine_batch_id:
            if self.selling_price == Decimal("0.00"):
                self.selling_price = (
                    self.medicine_batch.selling_price
                )

        if self.prescription_item_id:
            if self.gst_rate == Decimal("0.00"):
                self.gst_rate = (
                    self.prescription_item.medicine.gst_rate
                )

        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def subtotal(self):
        return (
            self.quantity_dispensed * self.selling_price
        )

    @property
    def gst_amount(self):
        taxable = self.subtotal - self.discount

        if taxable < 0:
            taxable = Decimal("0.00")

        return taxable * self.gst_rate / Decimal("100")

    @property
    def total_amount(self):
        taxable = self.subtotal - self.discount

        if taxable < 0:
            taxable = Decimal("0.00")

        return taxable + self.gst_amount

    def __str__(self):
        return (
            f"{self.dispensing.dispensing_number} - "
            f"{self.prescription_item.medicine.name}"
        )

# ============================================================
# PHARMACY PURCHASE RETURN
# ============================================================

class PharmacyPurchaseReturn(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PROCESSED = "PROCESSED", "Processed"
        CANCELLED = "CANCELLED", "Cancelled"

    return_number = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
    )

    purchase = models.ForeignKey(
        PharmacyPurchase,
        on_delete=models.PROTECT,
        related_name="purchase_returns",
    )

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="purchase_returns",
    )

    return_date = models.DateField(default=timezone.localdate)

    reason = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    stock_reversed = models.BooleanField(
        default=False,
        editable=False,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_pharmacy_purchase_returns",
    )

    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processed_pharmacy_purchase_returns",
    )

    processed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_amount(self):
        return sum(
            item.total_amount
            for item in self.items.all()
        )

    def save(self, *args, **kwargs):
        if not self.return_number:
            today = timezone.localdate()

            prefix = f"PR-{today.strftime('%Y%m%d')}-"

            last_return = (
                PharmacyPurchaseReturn.objects
                .filter(return_number__startswith=prefix)
                .order_by("-id")
                .first()
            )

            sequence = 1

            if last_return:
                try:
                    sequence = (
                        int(last_return.return_number.split("-")[-1])
                        + 1
                    )
                except (ValueError, IndexError):
                    sequence = 1

            self.return_number = f"{prefix}{sequence:04d}"

        if self.purchase_id:
            self.supplier_id = self.purchase.supplier_id

        super().save(*args, **kwargs)

    def __str__(self):
        return self.return_number


class PharmacyPurchaseReturnItem(models.Model):
    purchase_return = models.ForeignKey(
        PharmacyPurchaseReturn,
        on_delete=models.CASCADE,
        related_name="items",
    )

    purchase_item = models.ForeignKey(
        PharmacyPurchaseItem,
        on_delete=models.PROTECT,
        related_name="return_items",
    )

    medicine = models.ForeignKey(
        Medicine,
        on_delete=models.PROTECT,
        related_name="purchase_return_items",
    )

    medicine_batch = models.ForeignKey(
        MedicineBatch,
        on_delete=models.PROTECT,
        related_name="purchase_return_items",
    )

    quantity_returned = models.PositiveIntegerField()

    return_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
    )

    reason = models.CharField(
        max_length=255,
        blank=True,
    )

    stock_reversed = models.BooleanField(
        default=False,
        editable=False,
    )

    @property
    def subtotal(self):
        return (
            self.quantity_returned *
            self.return_price
        )

    @property
    def gst_amount(self):
        return (
            self.subtotal *
            self.gst_rate /
            Decimal("100")
        )

    @property
    def total_amount(self):
        return self.subtotal + self.gst_amount

    def clean(self):
        super().clean()

        if self.quantity_returned <= 0:
            raise ValidationError(
                "Return quantity must be greater than zero."
            )

        if self.purchase_item_id and self.medicine_id:
            if self.purchase_item.medicine_id != self.medicine_id:
                raise ValidationError(
                    "Medicine does not match the original purchase item."
                )

        if self.medicine_batch_id and self.medicine_id:
            if self.medicine_batch.medicine_id != self.medicine_id:
                raise ValidationError(
                    "Selected batch does not belong to this medicine."
                )

        if self.purchase_item_id and self.medicine_batch_id:
            if (
                self.purchase_item.medicine_id
                != self.medicine_batch.medicine_id
            ):
                raise ValidationError(
                    "Purchase item and batch medicine do not match."
                )

    def save(self, *args, **kwargs):
        if self.purchase_item_id:
            self.medicine_id = self.purchase_item.medicine_id

            if not self.return_price:
                self.return_price = (
                    self.purchase_item.purchase_price
                )

            self.gst_rate = (
                self.purchase_item.gst_rate
            )

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.purchase_return.return_number} - "
            f"{self.medicine.name}"
        )        