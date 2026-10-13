"""Glue between the portal screens and the apps' business services.

* ``create_*`` functions save a new record through the app's service, so the
  same rules (bed availability, stock, roles ...) apply as everywhere else.
* ``*_guard`` functions lock records that must no longer be edited.
* ``act_*`` functions are the one-click row buttons.
* ``after_*`` functions keep related records in step (visit status, totals,
  opening stock ...).
"""

from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone

from appointments.models import Appointment
from ipd import services as ipd_services
from ipd.models import IPDMedicationOrder
from laboratory import services as lab_services
from laboratory.models import (
    LabOrder,
    LabOrderItem,
    LabReport,
    LabResult,
    LabSample,
)
from opd.models import OPDFollowUp, OPDVisit
from pharmacy import services as pharmacy_services
from pharmacy.models import (
    MedicineBatch,
    PharmacyDispensing,
    PharmacyDispensingItem,
    PharmacyPurchase,
    PharmacyPurchaseReturn,
    Prescription,
    StockTransaction,
)

from .forms import PortalForm


def _text(value):
    return value or ""


# ---------------------------------------------------------------------------
# Small forms asked by some buttons
# ---------------------------------------------------------------------------

class ReasonForm(forms.Form):
    reason = forms.CharField(
        label="Reason",
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class StockAdjustmentForm(PortalForm):
    """Manual stock correction: a stock take, expired or damaged stock."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        kind = self.fields["transaction_type"]
        kind.choices = [
            (StockTransaction.TransactionType.ADJUSTMENT,
             "Adjustment (stock count correction)"),
            (StockTransaction.TransactionType.EXPIRED, "Expired - remove"),
            (StockTransaction.TransactionType.DAMAGED, "Damaged - remove"),
        ]

        batch = self.fields["medicine_batch"]
        batch.queryset = (
            MedicineBatch.objects.select_related("medicine")
            .order_by("medicine__name", "expiry_date")
        )
        batch.label_from_instance = lambda b: (
            f"{b.medicine.name} · batch {b.batch_number}"
            f" · exp {b.expiry_date:%d %b %Y} · {b.available_quantity} in stock"
        )

        self.fields["quantity"].help_text = (
            "Adjustment: + adds stock, - removes stock. "
            "Expired / damaged: enter how many to remove."
        )
        self.fields["notes"].required = True
        self.fields["notes"].label = "Reason"

    def clean(self):
        cleaned = super().clean()

        quantity = cleaned.get("quantity")
        kind = cleaned.get("transaction_type")

        if quantity is not None:
            if quantity == 0:
                self.add_error("quantity", "Quantity cannot be zero.")
            elif (
                kind != StockTransaction.TransactionType.ADJUSTMENT
                and quantity < 0
            ):
                self.add_error(
                    "quantity", "Enter a positive number of units to remove."
                )

        return cleaned


# ---------------------------------------------------------------------------
# IPD: save through the services
# ---------------------------------------------------------------------------

def create_bed_transfer(form, request):
    data = form.cleaned_data
    return ipd_services.transfer_patient_bed(
        admission=data["admission"],
        to_ward=form.instance.to_ward,
        to_room=form.instance.to_room,
        to_bed=data["to_bed"],
        user=request.user,
        reason=_text(data.get("reason")),
        notes=_text(data.get("notes")),
    )


def create_doctor_assignment(form, request):
    data = form.cleaned_data
    return ipd_services.assign_ipd_doctor(
        data["admission"],
        data["doctor"],
        user=request.user,
        role=data["role"],
        reason=_text(data.get("reason")),
        notes=_text(data.get("notes")),
    )


def create_doctor_note(form, request):
    data = form.cleaned_data
    return ipd_services.create_ipd_doctor_note(
        data["admission"],
        data["doctor"],
        data["clinical_note"],
        note_type=_text(data.get("note_type")) or "Progress Note",
    )


VITAL_FIELDS = (
    "temperature", "systolic_bp", "diastolic_bp", "pulse", "respiratory_rate",
    "spo2", "weight", "height", "blood_glucose", "pain_score", "nursing_notes",
)


def create_ipd_vitals(form, request):
    data = form.cleaned_data
    vitals = {name: data.get(name) for name in VITAL_FIELDS}
    vitals["nursing_notes"] = _text(vitals["nursing_notes"])
    return ipd_services.record_ipd_vitals(
        data["admission"], request.user, **vitals
    )


def create_nursing_note(form, request):
    data = form.cleaned_data
    return ipd_services.create_ipd_nursing_note(
        data["admission"],
        request.user,
        data["notes"],
        note_type=data["note_type"],
        intake_ml=data.get("intake_ml"),
        output_ml=data.get("output_ml"),
    )


def create_medication_order(form, request):
    data = form.cleaned_data
    return ipd_services.create_ipd_medication_order(
        admission=data["admission"],
        medicine=data["medicine"],
        prescribed_by=data["prescribed_by"],
        dose=data["dose"],
        frequency=data["frequency"],
        start_date=data["start_date"],
        end_date=data["end_date"],
        quantity=data.get("quantity") or 1,
        duration_days=data.get("duration_days") or 1,
        route=data["route"],
        instructions=_text(data.get("instructions")),
    )


def create_medication_administration(form, request):
    """Record a dose and, when it was given, take it out of stock."""
    data = form.cleaned_data
    status = data["status"]

    record = ipd_services.record_ipd_medication_administration(
        data["medication_order"],
        request.user,
        status,
        data["scheduled_at"],
        quantity_given=data.get("quantity_given") or 0,
        medicine_batch=data.get("medicine_batch"),
        reason=_text(data.get("reason")),
        notes=_text(data.get("notes")),
    )

    if status == record.Status.GIVEN:
        remove_stock(
            record.medicine_batch,
            record.quantity_given,
            StockTransaction.TransactionType.DISPENSE,
            reference=record.admission.admission_number,
            notes=f"IPD dose given to {record.patient.full_name}",
            user=request.user,
        )

    return record


# ---------------------------------------------------------------------------
# Stock helpers
# ---------------------------------------------------------------------------

def remove_stock(batch, quantity, kind, reference, notes, user):
    """Take ``quantity`` out of a batch and write the ledger line."""
    quantity = Decimal(quantity)

    batch = MedicineBatch.objects.select_for_update().get(pk=batch.pk)

    if quantity > batch.available_quantity:
        raise ValidationError(
            f"Only {batch.available_quantity} of batch "
            f"{batch.batch_number} left."
        )

    MedicineBatch.objects.filter(pk=batch.pk).update(
        available_quantity=batch.available_quantity - quantity,
        updated_at=timezone.now(),
    )

    return StockTransaction.objects.create(
        medicine_batch=batch,
        transaction_type=kind,
        quantity=-quantity,
        reference_number=reference,
        notes=notes,
        created_by=user,
    )


def create_stock_adjustment(form, request):
    data = form.cleaned_data
    kind = data["transaction_type"]
    quantity = data["quantity"]

    batch = MedicineBatch.objects.select_for_update().get(
        pk=data["medicine_batch"].pk
    )

    delta = quantity if kind == StockTransaction.TransactionType.ADJUSTMENT else -quantity
    new_available = batch.available_quantity + delta

    if new_available < 0:
        raise ValidationError(
            f"Only {batch.available_quantity} in stock, so {abs(delta)} "
            "cannot be removed."
        )

    changes = {"available_quantity": new_available, "updated_at": timezone.now()}

    # Adding stock by count correction also raises the received quantity so
    # "available" never exceeds "received".
    if new_available > batch.quantity_received:
        changes["quantity_received"] = new_available

    MedicineBatch.objects.filter(pk=batch.pk).update(**changes)

    return StockTransaction.objects.create(
        medicine_batch=batch,
        transaction_type=kind,
        quantity=delta,
        reference_number="MANUAL",
        notes=data["notes"],
        created_by=request.user,
    )


# ---------------------------------------------------------------------------
# Laboratory: save through the services
# ---------------------------------------------------------------------------

def create_lab_sample(form, request):
    data = form.cleaned_data
    item = data["order_item"]

    sample = lab_services.create_sample(item, request.user)

    changed = ["updated_at"]

    sample_type = data.get("sample_type")
    if sample_type and sample.sample_type_id != sample_type.pk:
        sample.sample_type = sample_type
        changed.append("sample_type")

    if data.get("remarks"):
        sample.remarks = data["remarks"]
        changed.append("remarks")

    sample.save(update_fields=changed)

    if item.status == LabOrderItem.Status.ORDERED:
        item.status = LabOrderItem.Status.SAMPLE_PENDING
        item.save(update_fields=["status"])

    lab_services.update_order_status(item.order)

    return sample


def save_lab_result(form, request):
    data = form.cleaned_data
    sample = data["sample"]

    existing = LabResult.objects.filter(
        sample=sample, order_item=sample.order_item
    ).first()

    if existing and existing.status == LabResult.ResultStatus.VERIFIED:
        raise ValidationError(
            "This result is already verified and can no longer be changed."
        )

    return lab_services.create_result(
        sample,
        result_value=_text(data.get("result_value")),
        numeric_value=data.get("numeric_value"),
        user=request.user,
        remarks=_text(data.get("remarks")),
    )


def create_lab_report(form, request):
    data = form.cleaned_data
    report = lab_services.create_lab_report(data["order"], request.user)

    report.clinical_summary = _text(data.get("clinical_summary"))
    report.report_notes = _text(data.get("report_notes"))
    report.save(update_fields=["clinical_summary", "report_notes", "updated_at"])

    return report


# ---------------------------------------------------------------------------
# Hooks after a normal save: (instance, form, request, created)
# ---------------------------------------------------------------------------

def after_lab_order(order, form, request, created):
    lab_services.update_order_total(order)

    package = form.cleaned_data.get("package")
    if package is not None:
        lab_services.add_package_to_order(order, package)

    if order.status == LabOrder.Status.DRAFT and order.items.exists():
        LabOrder.objects.filter(pk=order.pk).update(
            status=LabOrder.Status.ORDERED
        )
    elif order.status not in (LabOrder.Status.DRAFT, LabOrder.Status.CANCELLED):
        lab_services.update_order_status(order)


def after_vitals(vital, form, request, created):
    if created:
        OPDVisit.objects.filter(
            pk=vital.opd_visit_id, status=OPDVisit.Status.WAITING
        ).update(status=OPDVisit.Status.VITALS_COMPLETED)


def after_consultation(consultation, form, request, created):
    visit = consultation.opd_visit

    if consultation.consultation_end:
        new_status = OPDVisit.Status.CONSULTATION_COMPLETED
        allowed = (
            OPDVisit.Status.WAITING,
            OPDVisit.Status.VITALS_COMPLETED,
            OPDVisit.Status.IN_CONSULTATION,
        )
    else:
        new_status = OPDVisit.Status.IN_CONSULTATION
        allowed = (OPDVisit.Status.WAITING, OPDVisit.Status.VITALS_COMPLETED)

    OPDVisit.objects.filter(pk=visit.pk, status__in=allowed).update(
        status=new_status
    )

    Appointment.objects.filter(
        pk=visit.appointment_id,
        status__in=(
            Appointment.Status.BOOKED,
            Appointment.Status.CONFIRMED,
            Appointment.Status.CHECKED_IN,
        ),
    ).update(status=Appointment.Status.IN_CONSULTATION)


def after_batch(batch, form, request, created):
    """A batch added by hand is opening stock; record it in the ledger."""
    if created and batch.available_quantity > 0:
        StockTransaction.objects.create(
            medicine_batch=batch,
            transaction_type=StockTransaction.TransactionType.OPENING,
            quantity=batch.available_quantity,
            reference_number="OPENING",
            notes="Opening stock added from the portal",
            created_by=request.user,
        )


def before_prescription(prescription, request):
    """Pre-fill the diagnosis from the visit's diagnoses when left blank."""
    if prescription.diagnosis_summary or not prescription.opd_visit_id:
        return

    names = list(
        prescription.opd_visit.diagnoses.order_by("id")
        .values_list("diagnosis", flat=True)
    )
    if names:
        prescription.diagnosis_summary = "; ".join(names)


def after_dispensing(dispensing, form, request, created):
    """Fill a new dispensing with the prescription's items, earliest-expiry
    batches first, so the pharmacist only has to check and press Dispense."""
    if not created:
        return

    short = []
    made = 0

    for item in (
        dispensing.prescription.items
        .select_related("medicine")
        .filter(is_discontinued=False)
    ):
        done = (
            PharmacyDispensingItem.objects
            .filter(prescription_item=item, stock_applied=True)
            .aggregate(total=Sum("quantity_dispensed"))["total"]
            or Decimal("0")
        )
        remaining = item.quantity_prescribed - done

        if remaining <= 0:
            continue

        batches = list(
            MedicineBatch.objects
            .select_for_update()
            .filter(
                medicine=item.medicine,
                is_active=True,
                available_quantity__gt=0,
                expiry_date__gte=timezone.localdate(),
            )
            .order_by("expiry_date", "id")
        )

        for batch in batches:
            if remaining <= 0:
                break

            take = min(batch.available_quantity, remaining)

            PharmacyDispensingItem(
                dispensing=dispensing,
                prescription_item=item,
                medicine_batch=batch,
                quantity_dispensed=take,
                selling_price=batch.selling_price,
                gst_rate=item.medicine.gst_rate,
            ).save()

            remaining -= take
            made += 1

        if remaining > 0:
            short.append(f"{item.medicine.name} (short by {remaining})")

    if made == 0:
        raise ValidationError(
            "Nothing can be dispensed: every item is already dispensed "
            "or out of stock."
        )

    if short:
        messages.warning(
            request, "Not enough stock for: " + ", ".join(short) + "."
        )


# ---------------------------------------------------------------------------
# Guards: return a message to block "change" / "delete", or None
# ---------------------------------------------------------------------------

def _locked_unless(statuses, label):
    allowed = {getattr(status, "value", status) for status in statuses}

    def guard(obj, request, action):
        if obj.status not in allowed:
            verb = "edited" if action == "change" else "deleted"
            return (
                f"This {label} is {obj.get_status_display().lower()} "
                f"and can no longer be {verb}."
            )
        return None
    return guard


appointment_guard = _locked_unless(
    {
        Appointment.Status.BOOKED,
        Appointment.Status.CONFIRMED,
        Appointment.Status.CHECKED_IN,
        Appointment.Status.IN_CONSULTATION,
    },
    "appointment",
)

purchase_guard = _locked_unless({PharmacyPurchase.Status.DRAFT}, "purchase")
purchase_return_guard = _locked_unless(
    {PharmacyPurchaseReturn.Status.DRAFT}, "return"
)
dispensing_guard = _locked_unless(
    {
        PharmacyDispensing.Status.PENDING,
        PharmacyDispensing.Status.PARTIALLY_DISPENSED,
    },
    "dispensing",
)
prescription_guard = _locked_unless(
    {Prescription.Status.DRAFT, Prescription.Status.ACTIVE}, "prescription"
)
lab_order_guard = _locked_unless(
    {
        LabOrder.Status.DRAFT,
        LabOrder.Status.ORDERED,
        LabOrder.Status.SAMPLE_PENDING,
        LabOrder.Status.SAMPLE_COLLECTED,
        LabOrder.Status.PROCESSING,
        LabOrder.Status.PARTIAL,
    },
    "lab order",
)
lab_result_guard = _locked_unless(
    {LabResult.ResultStatus.PENDING, LabResult.ResultStatus.ENTERED},
    "result",
)
lab_report_guard = _locked_unless(
    {LabReport.Status.DRAFT, LabReport.Status.READY, LabReport.Status.VERIFIED},
    "report",
)


def opd_guard(obj, request, action):
    if obj.status in (OPDVisit.Status.COMPLETED, OPDVisit.Status.CANCELLED):
        return f"This visit is {obj.get_status_display().lower()} and is locked."
    return None


def admission_guard(obj, request, action):
    if action == "delete":
        if obj.status != obj.Status.CANCELLED:
            return (
                "Only a cancelled admission can be deleted. Cancel it first "
                "(that also frees the bed)."
            )
    elif obj.status in (obj.Status.DISCHARGED, obj.Status.CANCELLED):
        return f"This admission is {obj.get_status_display().lower()} and is locked."
    return None


# ---------------------------------------------------------------------------
# Row buttons
# ---------------------------------------------------------------------------

def _now():
    return timezone.now()


def act_check_in(appt, request):
    if appt.appointment_date != timezone.localdate():
        raise ValidationError(
            f"Check-in is only possible on the appointment day "
            f"({appt.appointment_date:%d %b %Y})."
        )
    Appointment.objects.filter(pk=appt.pk).update(
        status=Appointment.Status.CHECKED_IN,
        checked_in_at=_now(),
        updated_at=_now(),
    )
    return f"{appt.patient.full_name} checked in (token {appt.token_number})."


def act_cancel_appointment(appt, request, data):
    Appointment.objects.filter(pk=appt.pk).update(
        status=Appointment.Status.CANCELLED,
        cancelled_at=_now(),
        cancellation_reason=data["reason"],
        updated_at=_now(),
    )
    return f"Appointment {appt.appointment_number} cancelled."


def act_no_show(appt, request):
    Appointment.objects.filter(pk=appt.pk).update(
        status=Appointment.Status.NO_SHOW, updated_at=_now()
    )
    return f"{appt.patient.full_name} marked as no-show."


def act_start_visit(appt, request):
    visit = OPDVisit.objects.create(
        appointment=appt,
        patient=appt.patient,
        doctor=appt.doctor,
        department=appt.department,
        chief_complaint=appt.chief_complaint,
        created_by=request.user,
    )
    return f"OPD visit {visit.visit_number} created. Next: record vitals."


def act_complete_visit(visit, request):
    OPDVisit.objects.filter(pk=visit.pk).update(
        status=OPDVisit.Status.COMPLETED,
        completed_at=_now(),
        updated_at=_now(),
    )
    Appointment.objects.filter(pk=visit.appointment_id).update(
        status=Appointment.Status.COMPLETED,
        completed_at=_now(),
        updated_at=_now(),
    )
    return f"Visit {visit.visit_number} completed."


def act_discharge(admission, request, data):
    ipd_services.discharge_ipd_patient(
        admission,
        request.user,
        data["final_diagnosis"],
        data["treatment_summary"],
        data["discharge_instructions"],
        data["discharge_disposition"],
    )
    return f"{admission.patient.full_name} discharged. The bed is free again."


def act_end_assignment(assignment, request, data):
    ipd_services.remove_ipd_doctor(
        assignment, user=request.user, reason=data["reason"]
    )
    return "Doctor assignment ended."


def act_stop_order(order, request):
    IPDMedicationOrder.objects.filter(pk=order.pk).update(
        status=IPDMedicationOrder.Status.COMPLETED, updated_at=_now()
    )
    return "Medication order stopped."


def act_create_samples(order, request):
    items = list(
        order.items.select_related("test")
        .filter(test__isnull=False)
        .exclude(status=LabOrderItem.Status.CANCELLED)
    )
    if not items:
        raise ValidationError("This order has no tests.")

    created = 0
    for item in items:
        sample = lab_services.create_sample(item, request.user)
        created += 1
        if item.status == LabOrderItem.Status.ORDERED:
            item.status = LabOrderItem.Status.SAMPLE_PENDING
            item.save(update_fields=["status"])

    lab_services.update_order_status(order)
    return f"{created} sample(s) ready for collection."


def act_cancel_lab_order(order, request, data):
    if order.samples.exclude(status=LabSample.Status.REJECTED).exists():
        raise ValidationError(
            "Samples were already taken for this order, so it cannot be "
            "cancelled."
        )
    order.items.update(status=LabOrderItem.Status.CANCELLED)
    LabOrder.objects.filter(pk=order.pk).update(
        status=LabOrder.Status.CANCELLED,
        clinical_notes=(
            f"{order.clinical_notes}\nCancelled: {data['reason']}".strip()
        ),
        updated_at=_now(),
    )
    return f"Order {order.order_number} cancelled."


def act_create_report_from_order(order, request):
    report = lab_services.create_lab_report(order, request.user)
    return f"Report {report.report_number} created."


def act_collect_sample(sample, request):
    lab_services.collect_sample(sample, request.user)
    return f"Sample {sample.sample_number} collected."


def act_receive_sample(sample, request):
    lab_services.receive_sample(sample, request.user)
    return f"Sample {sample.sample_number} received in the lab."


def act_reject_sample(sample, request, data):
    LabSample.objects.filter(pk=sample.pk).update(
        status=LabSample.Status.REJECTED,
        rejection_reason=data["reason"],
        updated_at=_now(),
    )
    LabOrderItem.objects.filter(pk=sample.order_item_id).update(
        status=LabOrderItem.Status.SAMPLE_PENDING
    )
    lab_services.update_order_status(sample.order)
    return f"Sample {sample.sample_number} rejected. Create a new sample to recollect."


def act_verify_result(result, request):
    lab_services.verify_result(result, request.user)
    return "Result verified."


def act_verify_report(report, request):
    lab_services.verify_lab_report(report, request.user)
    return f"Report {report.report_number} verified."


def act_finalize_report(report, request):
    lab_services.finalize_lab_report(report, request.user)
    return f"Report {report.report_number} is final and can be printed."


def act_receive_purchase(purchase, request):
    purchase = PharmacyPurchase.objects.select_for_update().get(pk=purchase.pk)

    if purchase.status != PharmacyPurchase.Status.DRAFT:
        raise ValidationError("Only a draft purchase can be received.")

    if not purchase.items.exists():
        raise ValidationError("Add at least one item before receiving stock.")

    purchase.status = PharmacyPurchase.Status.RECEIVED
    purchase.received_by = request.user
    purchase.save()

    pharmacy_services.process_pharmacy_purchase(purchase, request.user)
    return f"Stock received for {purchase.grn_number}."


def act_cancel_purchase(purchase, request):
    PharmacyPurchase.objects.filter(pk=purchase.pk).update(
        status=PharmacyPurchase.Status.CANCELLED, updated_at=_now()
    )
    return f"{purchase.grn_number} cancelled."


def act_mark_paid(purchase, request):
    PharmacyPurchase.objects.filter(pk=purchase.pk).update(
        payment_status=PharmacyPurchase.PaymentStatus.PAID, updated_at=_now()
    )
    return f"{purchase.grn_number} marked as paid."


def act_process_return(purchase_return, request):
    if not purchase_return.items.exists():
        raise ValidationError("Add at least one item to return.")

    pharmacy_services.process_pharmacy_purchase_return(
        purchase_return, request.user
    )
    return f"{purchase_return.return_number} processed; stock reduced."


def act_cancel_return(purchase_return, request):
    PharmacyPurchaseReturn.objects.filter(pk=purchase_return.pk).update(
        status=PharmacyPurchaseReturn.Status.CANCELLED, updated_at=_now()
    )
    return f"{purchase_return.return_number} cancelled."


def act_cancel_prescription(prescription, request):
    Prescription.objects.filter(pk=prescription.pk).update(
        status=Prescription.Status.CANCELLED, updated_at=_now()
    )
    return f"{prescription.prescription_number} cancelled."


def act_dispense(dispensing, request):
    if not dispensing.items.exists():
        raise ValidationError("There is nothing to dispense.")

    PharmacyDispensing.objects.filter(pk=dispensing.pk).update(
        dispensed_by=request.user
    )
    pharmacy_services.process_pharmacy_dispensing(dispensing)
    return f"{dispensing.dispensing_number} dispensed; stock updated."


def act_cancel_dispensing(dispensing, request):
    if dispensing.items.filter(stock_applied=True).exists():
        raise ValidationError(
            "Part of this dispensing is already given, so it cannot be cancelled."
        )
    PharmacyDispensing.objects.filter(pk=dispensing.pk).update(
        status=PharmacyDispensing.Status.CANCELLED, updated_at=_now()
    )
    return f"{dispensing.dispensing_number} cancelled."


def act_followup_done(followup, request):
    OPDFollowUp.objects.filter(pk=followup.pk).update(
        status=OPDFollowUp.Status.COMPLETED, updated_at=_now()
    )
    return "Follow-up marked as done."


def act_followup_cancel(followup, request):
    OPDFollowUp.objects.filter(pk=followup.pk).update(
        status=OPDFollowUp.Status.CANCELLED, updated_at=_now()
    )
    return "Follow-up cancelled."
