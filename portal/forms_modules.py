"""Forms for the clinical, laboratory and pharmacy sections of the portal.

Rules these forms follow, so data stays accurate with little typing:

* only records that make sense are offered in drop-downs (active records,
  open visits, received samples, available beds ...);
* patient / doctor / order and similar details are copied from the parent
  record instead of being typed again;
* quantities and statuses that the system manages are not editable.
"""

from datetime import timedelta
from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone

from hospitals.models import Bed
from ipd.models import IPDAdmission, IPDMedicationOrder
from laboratory.models import (
    LabOrder,
    LabOrderItem,
    LabSample,
)
from opd.models import OPDVisit
from pharmacy.models import (
    MedicineBatch,
    PharmacyPurchase,
    Prescription,
    PrescriptionItem,
)

from .forms import PortalForm, portal_formfield


ACTIVE_ADMISSION = ("ADMITTED", "ON_HOLD")
OPEN_VISIT = (
    "WAITING", "VITALS_COMPLETED", "IN_CONSULTATION", "CONSULTATION_COMPLETED",
)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def visit_label(visit):
    return f"{visit.visit_number} · {visit.patient.full_name}"


def admission_label(admission):
    return f"{admission.admission_number} · {admission.patient.full_name}"


def bed_label(bed):
    return (
        f"Bed {bed.bed_number} · Room {bed.room.room_number}"
        f" · {bed.room.ward.name}"
    )


def batch_label(batch):
    return (
        f"{batch.medicine.name} · batch {batch.batch_number}"
        f" · exp {batch.expiry_date:%d %b %Y} · {batch.available_quantity} left"
    )


# ---------------------------------------------------------------------------
# Rows of an inline table
# ---------------------------------------------------------------------------

class LineForm(forms.ModelForm):
    """A row in an inline table. Subclasses may define ``restrict(parent)``
    to narrow drop-downs once the parent record is known."""

    locked = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        PortalForm._limit_to_active(self)


class ParentAwareFormSet(forms.BaseInlineFormSet):

    def _construct_form(self, i, **kwargs):
        form = super()._construct_form(i, **kwargs)

        restrict = getattr(form, "restrict", None)
        if restrict is not None:
            restrict(self.instance)

        return form

    def _should_delete_form(self, form):
        if getattr(form, "locked", False):
            return False
        return super()._should_delete_form(form)


def line_formset(parent, child, fields, form=None):
    """Return ``factory(extra)`` building an inline formset class."""

    def factory(extra):
        return forms.inlineformset_factory(
            parent,
            child,
            form=form or LineForm,
            formset=ParentAwareFormSet,
            fields=fields,
            extra=extra,
            can_delete=True,
            formfield_callback=portal_formfield,
        )

    return factory


# ---------------------------------------------------------------------------
# OPD
# ---------------------------------------------------------------------------

class OPDChildForm(PortalForm):
    """Forms that hang off an OPD visit."""

    visit_statuses = OPEN_VISIT
    without_reverse = None      # e.g. "vitals" -> only visits that have none

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        field = self.fields["opd_visit"]
        current = self.instance.opd_visit_id

        queryset = OPDVisit.objects.select_related("patient")
        queryset = queryset.filter(
            Q(status__in=self.visit_statuses) | Q(pk=current)
        )

        if self.without_reverse:
            queryset = queryset.filter(
                Q(**{f"{self.without_reverse}__isnull": True}) | Q(pk=current)
            )

        field.queryset = queryset.order_by("-visit_date", "-id")
        field.label_from_instance = visit_label

        if self.instance.pk:
            field.disabled = True


class PatientVitalForm(OPDChildForm):
    without_reverse = "vitals"


class OPDConsultationForm(OPDChildForm):
    without_reverse = "consultation"


class OPDDiagnosisForm(OPDChildForm):
    derive = {"diagnosed_by": "opd_visit.doctor"}


class OPDFollowUpForm(OPDChildForm):
    derive = {
        "patient": "opd_visit.patient",
        "doctor": "opd_visit.doctor",
    }


# ---------------------------------------------------------------------------
# IPD
# ---------------------------------------------------------------------------

