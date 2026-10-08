from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    LabOrder,
    LabOrderItem,
    LabPackage,
    LabPackageItem,
    LabSample,
    LabResult,
    LabReport,
    LabReferenceRange,
)


# =========================================================
# PACKAGE → TESTS
# =========================================================

@transaction.atomic
def add_package_to_order(order, package):
    """
    Adds all tests from a package to a Lab Order.

    Existing tests are not duplicated.
    """

    if order.status == LabOrder.Status.CANCELLED:
        raise ValidationError(
            "Cannot add tests to a cancelled lab order."
        )

    if not package.is_active:
        raise ValidationError(
            "Selected lab package is inactive."
        )

    package_items = (
        LabPackageItem.objects
        .select_related("test")
        .filter(package=package)
    )

    if not package_items.exists():
        raise ValidationError(
            f"Package '{package.name}' has no tests."
        )

    created_items = []

    for package_item in package_items:
        test = package_item.test

        existing_item = (
            order.items
            .filter(
                item_type=LabOrderItem.ItemType.TEST,
                test=test,
            )
            .first()
        )

        if existing_item:
            continue

        item = LabOrderItem.objects.create(
            order=order,
            item_type=LabOrderItem.ItemType.TEST,
            test=test,
            quantity=1,
            price=test.price,
            discount=Decimal("0.00"),
            status=LabOrderItem.Status.ORDERED,
        )

        created_items.append(item)

    update_order_total(order)

    return created_items


# =========================================================
# ORDER TOTAL
# =========================================================

def update_order_total(order):
    """
    Recalculates Lab Order total.
    """

    total = Decimal("0.00")

    for item in order.items.all():
        total += item.total_amount

    order.total_amount = total
    order.save(
        update_fields=[
            "total_amount",
            "updated_at",
        ]
    )

    return total


# =========================================================
# CREATE SAMPLE
# =========================================================

@transaction.atomic
def create_sample(order_item, user=None):
    """
    Creates a sample for a lab order item.
    """

    if order_item.status == LabOrderItem.Status.CANCELLED:
        raise ValidationError(
            "Cannot collect sample for a cancelled item."
        )

    if not order_item.test_id:
        raise ValidationError(
            "Sample can only be created for a test item."
        )

    existing_sample = (
        LabSample.objects
        .filter(order_item=order_item)
        .exclude(status=LabSample.Status.REJECTED)
        .first()
    )

    if existing_sample:
        return existing_sample

    sample = LabSample.objects.create(
        order=order_item.order,
        order_item=order_item,
        sample_type=order_item.test.sample_type,
        status=LabSample.Status.PENDING,
    )

    return sample


# =========================================================
# COLLECT SAMPLE
# =========================================================

@transaction.atomic
def collect_sample(sample, user):
    """
    Marks a sample as collected.
    """

    if sample.status in [
        LabSample.Status.REJECTED,
        LabSample.Status.PROCESSED,
    ]:
        raise ValidationError(
            "This sample cannot be collected."
        )

    sample.status = LabSample.Status.COLLECTED
    sample.collected_at = timezone.now()
    sample.collected_by = user

    sample.save(
        update_fields=[
            "status",
            "collected_at",
            "collected_by",
            "updated_at",
        ]
    )

    order_item = sample.order_item

    order_item.status = LabOrderItem.Status.SAMPLE_COLLECTED
    order_item.save(
        update_fields=[
            "status",
        ]
    )

    update_order_status(sample.order)

    return sample


# =========================================================
# RECEIVE SAMPLE
# =========================================================

@transaction.atomic
def receive_sample(sample, user):
    """
    Marks collected sample as received in laboratory.
    """

    if sample.status != LabSample.Status.COLLECTED:
        raise ValidationError(
            "Only collected samples can be received."
        )

    sample.status = LabSample.Status.RECEIVED
    sample.received_at = timezone.now()
    sample.received_by = user

    sample.save(
        update_fields=[
            "status",
            "received_at",
            "received_by",
            "updated_at",
        ]
    )

    sample.order_item.status = LabOrderItem.Status.PROCESSING

    sample.order_item.save(
        update_fields=[
            "status",
        ]
    )

    update_order_status(sample.order)

    return sample


# =========================================================
# CREATE RESULT
# =========================================================

