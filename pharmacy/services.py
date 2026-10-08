from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    Medicine,
    MedicineBatch,
    StockTransaction,
    PharmacyPurchase,
    PharmacyPurchaseItem,
    PharmacyPurchaseReturn,
    PharmacyPurchaseReturnItem,
    Prescription,
    PharmacyDispensing,
    PharmacyDispensingItem,
)


# ============================================================
# PURCHASE / GRN
# ============================================================

@transaction.atomic
def process_pharmacy_purchase(purchase, user=None):
    """
    Process received GRN and add stock.
    Prevents duplicate stock processing.
    """

    purchase = (
        PharmacyPurchase.objects
        .select_for_update()
        .get(pk=purchase.pk)
    )

    if purchase.status != PharmacyPurchase.Status.RECEIVED:
        raise ValidationError(
            "Only RECEIVED purchases can be processed."
        )

    if purchase.stock_processed:
        return purchase

    items = list(
        purchase.items.select_related("medicine")
    )

    if not items:
        raise ValidationError(
            "Purchase cannot be received without items."
        )

    for item in items:

        if item.quantity_received <= 0:
            raise ValidationError(
                f"Invalid quantity for {item.medicine.name}."
            )

        batch, created = (
            MedicineBatch.objects
            .select_for_update()
            .get_or_create(
                medicine=item.medicine,
                batch_number=item.batch_number,
                defaults={
                    "manufacturing_date": item.manufacturing_date,
                    "expiry_date": item.expiry_date,
                    "purchase_price": item.purchase_price,
                    "selling_price": item.selling_price,
                    "quantity_received": item.quantity_received,
                    "available_quantity": item.quantity_received,
                    "received_date": purchase.grn_date,
                    "is_active": True,
                },
            )
        )

        if not created:
            batch.quantity_received += item.quantity_received
            batch.available_quantity += item.quantity_received

            batch.purchase_price = item.purchase_price
            batch.selling_price = item.selling_price

            if item.manufacturing_date:
                batch.manufacturing_date = item.manufacturing_date

            if item.expiry_date:
                batch.expiry_date = item.expiry_date

            batch.is_active = True
            batch.save()

        StockTransaction.objects.create(
            medicine=item.medicine,
            medicine_batch=batch,
            transaction_type=StockTransaction.TransactionType.PURCHASE,
            quantity=item.quantity_received,
            reference=purchase.grn_number,
            notes=f"Stock received through GRN {purchase.grn_number}",
            created_by=user or purchase.received_by,
        )

        item.stock_processed = True
        item.save(
            update_fields=["stock_processed"]
        )

    purchase.stock_processed = True
    purchase.received_at = (
        purchase.received_at or timezone.now()
    )

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
# PURCHASE RETURN
# ============================================================

