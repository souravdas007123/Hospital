from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from .models import (
    MedicineBatch,
    PharmacyDispensing,
    PharmacyDispensingItem,
    PharmacyPurchase,
    PharmacyPurchaseItem,
    Prescription,
    PrescriptionItem,
    StockTransaction,
)


# ============================================================
# PHARMACY PURCHASE / GRN STOCK PROCESSING
# ============================================================

@transaction.atomic
def process_pharmacy_purchase(purchase, user=None):
    """
    GRN ko RECEIVE karne par stock increase karta hai.

    Rules:
    - Only RECEIVED GRN process hoga.
    - Already processed GRN dobara process nahi hoga.
    - Existing medicine + batch mila to quantity increase.
    - Naya batch ho to new MedicineBatch create.
    - Purchase StockTransaction create.
    """

    purchase = (
        PharmacyPurchase.objects
        .select_for_update()
        .get(pk=purchase.pk)
    )

    if purchase.status != PharmacyPurchase.Status.RECEIVED:
        raise ValidationError(
            "Only RECEIVED GRN can be processed."
        )

    if purchase.stock_processed:
        return purchase

    items = (
        PharmacyPurchaseItem.objects
        .select_related("medicine")
        .select_for_update()
        .filter(purchase=purchase)
    )

    if not items.exists():
        raise ValidationError(
            "Cannot receive GRN without any items."
        )

    for item in items:

        if item.stock_processed:
            continue

        if item.quantity_received <= 0:
            raise ValidationError(
                f"{item.medicine.name}: quantity must be greater than zero."
            )

        if item.expiry_date < purchase.grn_date:
            raise ValidationError(
                f"{item.medicine.name}, batch {item.batch_number}: "
                "expiry date cannot be before GRN date."
            )

        # ----------------------------------------------------
        # Find existing batch
        # ----------------------------------------------------

        batch = (
            MedicineBatch.objects
            .select_for_update()
            .filter(
                medicine_id=item.medicine_id,
                batch_number=item.batch_number,
            )
            .first()
        )

        # ----------------------------------------------------
        # Existing batch
        # ----------------------------------------------------

        if batch:

            if batch.expiry_date != item.expiry_date:
                raise ValidationError(
                    f"Batch {item.batch_number} already exists with "
                    "a different expiry date."
                )

            if not batch.is_active:
                raise ValidationError(
                    f"Batch {item.batch_number} is inactive."
                )

            batch.quantity_received += item.quantity_received
            batch.available_quantity += item.quantity_received

            # Latest purchase price
            batch.purchase_price = item.purchase_price
            batch.selling_price = item.selling_price

            if item.manufacturing_date:
                batch.manufacturing_date = item.manufacturing_date

            batch.received_date = purchase.grn_date

            batch.save(
                update_fields=[
                    "quantity_received",
                    "available_quantity",
                    "purchase_price",
                    "selling_price",
                    "manufacturing_date",
                    "received_date",
                    "updated_at",
                ]
            )

        # ----------------------------------------------------
        # New batch
        # ----------------------------------------------------

        else:

            batch = MedicineBatch.objects.create(
                medicine_id=item.medicine_id,
                batch_number=item.batch_number,
                manufacturing_date=item.manufacturing_date,
                expiry_date=item.expiry_date,
                purchase_price=item.purchase_price,
                selling_price=item.selling_price,
                quantity_received=item.quantity_received,
                available_quantity=item.quantity_received,
                received_date=purchase.grn_date,
                is_active=True,
            )

        # ----------------------------------------------------
        # Stock transaction
        # ----------------------------------------------------

        StockTransaction.objects.create(
            medicine_batch=batch,
            transaction_type=StockTransaction.TransactionType.PURCHASE,
            quantity=item.quantity_received,
            reference_number=purchase.grn_number,
            notes=(
                f"Purchase received from "
                f"{purchase.supplier.name}. "
                f"Supplier invoice: "
                f"{purchase.invoice_number or 'N/A'}"
            ),
            created_by=user or purchase.received_by,
        )

        item.stock_processed = True
        item.save(
            update_fields=["stock_processed"]
        )

    purchase.stock_processed = True

    if not purchase.received_at:
        from django.utils import timezone
        purchase.received_at = timezone.now()

    if user:
        purchase.received_by = user

    purchase.save(
        update_fields=[
            "stock_processed",
            "received_at",
            "received_by",
            "updated_at",
        ]
    )

    return purchase