@transaction.atomic
def create_result(
    sample,
    result_value="",
    numeric_value=None,
    user=None,
    remarks="",
):
    """
    Creates or updates a result for the sample's test.
    """

    if sample.status not in [
        LabSample.Status.RECEIVED,
        LabSample.Status.PROCESSED,
    ]:
        raise ValidationError(
            "Sample must be received before entering result."
        )

    order_item = sample.order_item

    if not order_item.test_id:
        raise ValidationError(
            "This order item does not have a test."
        )

    test = order_item.test

    result, created = LabResult.objects.get_or_create(
        sample=sample,
        order_item=order_item,
        test=test,
        defaults={
            "result_value": result_value,
            "numeric_value": numeric_value,
            "unit": test.unit,
            "status": LabResult.ResultStatus.ENTERED,
            "entered_by": user,
            "entered_at": timezone.now(),
            "remarks": remarks,
        },
    )

    if not created:
        result.result_value = result_value
        result.numeric_value = numeric_value
        result.unit = test.unit
        result.status = LabResult.ResultStatus.ENTERED
        result.entered_by = user
        result.entered_at = timezone.now()
        result.remarks = remarks

    evaluate_result(result)

    result.save()

    order_item.status = LabOrderItem.Status.COMPLETED

    order_item.save(
        update_fields=[
            "status",
        ]
    )

    sample.status = LabSample.Status.PROCESSED
    sample.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    update_order_status(sample.order)

    return result


# =========================================================
# RESULT EVALUATION
# =========================================================

def evaluate_result(result):
    """
    Automatically evaluates numeric result against
    the applicable reference range.
    """

    result.is_abnormal = False
    result.is_critical = False

    if result.numeric_value is None:
        return result

    patient = result.sample.order.patient

    gender = getattr(patient, "gender", None)

    if gender:
        gender_value = str(gender).upper()
    else:
        gender_value = "ALL"

    age = calculate_patient_age(patient)

    reference_ranges = (
        LabReferenceRange.objects
        .filter(
            test=result.test,
            is_active=True,
        )
        .order_by(
            "age_min",
            "id",
        )
    )

    selected_range = None

    for ref in reference_ranges:

        if ref.gender != LabReferenceRange.Gender.ALL:
            if ref.gender != gender_value:
                continue

        if age < ref.age_min:
            continue

        if ref.age_max is not None and age > ref.age_max:
            continue

        selected_range = ref
        break

    if not selected_range:
        return result

    # -----------------------------------------
    # Store reference range as readable text
    # -----------------------------------------

    if (
        selected_range.normal_min is not None
        and selected_range.normal_max is not None
    ):
        result.reference_range = (
            f"{selected_range.normal_min}"
            f" - "
            f"{selected_range.normal_max}"
        )

    elif selected_range.normal_text:
        result.reference_range = selected_range.normal_text

    # -----------------------------------------
    # Normal range check
    # -----------------------------------------

    if (
        selected_range.normal_min is not None
        and result.numeric_value < selected_range.normal_min
    ):
        result.is_abnormal = True

    if (
        selected_range.normal_max is not None
        and result.numeric_value > selected_range.normal_max
    ):
        result.is_abnormal = True

    # -----------------------------------------
    # Critical range check
    # -----------------------------------------

    if (
        selected_range.critical_low is not None
        and result.numeric_value <= selected_range.critical_low
    ):
        result.is_critical = True
        result.is_abnormal = True

    if (
        selected_range.critical_high is not None
        and result.numeric_value >= selected_range.critical_high
    ):
        result.is_critical = True
        result.is_abnormal = True

    if selected_range.interpretation:
        result.interpretation = selected_range.interpretation

    return result


# =========================================================
# PATIENT AGE
# =========================================================

def calculate_patient_age(patient):
    """
    Returns patient's age in years.
    """

    if not patient.dob:
        return Decimal("0")

    today = timezone.localdate()

    age = (
        today.year
        - patient.dob.year
    )

    if (
        (today.month, today.day)
        < (
            patient.dob.month,
            patient.dob.day,
        )
    ):
        age -= 1

    return Decimal(str(age))

# =========================================================
# VERIFY RESULT
# =========================================================