@transaction.atomic
def process_pharmacy_purchase_return(
    purchase_return,
    user=None,
):
    """
    Reverse stock for a supplier purchase return.

    Safety:
    - Only PROCESSED returns are allowed.
    - Cannot return more than available stock.
    - Cannot process the same return twice.
    - Creates RETURN stock transaction.
    """

    purchase_return = (
        PharmacyPurchaseReturn.objects
        .select_for_update()
        .get(pk=purchase_return.pk)
    )

    if purchase_return.status == (
        PharmacyPurchaseReturn.Status.CANCELLED
    ):
        raise ValidationError(
            "Cancelled purchase return cannot be processed."
        )

    if purchase_return.stock_reversed:
        return purchase_return

    if purchase_return.purchase.status != (
        PharmacyPurchase.Status.RECEIVED
    ):
        raise ValidationError(
            "Purchase must be RECEIVED before stock can be returned."
        )

    items = list(
        purchase_return.items
        .select_related(
            "medicine",
            "medicine_batch",
            "purchase_item",
        )
    )

    if not items:
        raise ValidationError(
            "Purchase return must contain at least one item."
        )

    for item in items:

        if item.stock_reversed:
            continue

        batch = (
            MedicineBatch.objects
            .select_for_update()
            .get(pk=item.medicine_batch_id)
        )

        if batch.medicine_id != item.medicine_id:
            raise ValidationError(
                f"Batch does not belong to {item.medicine.name}."
            )

        if item.quantity_returned <= 0:
            raise ValidationError(
                f"Invalid return quantity for {item.medicine.name}."
            )

        # ----------------------------------------------------
        # Check how much has already been returned against
        # original purchase item.
        # ----------------------------------------------------

        previous_returned = (
            PharmacyPurchaseReturnItem.objects
            .filter(
                purchase_item=item.purchase_item,
                purchase_return__status=(
                    PharmacyPurchaseReturn.Status.PROCESSED
                ),
            )
            .exclude(pk=item.pk)
            .aggregate(
                total=Sum("quantity_returned")
            )["total"]
            or 0
        )

        total_allowed = (
            item.purchase_item.quantity_received
        )

        if (
            previous_returned +
            item.quantity_returned
            > total_allowed
        ):
            raise ValidationError(
                f"Return quantity exceeds purchased quantity "
                f"for {item.medicine.name}. "
                f"Purchased: {total_allowed}, "
                f"Already returned: {previous_returned}."
            )

        # ----------------------------------------------------
        # Check current physical stock.
        # ----------------------------------------------------

        if (
            batch.available_quantity
            < item.quantity_returned
        ):
            raise ValidationError(
                f"Insufficient stock in batch "
                f"{batch.batch_number} for "
                f"{item.medicine.name}. "
                f"Available: {batch.available_quantity}, "
                f"Return: {item.quantity_returned}."
            )

        batch.available_quantity -= (
            item.quantity_returned
        )

        if batch.available_quantity == 0:
            batch.is_active = False

        batch.save(
            update_fields=[
                "available_quantity",
                "is_active",
            ]
        )

        StockTransaction.objects.create(
            medicine=item.medicine,
            medicine_batch=batch,
            transaction_type=(
                StockTransaction.TransactionType.RETURN
            ),
            quantity=-item.quantity_returned,
            reference=purchase_return.return_number,
            notes=(
                f"Supplier purchase return "
                f"{purchase_return.return_number}"
            ),
            created_by=user or purchase_return.created_by,
        )

        item.stock_reversed = True
        item.save(
            update_fields=["stock_reversed"]
        )

    purchase_return.stock_reversed = True
    purchase_return.status = (
        PharmacyPurchaseReturn.Status.PROCESSED
    )
    purchase_return.processed_at = timezone.now()

    if user:
        purchase_return.processed_by = user

    purchase_return.save(
        update_fields=[
            "stock_reversed",
            "status",
            "processed_at",
            "processed_by",
            "updated_at",
        ]
    )

    return purchase_return


# ============================================================
# FEFO - FIRST EXPIRY, FIRST OUT
# ============================================================

def get_fefo_batches(
    medicine,
    required_quantity,
):
    """
    Return active, non-expired batches ordered by earliest expiry.
    """

    today = timezone.localdate()

    batches = (
        MedicineBatch.objects
        .select_for_update()
        .filter(
            medicine=medicine,
            is_active=True,
            available_quantity__gt=0,
        )
        .filter(
            expiry_date__isnull=True
        )
        | MedicineBatch.objects
        .select_for_update()
        .filter(
            medicine=medicine,
            is_active=True,
            available_quantity__gt=0,
            expiry_date__gte=today,
        )
    )

    batches = batches.order_by(
        "expiry_date",
        "id",
    )

    total_available = sum(
        batch.available_quantity
        for batch in batches
    )

    if total_available < required_quantity:
        raise ValidationError(
            f"Insufficient stock for {medicine.name}. "
            f"Required: {required_quantity}, "
            f"Available: {total_available}."
        )

    return list(batches)


def allocate_fefo_batches(
    medicine,
    required_quantity,
):
    """
    Allocate stock from batches using FEFO.

    Example:
        Batch A = 5
        Batch B = 10
        Required = 8

    Result:
        Batch A = 5
        Batch B = 3
    """

    if required_quantity <= 0:
        raise ValidationError(
            "Required quantity must be greater than zero."
        )

    batches = get_fefo_batches(
        medicine,
        required_quantity,
    )

    allocations = []
    remaining = required_quantity

    for batch in batches:

        if remaining <= 0:
            break

        quantity = min(
            batch.available_quantity,
            remaining,
        )

        allocations.append(
            {
                "batch": batch,
                "quantity": quantity,
            }
        )

        remaining -= quantity

    if remaining > 0:
        raise ValidationError(
            f"Unable to allocate FEFO stock for "
            f"{medicine.name}."
        )

    return allocations


# ============================================================
# DISPENSING
# ============================================================