# ============================================================
# PHARMACY DISPENSING STOCK PROCESSING
# ============================================================

@transaction.atomic
def process_pharmacy_dispensing(dispensing):
    if dispensing.status == PharmacyDispensing.Status.CANCELLED:
        return dispensing

    items = (
        PharmacyDispensingItem.objects
        .select_related(
            "prescription_item",
            "prescription_item__medicine",
            "medicine_batch",
            "medicine_batch__medicine",
        )
        .filter(
            dispensing=dispensing,
            stock_applied=False,
        )
    )

    for item in items:

        batch = (
            MedicineBatch.objects
            .select_for_update()
            .get(pk=item.medicine_batch_id)
        )

        if batch.is_expired:
            raise ValidationError(
                f"Medicine batch {batch.batch_number} has expired."
            )

        if not batch.is_active:
            raise ValidationError(
                f"Medicine batch {batch.batch_number} is inactive."
            )

        if item.quantity_dispensed > batch.available_quantity:
            raise ValidationError(
                f"Insufficient stock for "
                f"{batch.medicine.name}. "
                f"Available: {batch.available_quantity}, "
                f"Required: {item.quantity_dispensed}."
            )

        already_dispensed = (
            PharmacyDispensingItem.objects
            .filter(
                prescription_item_id=item.prescription_item_id,
                stock_applied=True,
            )
            .exclude(pk=item.pk)
            .aggregate(
                total=Sum("quantity_dispensed")
            )["total"]
            or Decimal("0.00")
        )

        prescribed_quantity = (
            item.prescription_item.quantity_prescribed
        )

        remaining_quantity = (
            prescribed_quantity - already_dispensed
        )

        if item.quantity_dispensed > remaining_quantity:
            raise ValidationError(
                f"{item.prescription_item.medicine.name}: "
                f"Only {remaining_quantity} remaining "
                "from prescribed quantity."
            )

        batch.available_quantity -= item.quantity_dispensed

        batch.save(
            update_fields=[
                "available_quantity",
                "updated_at",
            ]
        )

        StockTransaction.objects.create(
            medicine_batch=batch,
            transaction_type=(
                StockTransaction.TransactionType.DISPENSE
            ),
            quantity=item.quantity_dispensed,
            reference_number=(
                dispensing.dispensing_number
            ),
            notes=(
                "Dispensed against prescription "
                f"{dispensing.prescription.prescription_number}"
            ),
            created_by=dispensing.dispensed_by,
        )

        item.stock_applied = True

        item.save(
            update_fields=["stock_applied"]
        )

    update_prescription_status(
        dispensing.prescription
    )

    return dispensing


# ============================================================
# UPDATE PRESCRIPTION STATUS
# ============================================================

def update_prescription_status(prescription):

    prescription_items = (
        PrescriptionItem.objects
        .filter(
            prescription=prescription,
            is_discontinued=False,
        )
    )

    if not prescription_items.exists():
        return

    all_dispensed = True
    any_dispensed = False

    for prescription_item in prescription_items:

        dispensed_quantity = (
            PharmacyDispensingItem.objects
            .filter(
                prescription_item=prescription_item,
                stock_applied=True,
            )
            .aggregate(
                total=Sum("quantity_dispensed")
            )["total"]
            or Decimal("0.00")
        )

        prescribed_quantity = (
            prescription_item.quantity_prescribed
        )

        if dispensed_quantity > Decimal("0.00"):
            any_dispensed = True

        if dispensed_quantity < prescribed_quantity:
            all_dispensed = False

    if all_dispensed:
        prescription.status = Prescription.Status.DISPENSED

    elif any_dispensed:
        prescription.status = (
            Prescription.Status.PARTIALLY_DISPENSED
        )

    else:
        prescription.status = Prescription.Status.ACTIVE

    prescription.save(
        update_fields=["status", "updated_at"]
    )