@transaction.atomic
def verify_result(result, user):
    """
    Verifies a laboratory result.
    """

    if result.status not in [
        LabResult.ResultStatus.ENTERED,
        LabResult.ResultStatus.AMENDED,
    ]:
        raise ValidationError(
            "Only entered or amended results can be verified."
        )

    result.status = LabResult.ResultStatus.VERIFIED
    result.verified_by = user
    result.verified_at = timezone.now()

    result.save(
        update_fields=[
            "status",
            "verified_by",
            "verified_at",
            "updated_at",
        ]
    )

    update_order_status(result.sample.order)

    return result


# =========================================================
# ORDER STATUS
# =========================================================

def update_order_status(order):
    """
    Automatically updates overall Lab Order status.
    """

    items = list(order.items.all())

    if not items:
        return order

    active_items = [
        item
        for item in items
        if item.status != LabOrderItem.Status.CANCELLED
    ]

    if not active_items:
        order.status = LabOrder.Status.CANCELLED

    elif all(
        item.status == LabOrderItem.Status.COMPLETED
        for item in active_items
    ):
        order.status = LabOrder.Status.COMPLETED

    elif any(
        item.status == LabOrderItem.Status.COMPLETED
        for item in active_items
    ):
        order.status = LabOrder.Status.PARTIAL

    elif any(
        item.status == LabOrderItem.Status.PROCESSING
        for item in active_items
    ):
        order.status = LabOrder.Status.PROCESSING

    elif any(
        item.status == LabOrderItem.Status.SAMPLE_COLLECTED
        for item in active_items
    ):
        order.status = LabOrder.Status.SAMPLE_COLLECTED

    elif any(
        item.status == LabOrderItem.Status.SAMPLE_PENDING
        for item in active_items
    ):
        order.status = LabOrder.Status.SAMPLE_PENDING

    else:
        order.status = LabOrder.Status.ORDERED

    order.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    return order


# =========================================================
# CREATE LAB REPORT
# =========================================================

@transaction.atomic
def create_lab_report(order, user=None):
    """
    Creates a Lab Report after all required results
    have been verified.
    """

    if order.status != LabOrder.Status.COMPLETED:
        raise ValidationError(
            "Lab report can only be created after "
            "all order items are completed."
        )

    items = (
        order.items
        .filter(
            status=LabOrderItem.Status.COMPLETED
        )
    )

    if not items.exists():
        raise ValidationError(
            "No completed lab tests found."
        )

    for item in items:

        if not item.test_id:
            continue

        result = (
            LabResult.objects
            .filter(
                order_item=item,
                status=LabResult.ResultStatus.VERIFIED,
            )
            .first()
        )

        if not result:
            raise ValidationError(
                f"Result for '{item.test.name}' "
                "has not been verified."
            )

    report, created = LabReport.objects.get_or_create(
        order=order,
        defaults={
            "patient": order.patient,
            "status": LabReport.Status.READY,
            "prepared_by": user,
        },
    )

    if not created:
        if report.status == LabReport.Status.CANCELLED:
            raise ValidationError(
                "Cancelled report cannot be reused."
            )

    return report


# =========================================================
# VERIFY COMPLETE REPORT
# =========================================================

@transaction.atomic
def verify_lab_report(report, user):
    """
    Verifies a complete lab report.
    """

    if report.status not in [
        LabReport.Status.READY,
        LabReport.Status.DRAFT,
    ]:
        raise ValidationError(
            "This report cannot be verified in its current status."
        )

    report.status = LabReport.Status.VERIFIED
    report.verified_by = user
    report.verified_at = timezone.now()

    report.save(
        update_fields=[
            "status",
            "verified_by",
            "verified_at",
            "updated_at",
        ]
    )

    return report


# =========================================================
# FINALIZE REPORT
# =========================================================

@transaction.atomic
def finalize_lab_report(report, user):
    """
    Finalizes a verified report.
    """

    if report.status != LabReport.Status.VERIFIED:
        raise ValidationError(
            "Only verified reports can be finalized."
        )

    report.status = LabReport.Status.FINAL
    report.finalized_by = user
    report.finalized_at = timezone.now()

    report.save(
        update_fields=[
            "status",
            "finalized_by",
            "finalized_at",
            "updated_at",
        ]
    )

    return report