class AdmissionChildForm(PortalForm):
    """Forms that hang off an active IPD admission."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        field = self.fields.get("admission")
        if field is None:
            return

        field.queryset = (
            IPDAdmission.objects.select_related("patient")
            .filter(
                Q(status__in=ACTIVE_ADMISSION)
                | Q(pk=self.instance.admission_id)
            )
            .order_by("-admission_date")
        )
        field.label_from_instance = admission_label

        if self.instance.pk:
            field.disabled = True


class IPDBedTransferForm(AdmissionChildForm):
    derive = {
        "patient": "admission.patient",
        "from_ward": "admission.ward",
        "from_room": "admission.room",
        "from_bed": "admission.bed",
        "to_room": "to_bed.room",
        "to_ward": "to_bed.room.ward",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        field = self.fields["to_bed"]
        field.label = "Move to bed"
        field.queryset = (
            Bed.objects.select_related("room__ward")
            .filter(is_active=True, status=Bed.Status.AVAILABLE)
            .order_by("room__ward__name", "room__room_number", "bed_number")
        )
        field.label_from_instance = bed_label
        field.help_text = "Only available beds are listed."


class IPDDoctorAssignmentForm(AdmissionChildForm):
    doctor_user_fields = ("doctor",)


class IPDDoctorNoteForm(AdmissionChildForm):
    doctor_user_fields = ("doctor",)


class IPDNursingVitalForm(AdmissionChildForm):
    derive = {"patient": "admission.patient"}


class IPDNursingNoteForm(AdmissionChildForm):
    derive = {"patient": "admission.patient"}


class IPDMedicationOrderForm(AdmissionChildForm):
    derive = {"patient": "admission.patient"}
    doctor_user_fields = ("prescribed_by",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.instance.pk:
            self.fields.pop("status", None)
            self.initial.setdefault("start_date", timezone.localdate())

        self.fields["end_date"].required = False
        self.fields["end_date"].help_text = (
            "Leave blank to use the start date plus the number of days."
        )

    def clean(self):
        cleaned = super().clean()

        start = cleaned.get("start_date")
        days = cleaned.get("duration_days") or 1

        if start and not cleaned.get("end_date"):
            cleaned["end_date"] = start + timedelta(days=max(days, 1) - 1)

        return cleaned


class IPDMedicationAdministrationForm(PortalForm):
    derive = {
        "admission": "medication_order.admission",
        "patient": "medication_order.patient",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        order_field = self.fields["medication_order"]
        order_field.queryset = (
            IPDMedicationOrder.objects
            .select_related("patient", "medicine", "admission")
            .filter(
                status=IPDMedicationOrder.Status.ACTIVE,
                admission__status__in=ACTIVE_ADMISSION,
            )
            .order_by("-id")
        )
        order_field.label_from_instance = lambda order: (
            f"{order.patient.full_name} · {order.medicine.name}"
            f" · {order.dose} {order.get_route_display()}"
        )

        batch = self.fields["medicine_batch"]
        batch.queryset = (
            MedicineBatch.objects.select_related("medicine")
            .filter(
                is_active=True,
                available_quantity__gt=0,
                expiry_date__gte=timezone.localdate(),
            )
            .order_by("medicine__name", "expiry_date")
        )
        batch.label_from_instance = batch_label
        batch.help_text = "Leave blank to use the batch that expires first."

        quantity = self.fields["quantity_given"]
        quantity.required = False
        quantity.help_text = "Leave blank for 1 when the dose is given."

        self.initial.setdefault(
            "scheduled_at",
            timezone.localtime().replace(second=0, microsecond=0),
        )

    def clean(self):
        cleaned = super().clean()

        order = cleaned.get("medication_order")
        status = cleaned.get("status")

        if order is None or status is None:
            return cleaned

        if status == self.instance.Status.GIVEN:
            quantity = cleaned.get("quantity_given") or 1
            cleaned["quantity_given"] = quantity

            if cleaned.get("medicine_batch") is None:
                batch = (
                    MedicineBatch.objects
                    .filter(
                        medicine=order.medicine,
                        is_active=True,
                        available_quantity__gte=quantity,
                        expiry_date__gte=timezone.localdate(),
                    )
                    .order_by("expiry_date", "id")
                    .first()
                )
                if batch is None:
                    self.add_error(
                        "medicine_batch",
                        f"No unexpired batch of {order.medicine.name} has "
                        f"{quantity} in stock.",
                    )
                else:
                    cleaned["medicine_batch"] = batch

            if self.request is not None:
                self.instance.administered_by = self.request.user
            self.instance.administered_at = timezone.now()
        else:
            cleaned["quantity_given"] = 0
            cleaned["medicine_batch"] = None

        return cleaned


# ---------------------------------------------------------------------------
# Laboratory
# ---------------------------------------------------------------------------

class LabSampleForm(PortalForm):
    derive = {"order": "order_item.order"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        field = self.fields["order_item"]
        field.queryset = (
            LabOrderItem.objects
            .select_related("order__patient", "test")
            .filter(
                Q(
                    test__isnull=False,
                    order__status__in=[
                        LabOrder.Status.ORDERED,
                        LabOrder.Status.SAMPLE_PENDING,
                        LabOrder.Status.SAMPLE_COLLECTED,
                        LabOrder.Status.PROCESSING,
                        LabOrder.Status.PARTIAL,
                    ],
                )
                | Q(pk=self.instance.order_item_id)
            )
            .exclude(status=LabOrderItem.Status.CANCELLED)
            .exclude(
                Q(
                    samples__status__in=[
                        LabSample.Status.PENDING,
                        LabSample.Status.COLLECTED,
                        LabSample.Status.RECEIVED,
                        LabSample.Status.PROCESSED,
                    ]
                )
                & ~Q(pk=self.instance.order_item_id)
            )
            .order_by("-order__order_date", "id")
        )
        field.label_from_instance = lambda item: (
            f"{item.order.order_number} · {item.order.patient.full_name}"
            f" · {item.test.name}"
        )

        self.fields["sample_type"].required = False
        self.fields["sample_type"].help_text = (
            "Leave blank to use the sample type of the test."
        )

        if self.instance.pk:
            field.disabled = True

    def clean(self):
        cleaned = super().clean()

        item = cleaned.get("order_item")

        if item is not None and not cleaned.get("sample_type") and item.test_id:
            cleaned["sample_type"] = item.test.sample_type

        return cleaned


class LabResultForm(PortalForm):
    derive = {
        "order_item": "sample.order_item",
        "test": "sample.order_item.test",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        field = self.fields["sample"]
        field.queryset = (
            LabSample.objects
            .select_related("order__patient", "order_item__test")
            .filter(
                Q(status__in=[LabSample.Status.RECEIVED, LabSample.Status.PROCESSED])
                | Q(pk=self.instance.sample_id)
            )
            .order_by("-id")
        )
        field.label_from_instance = lambda sample: (
            f"{sample.sample_number} · {sample.order.patient.full_name}"
            f" · {sample.order_item.test.name}"
            f"{' (' + sample.order_item.test.unit + ')' if sample.order_item.test.unit else ''}"
        )
        field.help_text = "Only samples already received in the lab are listed."

        if self.instance.pk:
            field.disabled = True


class LabReportForm(PortalForm):
    derive = {"patient": "order.patient"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        field = self.fields["order"]
        field.queryset = (
            LabOrder.objects.select_related("patient")
            .filter(
                Q(status=LabOrder.Status.COMPLETED, report__isnull=True)
                | Q(pk=self.instance.order_id)
            )
            .order_by("-order_date")
        )
        field.label_from_instance = lambda order: (
            f"{order.order_number} · {order.patient.full_name}"
        )
        field.help_text = (
            "Only orders whose tests are all completed and verified "
            "can get a report."
        )

        if self.instance.pk:
            field.disabled = True


# ---------------------------------------------------------------------------
# Pharmacy
# ---------------------------------------------------------------------------

class MedicineBatchForm(PortalForm):
    readonly_on_edit = ("medicine", "batch_number", "quantity_received")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk:
            self.fields["quantity_received"].help_text = (
                "Stock quantity is changed only through purchases, "
                "dispensing and stock adjustments."
            )
        else:
            self.fields["quantity_received"].help_text = (
                "Opening stock for this batch."
            )


class PrescriptionForm(PortalForm):
    derive = {
        "patient": "opd_visit.patient",
        "doctor": "opd_visit.doctor",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        field = self.fields["opd_visit"]
        field.queryset = (
            OPDVisit.objects.select_related("patient")
            .filter(
                Q(status__in=OPEN_VISIT, prescription__isnull=True)
                | Q(pk=self.instance.opd_visit_id)
            )
            .order_by("-visit_date", "-id")
        )
        field.label_from_instance = visit_label
        field.help_text = "Patient and doctor are taken from the visit."

        self.fields["status"].choices = [
            (Prescription.Status.DRAFT, "Draft"),
            (Prescription.Status.ACTIVE, "Active"),
            (Prescription.Status.CANCELLED, "Cancelled"),
        ]

        if self.instance.pk:
            field.disabled = True
        else:
            self.initial["status"] = Prescription.Status.ACTIVE


class PharmacyDispensingForm(PortalForm):
    derive = {"patient": "prescription.patient"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        field = self.fields["prescription"]
        field.queryset = (
            Prescription.objects.select_related("patient")
            .filter(
                Q(
                    status__in=[
                        Prescription.Status.ACTIVE,
                        Prescription.Status.PARTIALLY_DISPENSED,
                    ]
                )
                | Q(pk=self.instance.prescription_id)
            )
            .order_by("-id")
        )
        field.label_from_instance = lambda rx: (
            f"{rx.prescription_number} · {rx.patient.full_name}"
        )
        field.help_text = (
            "Items and batches (earliest expiry first) are filled in "
            "automatically."
        )

        if self.instance.pk:
            field.disabled = True


class PurchaseReturnForm(PortalForm):
    derive = {"supplier": "purchase.supplier"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        field = self.fields["purchase"]
        field.queryset = (
            PharmacyPurchase.objects.select_related("supplier")
            .filter(
                Q(status=PharmacyPurchase.Status.RECEIVED)
                | Q(pk=self.instance.purchase_id)
            )
            .order_by("-id")
        )
        field.label_from_instance = lambda purchase: (
            f"{purchase.grn_number} · {purchase.supplier.name}"
        )

        if self.instance.pk:
            field.disabled = True


class PurchaseReturnLineForm(LineForm):

    def restrict(self, parent):
        self.parent_return = parent

        if parent.purchase_id:
            self.fields["purchase_item"].queryset = (
                self.fields["purchase_item"].queryset
                .filter(purchase_id=parent.purchase_id)
                .select_related("medicine")
            )
            self.fields["purchase_item"].label_from_instance = lambda item: (
                f"{item.medicine.name} · batch {item.batch_number}"
                f" · received {item.quantity_received}"
            )

        batch = self.fields["medicine_batch"]
        batch.required = False
        batch.help_text = "Blank = the batch received in this purchase."

        price = self.fields["return_price"]
        price.required = False
        price.help_text = "Blank = purchase price"

    def clean(self):
        cleaned = super().clean()

        item = cleaned.get("purchase_item")
        batch = cleaned.get("medicine_batch")

        if item is not None and batch is None:
            batch = (
                MedicineBatch.objects
                .filter(
                    medicine=item.medicine,
                    batch_number=item.batch_number,
                    expiry_date=item.expiry_date,
                )
                .order_by("-id")
                .first()
            )
            if batch is None:
                self.add_error(
                    "medicine_batch",
                    "This purchase line has no stock batch yet.",
                )
            else:
                cleaned["medicine_batch"] = batch

        quantity = cleaned.get("quantity_returned")
        if batch is not None and quantity and quantity > batch.available_quantity:
            self.add_error(
                "quantity_returned",
                f"Only {batch.available_quantity} left in this batch.",
            )

        if cleaned.get("return_price") is None:
            cleaned["return_price"] = (
                item.purchase_price if item is not None else Decimal("0")
            )

        return cleaned


class DispensingLineForm(LineForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk and self.instance.stock_applied:
            self.locked = True
            for field in self.fields.values():
                field.disabled = True

        self.fields["discount"].required = False

    def restrict(self, parent):
        if parent.prescription_id:
            item_field = self.fields["prescription_item"]
            item_field.queryset = (
                PrescriptionItem.objects
                .filter(prescription_id=parent.prescription_id)
                .select_related("medicine")
            )
            item_field.label_from_instance = lambda item: (
                f"{item.medicine.name} · prescribed {item.quantity_prescribed}"
            )

        batch = self.fields["medicine_batch"]
        batch.queryset = (
            MedicineBatch.objects.select_related("medicine")
            .filter(
                Q(
                    is_active=True,
                    available_quantity__gt=0,
                    expiry_date__gte=timezone.localdate(),
                )
                | Q(pk=self.instance.medicine_batch_id)
            )
            .order_by("medicine__name", "expiry_date")
        )
        batch.label_from_instance = batch_label

    def clean_discount(self):
        value = self.cleaned_data.get("discount")
        return value if value is not None else Decimal("0.00")