@transaction.atomic
def process_pharmacy_dispensing(dispensing):
    """
    Deduct pharmacy stock.

    FEFO is automatically used when a dispensing item
    does not have a manually selected batch.

    If a batch is already selected, that batch is respected.
    """

    dispensing = (
        PharmacyDispensing.objects
        .select_for_update()
        .get(pk=dispensing.pk)
    )

    if dispensing.status == (
        PharmacyDispensing.Status.CANCELLED
    ):
        raise ValidationError(
            "Cancelled dispensing cannot be processed."
        )

    items = list(
        dispensing.items.select_related(
            "prescription_item__medicine",
            "medicine_batch",
        )
    )

    if not items:
        raise ValidationError(
            "Dispensing must contain at least one item."
        )

    for item in items:

        if item.stock_applied:
            continue

        prescription_item = item.prescription_item
        medicine = prescription_item.medicine

        required_quantity = item.quantity_dispensed

        if required_quantity <= 0:
            raise ValidationError(
                f"Invalid dispensing quantity for "
                f"{medicine.name}."
            )

        # ----------------------------------------------------
        # Determine already dispensed quantity
        # ----------------------------------------------------

        already_dispensed = (
            PharmacyDispensingItem.objects
            .filter(
                prescription_item=prescription_item,
                stock_applied=True,
            )
            .exclude(pk=item.pk)
            .aggregate(
                total=Sum("quantity_dispensed")
            )["total"]
            or 0
        )

        prescribed_quantity = (
            prescription_item.quantity
        )

        if (
            already_dispensed +
            required_quantity
            > prescribed_quantity
        ):
            raise ValidationError(
                f"Dispensing quantity exceeds prescription "
                f"quantity for {medicine.name}. "
                f"Prescribed: {prescribed_quantity}, "
                f"Already dispensed: {already_dispensed}, "
                f"Requested: {required_quantity}."
            )

        # ----------------------------------------------------
        # FEFO allocation
        # ----------------------------------------------------

        if item.medicine_batch_id:
            batches = [
                {
                    "batch": (
                        MedicineBatch.objects
                        .select_for_update()
                        .get(
                            pk=item.medicine_batch_id
                        )
                    ),
                    "quantity": required_quantity,
                }
            ]
        else:
            batches = allocate_fefo_batches(
                medicine,
                required_quantity,
            )

        remaining = required_quantity

        for allocation in batches:

            batch = allocation["batch"]
            quantity = allocation["quantity"]

            if (
                batch.expiry_date
                and batch.expiry_date < timezone.localdate()
            ):
                raise ValidationError(
                    f"Batch {batch.batch_number} "
                    f"of {medicine.name} is expired."
                )

            if not batch.is_active:
                raise ValidationError(
                    f"Batch {batch.batch_number} "
                    f"is inactive."
                )

            if batch.available_quantity < quantity:
                raise ValidationError(
                    f"Insufficient stock in batch "
                    f"{batch.batch_number}."
                )

            batch.available_quantity -= quantity

            if batch.available_quantity == 0:
                batch.is_active = False

            batch.save(
                update_fields=[
                    "available_quantity",
                    "is_active",
                ]
            )

            StockTransaction.objects.create(
                medicine=medicine,
                medicine_batch=batch,
                transaction_type=(
                    StockTransaction.TransactionType.DISPENSE
                ),
                quantity=-quantity,
                reference=dispensing.dispensing_number,
                notes=(
                    f"Medicine dispensed through "
                    f"{dispensing.dispensing_number}"
                ),
                created_by=dispensing.dispensed_by,
            )

            remaining -= quantity

        if remaining > 0:
            raise ValidationError(
                f"Unable to deduct complete quantity "
                f"for {medicine.name}."
            )

        # ----------------------------------------------------
        # For FEFO allocation, store the first selected batch
        # on the dispensing item.
        # ----------------------------------------------------

        if not item.medicine_batch_id and batches:
            item.medicine_batch = batches[0]["batch"]

        item.stock_applied = True

        item.save(
            update_fields=[
                "medicine_batch",
                "stock_applied",
            ]
        )

    update_prescription_status(
        dispensing.prescription
    )

    return dispensing


# ============================================================
# PRESCRIPTION STATUS
# ============================================================

def update_prescription_status(prescription):
    """
    Automatically update prescription dispensing status.
    """

    items = list(
        prescription.items.all()
    )

    if not items:
        return

    total_prescribed = sum(
        item.quantity
        for item in items
    )

    total_dispensed = (
        PharmacyDispensingItem.objects
        .filter(
            prescription_item__prescription=prescription,
            stock_applied=True,
        )
        .aggregate(
            total=Sum("quantity_dispensed")
        )["total"]
        or 0
    )

    if total_dispensed <= 0:
        new_status = Prescription.Status.ACTIVE

    elif total_dispensed < total_prescribed:
        new_status = (
            Prescription.Status.PARTIALLY_DISPENSED
        )

    else:
        new_status = Prescription.Status.DISPENSED

    if prescription.status != new_status:
        prescription.status = new_status

        prescription.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )