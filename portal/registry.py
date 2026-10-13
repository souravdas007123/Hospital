"""One place that describes every section of the portal.

Each ``Entity`` knows its model, how to list it, how to build its add/edit
form, which buttons appear on its rows and how it is saved. The generic
views in ``views.py`` do the rest.
"""

from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Q, Sum
from django.forms import modelform_factory
from django.urls import reverse
from django.utils import timezone

from appointments.models import Appointment
from doctors.models import Doctor, DoctorAvailability, DoctorSchedule
from hospitals.models import Bed, Building, Department, Floor, Hospital, Room, Ward
from ipd.forms import IPDDischargeForm
from ipd.models import (
    IPDAdmission,
    IPDBedTransfer,
    IPDDoctorAssignment,
    IPDDoctorNote,
    IPDMedicationAdministration,
    IPDMedicationOrder,
    IPDNursingNote,
    IPDNursingVital,
)
from laboratory.models import (
    LabCategory,
    LabOrder,
    LabPackage,
    LabPackageItem,
    LabReferenceRange,
    LabReport,
    LabResult,
    LabSample,
    LabTest,
    SampleType,
)
from opd.models import (
    OPDConsultation,
    OPDDiagnosis,
    OPDFollowUp,
    OPDVisit,
    PatientVital,
)
from patients.models import Patient, PatientDocument
from pharmacy.models import (
    Manufacturer,
    Medicine,
    MedicineBatch,
    MedicineCategory,
    PharmacyDispensing,
    PharmacyDispensingItem,
    PharmacyPurchase,
    PharmacyPurchaseItem,
    PharmacyPurchaseReturn,
    PharmacyPurchaseReturnItem,
    Prescription,
    PrescriptionItem,
    StockTransaction,
    Supplier,
)

from . import forms as portal_forms
from . import forms_modules as module_forms
from . import workflows as wf
from .spec import Action, Inline
from .utils import (
    WEEKDAYS,
    doctor_profile_name,
    new_url,
    person_name,
    user_doctor_name,
    weekday_name,
)


User = get_user_model()

ACTIVE_CHOICES = [("1", "Active"), ("0", "Inactive")]


def cast_bool(value):
    return value == "1"


class Entity:
    """Configuration for one portal section (list + add/edit/delete)."""

    def __init__(
        self,
        key,
        model,
        title,
        plural,
        group,
        subtitle,
        columns,
        search,
        ordering,
        select=(),
        prefetch=(),
        annotate=None,
        filter_field=None,
        filter_label="All",
        filter_choices=(),
        filter_cast=None,
        form_base=None,
        form_fields=None,
        form_exclude=(),
        inlines=(),
        auto_user=(),
        creator=None,
        creator_on_edit=False,
        allow_edit=True,
        allow_delete=True,
        edit_after_create=False,
        before_save=None,
        after_save=None,
        guard=None,
        actions=(),
    ):
        self.key = key
        self.model = model
        self.title = title
        self.plural = plural
        self.group = group
        self.subtitle = subtitle
        self.columns = columns
        self.search = list(search)
        self.ordering = tuple(ordering)
        self.select = tuple(select)
        self.prefetch = tuple(prefetch)
        self.annotate = annotate        # callable() -> dict of annotations
        self.filter_field = filter_field
        self.filter_label = filter_label
        self.filter_choices = list(filter_choices)
        self.filter_cast = filter_cast
        self.form_base = form_base or portal_forms.PortalForm
        self.form_fields = form_fields
        self.form_exclude = tuple(form_exclude)
        self.inlines = list(inlines)
        self.auto_user = tuple(auto_user)    # set to the logged-in user on create
        self.creator = creator               # callable(form, request) -> instance
        self.creator_on_edit = creator_on_edit
        self.allow_edit = allow_edit
        self.allow_delete = allow_delete
        self.edit_after_create = edit_after_create
        self.before_save = before_save  # callable(instance, request)
        self.after_save = after_save    # callable(instance, form, request, created)
        self.guard = guard              # callable(obj, request, action) -> error or None
        self.actions = list(actions)
        self._form_class = None

    # -- permissions ------------------------------------------------------
    def perm(self, action):
        opts = self.model._meta
        return f"{opts.app_label}.{action}_{opts.model_name}"

    def action_perm(self, action):
        """Full permission string needed for a row button."""
        if "." in action.perm:
            return action.perm
        return self.perm(action.perm)

    # -- data ---------------------------------------------------------------
    def queryset(self):
        queryset = self.model.objects.all()

        # select_related() with no arguments would follow every FK, so only
        # call it when this section names specific relations.
        if self.select:
            queryset = queryset.select_related(*self.select)

        if self.prefetch:
            queryset = queryset.prefetch_related(*self.prefetch)

        if self.annotate:
            queryset = queryset.annotate(**self.annotate())

        return queryset

    # -- forms --------------------------------------------------------------
    def get_form_class(self):
        if self._form_class is None:
            if self.form_fields:
                kwargs = {"fields": tuple(self.form_fields)}
            else:
                kwargs = {"exclude": self.form_exclude}

            self._form_class = modelform_factory(
                self.model,
                form=self.form_base,
                formfield_callback=portal_forms.portal_formfield,
                **kwargs,
            )
        return self._form_class


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

def assign_appointment_token(instance, request):
    """Blank token -> next number for that doctor on that day."""
    if instance.token_number is not None:
        return

    last = (
        Appointment.objects
        .filter(
            doctor=instance.doctor,
            appointment_date=instance.appointment_date,
        )
        .aggregate(highest=Max("token_number"))["highest"]
        or 0
    )
    instance.token_number = last + 1


def has_related(obj, name):
    """True when a one-to-one child (e.g. ``visit.vitals``) exists."""
    return hasattr(obj, name)


def user_guard(obj, request, action):
    if obj.is_superuser and not request.user.is_superuser:
        return "Only a superuser can change or delete a superuser account."

    if action == "delete" and obj.pk == request.user.pk:
        return "You cannot delete your own account."

    return None


PATIENT_SEARCH = [
    "patient__uhid",
    "patient__first_name",
    "patient__last_name",
    "patient__phone",
]


VISIT_PATIENT_SEARCH = [
    "opd_visit__visit_number",
    "opd_visit__patient__uhid",
    "opd_visit__patient__first_name",
    "opd_visit__patient__last_name",
    "opd_visit__patient__phone",
]

ADMISSION_SEARCH = [
    "admission__admission_number",
    "admission__patient__uhid",
    "admission__patient__first_name",
    "admission__patient__last_name",
]


def bp_text(systolic, diastolic):
    if systolic and diastolic:
        return f"{systolic}/{diastolic}"
    return None


def result_flag(result):
    if result.is_critical:
        return {"text": "Critical", "badge": "s-cancelled"}
    if result.is_abnormal:
        return {"text": "Abnormal", "badge": "s-waiting"}
    return {"text": "Normal", "badge": "s-completed"}


def file_link(field_name):
    def build(obj):
        field = getattr(obj, field_name)
        if not field:
            return None
        return {"text": "Open file", "href": field.url}
    return build


def medicine_stock():
    return {
        "stock_total": Sum(
            "batches__available_quantity",
            filter=Q(
                batches__is_active=True,
                batches__expiry_date__gte=timezone.localdate(),
            ),
        )
    }


def count_items():
    return {"item_count": Count("items")}


# ---------------------------------------------------------------------------
# The sections, in menu order
# ---------------------------------------------------------------------------

ENTITY_LIST = [
    # ---- Clinical --------------------------------------------------------
    Entity(
        key="patients",
        model=Patient,
        title="Patient",
        plural="Patients",
        group="Clinical",
        subtitle="Registered patients",
        search=[
            "uhid", "first_name", "middle_name", "last_name",
            "phone", "email", "city",
        ],
        ordering=("-registration_date", "-id"),
        filter_field="gender",
        filter_label="All genders",
        filter_choices=Patient.Gender.choices,
        form_exclude=("created_by",),
        columns=[
            ("UHID", "uhid", "mono"),
            ("Patient", "full_name", None),
            ("Gender", "get_gender_display", None),
            ("Blood group", "get_blood_group_display", None),
            ("Phone", "phone", None),
            ("City", "city", None),
            ("Registered", "registration_date", None),
            ("Status", "is_active", "active"),
        ],
    ),
    Entity(
        key="appointments",
        model=Appointment,
        title="Appointment",
        plural="Appointments",
        group="Clinical",
        subtitle="Booked, ongoing and past appointments",
        select=("patient", "doctor__user", "department", "opd_visit"),
        search=PATIENT_SEARCH + [
            "appointment_number",
            "doctor__user__first_name",
            "doctor__user__last_name",
            "department__name",
        ],
        ordering=("-appointment_date", "start_time", "-id"),
        filter_field="status",
        filter_label="All statuses",
        filter_choices=Appointment.Status.choices,
        form_base=portal_forms.AppointmentForm,
        form_exclude=(
            "created_by", "checked_in_at", "completed_at", "cancelled_at",
        ),
        before_save=assign_appointment_token,
        guard=wf.appointment_guard,
        actions=[
            Action(
                "check-in", "Check in", run=wf.act_check_in, style="primary",
                visible=lambda o: o.status in (
                    Appointment.Status.BOOKED, Appointment.Status.CONFIRMED
                ) and o.appointment_date == timezone.localdate(),
            ),
            Action(
                "start-visit", "Start OPD visit", run=wf.act_start_visit,
                perm="opd.add_opdvisit", style="primary",
                visible=lambda o: o.status == Appointment.Status.CHECKED_IN
                and not has_related(o, "opd_visit"),
            ),
            Action(
                "no-show", "No show", run=wf.act_no_show,
                confirm="Mark this patient as a no-show?",
                visible=lambda o: o.status in (
                    Appointment.Status.BOOKED, Appointment.Status.CONFIRMED
                ) and o.appointment_date <= timezone.localdate(),
            ),
            Action(
                "cancel", "Cancel", run=wf.act_cancel_appointment,
                form=wf.ReasonForm, style="danger",
                visible=lambda o: o.status in (
                    Appointment.Status.BOOKED,
                    Appointment.Status.CONFIRMED,
                    Appointment.Status.CHECKED_IN,
                ),
            ),
        ],
        columns=[
            ("Appt no.", "appointment_number", "mono"),
            ("Patient", "patient.full_name", None),
            ("Doctor", lambda o: doctor_profile_name(o.doctor), None),
            ("Department", "department.name", None),
            ("Date", "appointment_date", None),
            ("Time", "start_time", None),
            ("Token", "token_number", "num"),
            ("Type", "get_appointment_type_display", None),
            ("Status", "status", "status"),
        ],
    ),
    Entity(
        key="opd",
        model=OPDVisit,
        title="OPD Visit",
        plural="OPD Visits",
        group="Clinical",
        subtitle="Outpatient visits and consultations",
        select=(
            "patient", "doctor__user", "department", "vitals", "consultation",
            "prescription",
        ),
        search=PATIENT_SEARCH + [
            "visit_number",
            "doctor__user__first_name",
            "doctor__user__last_name",
            "department__name",
            "chief_complaint",
        ],
        ordering=("-visit_date", "-id"),
        filter_field="status",
        filter_label="All statuses",
        filter_choices=OPDVisit.Status.choices,
        form_base=portal_forms.OPDVisitForm,
        form_exclude=(
            "patient", "doctor", "department", "created_by", "completed_at",
        ),
        guard=wf.opd_guard,
        actions=[
            Action(
                "vitals", "Vitals", perm="opd.add_patientvital",
                link=lambda o: new_url("vitals", opd_visit=o.pk),
                visible=lambda o: o.status == OPDVisit.Status.WAITING
                and not has_related(o, "vitals"),
            ),
            Action(
                "consult", "Consultation", perm="opd.add_opdconsultation",
                link=lambda o: new_url("consultations", opd_visit=o.pk),
                visible=lambda o: o.status in (
                    OPDVisit.Status.WAITING, OPDVisit.Status.VITALS_COMPLETED
                ) and not has_related(o, "consultation"),
            ),
            Action(
                "diagnosis", "Diagnosis", perm="opd.add_opddiagnosis",
                link=lambda o: new_url("diagnoses", opd_visit=o.pk),
                visible=lambda o: o.status in (
                    OPDVisit.Status.IN_CONSULTATION,
                    OPDVisit.Status.CONSULTATION_COMPLETED,
                ),
            ),
            Action(
                "prescribe", "Prescribe", perm="pharmacy.add_prescription",
                link=lambda o: new_url("prescriptions", opd_visit=o.pk),
                visible=lambda o: o.status in (
                    OPDVisit.Status.IN_CONSULTATION,
                    OPDVisit.Status.CONSULTATION_COMPLETED,
                ) and not has_related(o, "prescription"),
            ),
            Action(
                "lab", "Lab order", perm="laboratory.add_laborder",
                link=lambda o: new_url(
                    "lab-orders", patient=o.patient_id, opd_visit=o.pk
                ),
                visible=lambda o: o.status in (
                    OPDVisit.Status.IN_CONSULTATION,
                    OPDVisit.Status.CONSULTATION_COMPLETED,
                ),
            ),
            Action(
                "followup", "Follow-up", perm="opd.add_opdfollowup",
                link=lambda o: new_url("follow-ups", opd_visit=o.pk),
                visible=lambda o: o.status == OPDVisit.Status.CONSULTATION_COMPLETED,
            ),
            Action(
                "complete", "Complete visit", run=wf.act_complete_visit,
                style="primary",
                confirm="Mark this visit as completed? It will be locked.",
                visible=lambda o: o.status == OPDVisit.Status.CONSULTATION_COMPLETED,
            ),
        ],
        columns=[
            ("Visit no.", "visit_number", "mono"),
            ("Patient", "patient.full_name", None),
            ("Doctor", lambda o: doctor_profile_name(o.doctor), None),
            ("Department", "department.name", None),
            ("Visit date", "visit_date", None),
            ("Complaint", "chief_complaint", "trunc"),
            ("Status", "status", "status"),
        ],
    ),
    Entity(
        key="ipd",
        model=IPDAdmission,
        title="IPD Admission",
        plural="IPD Admissions",
        group="Clinical",
        subtitle="Inpatient admissions and bed allocation",
        select=("patient", "doctor", "ward", "room", "bed"),
        search=PATIENT_SEARCH + [
            "admission_number",
            "doctor__first_name",
            "doctor__last_name",
            "ward__name",
            "room__room_number",
            "bed__bed_number",
        ],
        ordering=("-admission_date", "-id"),
        filter_field="status",
        filter_label="All statuses",
        filter_choices=IPDAdmission.Status.choices,
        form_base=portal_forms.IPDAdmissionForm,
        form_exclude=("admission_number", "created_by"),
        guard=wf.admission_guard,
        actions=[
            Action(
                "transfer", "Transfer bed", perm="ipd.add_ipdbedtransfer",
                link=lambda o: new_url("ipd-transfers", admission=o.pk),
                visible=lambda o: o.status in ("ADMITTED", "ON_HOLD"),
            ),
            Action(
                "vitals", "Vitals", perm="ipd.add_ipdnursingvital",
                link=lambda o: new_url("ipd-vitals", admission=o.pk),
                visible=lambda o: o.status in ("ADMITTED", "ON_HOLD"),
            ),
            Action(
                "discharge", "Discharge", run=wf.act_discharge,
                form=IPDDischargeForm, style="danger",
                visible=lambda o: o.status in ("ADMITTED", "ON_HOLD"),
            ),
        ],
        columns=[
            ("Admission no.", "admission_number", "mono"),
            ("Patient", "patient.full_name", None),
            ("Doctor", lambda o: user_doctor_name(o.doctor), None),
            ("Ward", "ward.name", None),
            ("Room", "room.room_number", None),
            ("Bed", "bed.bed_number", None),
            ("Admitted on", "admission_date", None),
            ("Type", "get_admission_type_display", None),
            ("Status", "status", "status"),
        ],
    ),
    Entity(
        key="lab-orders",
        model=LabOrder,
        title="Lab Order",
        plural="Lab Orders",
        group="Laboratory",
        subtitle="Laboratory orders and their progress",
        select=("patient", "doctor", "report"),
        search=PATIENT_SEARCH + [
            "order_number",
            "doctor__first_name",
            "doctor__last_name",
        ],
        ordering=("-order_date", "-id"),
        filter_field="status",
        filter_label="All statuses",
        filter_choices=LabOrder.Status.choices,
        form_base=portal_forms.LabOrderForm,
        form_exclude=("total_amount", "created_by"),
        inlines=[
            Inline("lines", "Tests", portal_forms.lab_item_formset),
        ],
        after_save=wf.after_lab_order,
        guard=wf.lab_order_guard,
        actions=[
            Action(
                "samples", "Create samples", run=wf.act_create_samples,
                perm="laboratory.add_labsample", style="primary",
                visible=lambda o: o.status in (
                    LabOrder.Status.DRAFT, LabOrder.Status.ORDERED
                ),
            ),
            Action(
                "report", "Create report", run=wf.act_create_report_from_order,
                perm="laboratory.add_labreport", style="primary",
                visible=lambda o: o.status == LabOrder.Status.COMPLETED
                and not has_related(o, "report"),
            ),
            Action(
                "view-report", "View report", perm="laboratory.view_labreport",
                link=lambda o: reverse(
                    "laboratory:lab_report_print", kwargs={"pk": o.report.pk}
                ),
                new_tab=True,
                visible=lambda o: has_related(o, "report"),
            ),
            Action(
                "cancel", "Cancel order", run=wf.act_cancel_lab_order,
                form=wf.ReasonForm, style="danger",
                visible=lambda o: o.status in (
                    LabOrder.Status.DRAFT,
                    LabOrder.Status.ORDERED,
                    LabOrder.Status.SAMPLE_PENDING,
                ),
            ),
        ],
        columns=[
            ("Order no.", "order_number", "mono"),
            ("Patient", "patient.full_name", None),
            ("Ordered by", lambda o: user_doctor_name(o.doctor), None),
            ("Ordered on", "order_date", None),
            ("Priority", "priority", "urgent"),
            ("Amount", "total_amount", "num"),
            ("Status", "status", "status"),
        ],
    ),

    # ---- Clinical: OPD workflow ---------------------------------------------
    Entity(
        key="vitals",
        model=PatientVital,
        title="OPD Vitals",
        plural="OPD Vitals",
        group="Clinical",
        subtitle="Vital signs taken before the consultation",
        select=("opd_visit__patient",),
        search=VISIT_PATIENT_SEARCH,
        ordering=("-recorded_at", "-id"),
        form_base=module_forms.PatientVitalForm,
        form_exclude=("recorded_by", "recorded_at"),
        auto_user=("recorded_by",),
        after_save=wf.after_vitals,
        columns=[
            ("Visit", "opd_visit.visit_number", "mono"),
            ("Patient", "opd_visit.patient.full_name", None),
            ("BP (mmHg)", lambda o: bp_text(o.systolic_bp, o.diastolic_bp), None),
            ("Pulse", "pulse_rate", "num"),
            ("Temp", "temperature", "num"),
            ("SpO₂ %", "spo2", "num"),
            ("Weight kg", "weight", "num"),
            ("Recorded", "recorded_at", None),
        ],
    ),
    Entity(
        key="consultations",
        model=OPDConsultation,
        title="Consultation",
        plural="Consultations",
        group="Clinical",
        subtitle="Doctor's findings, plan and advice for each visit",
        select=("opd_visit__patient", "opd_visit__doctor__user"),
        search=VISIT_PATIENT_SEARCH + ["diagnosis_summary", "symptoms"],
        ordering=("-created_at", "-id"),
        form_base=module_forms.OPDConsultationForm,
        after_save=wf.after_consultation,
        columns=[
            ("Visit", "opd_visit.visit_number", "mono"),
            ("Patient", "opd_visit.patient.full_name", None),
            ("Doctor", lambda o: doctor_profile_name(o.opd_visit.doctor), None),
            ("Diagnosis", "diagnosis_summary", "trunc"),
            ("Started", "consultation_start", None),
            ("Ended", "consultation_end", None),
        ],
    ),
    Entity(
        key="diagnoses",
        model=OPDDiagnosis,
        title="Diagnosis",
        plural="Diagnoses",
        group="Clinical",
        subtitle="Diagnoses recorded during OPD visits",
        select=("opd_visit__patient", "diagnosed_by__user"),
        search=VISIT_PATIENT_SEARCH + ["diagnosis"],
        ordering=("-created_at", "-id"),
        filter_field="diagnosis_type",
        filter_label="All types",
        filter_choices=OPDDiagnosis.DiagnosisType.choices,
        form_base=module_forms.OPDDiagnosisForm,
        form_exclude=("diagnosed_by", "created_at"),
        columns=[
            ("Visit", "opd_visit.visit_number", "mono"),
            ("Patient", "opd_visit.patient.full_name", None),
            ("Type", "get_diagnosis_type_display", None),
            ("Diagnosis", "diagnosis", "trunc"),
            ("Doctor", lambda o: doctor_profile_name(o.diagnosed_by), None),
            ("Recorded", "created_at", None),
        ],
    ),
    Entity(
        key="follow-ups",
        model=OPDFollowUp,
        title="Follow-up",
        plural="Follow-ups",
        group="Clinical",
        subtitle="Patients who must come back",
        select=("patient", "doctor__user", "opd_visit"),
        search=PATIENT_SEARCH + ["opd_visit__visit_number", "instructions"],
        ordering=("followup_date", "-id"),
        filter_field="status",
        filter_label="All statuses",
        filter_choices=OPDFollowUp.Status.choices,
        form_base=module_forms.OPDFollowUpForm,
        form_exclude=("patient", "doctor", "created_at", "updated_at"),
        actions=[
            Action(
                "done", "Mark done", run=wf.act_followup_done,
                visible=lambda o: o.status == OPDFollowUp.Status.PENDING,
            ),
            Action(
                "cancel", "Cancel", run=wf.act_followup_cancel,
                confirm="Cancel this follow-up?", style="danger",
                visible=lambda o: o.status == OPDFollowUp.Status.PENDING,
            ),
        ],
        columns=[
            ("Patient", "patient.full_name", None),
            ("Doctor", lambda o: doctor_profile_name(o.doctor), None),
            ("Visit", "opd_visit.visit_number", "mono"),
            ("Follow-up date", "followup_date", None),
            ("Instructions", "instructions", "trunc"),
            ("Status", "status", "status"),
        ],
    ),
    Entity(
        key="patient-documents",
        model=PatientDocument,
        title="Patient Document",
        plural="Patient Documents",
        group="Clinical",
        subtitle="Scanned reports, ID proofs and other files",
        select=("patient", "uploaded_by"),
        search=PATIENT_SEARCH + ["title", "description"],
        ordering=("-uploaded_at", "-id"),
        filter_field="document_type",
        filter_label="All types",
        filter_choices=PatientDocument.DocumentType.choices,
        form_exclude=("uploaded_by", "uploaded_at"),
        auto_user=("uploaded_by",),
        columns=[
            ("Patient", "patient.full_name", None),
            ("Type", "get_document_type_display", None),
            ("Title", "title", None),
            ("File", file_link("file"), "link"),
            ("Uploaded by", lambda o: person_name(o.uploaded_by), None),
            ("Uploaded", "uploaded_at", None),
        ],
    ),

    # ---- Inpatient ------------------------------------------------------------
    Entity(
        key="ipd-transfers",
        model=IPDBedTransfer,
        title="Bed Transfer",
        plural="Bed Transfers",
        group="Inpatient",
        subtitle="History of patients moved between beds (saved automatically)",
        select=(
            "admission", "patient", "from_ward", "from_bed", "to_ward",
            "to_bed", "transferred_by",
        ),
        search=ADMISSION_SEARCH + ["from_bed__bed_number", "to_bed__bed_number"],
        ordering=("-transfer_date", "-id"),
        form_base=module_forms.IPDBedTransferForm,
        form_fields=("admission", "to_bed", "reason", "notes"),
        creator=wf.create_bed_transfer,
        allow_edit=False,
        allow_delete=False,
        columns=[
            ("Admission", "admission.admission_number", "mono"),
            ("Patient", "patient.full_name", None),
            ("From", lambda o: f"{o.from_ward.name} · bed {o.from_bed.bed_number}", None),
            ("To", lambda o: f"{o.to_ward.name} · bed {o.to_bed.bed_number}", None),
            ("When", "transfer_date", None),
            ("Reason", "reason", "trunc"),
            ("By", lambda o: person_name(o.transferred_by), None),
        ],
    ),
    Entity(
        key="ipd-doctors",
        model=IPDDoctorAssignment,
        title="Doctor Assignment",
        plural="Doctor Assignments",
        group="Inpatient",
        subtitle="Doctors looking after each admitted patient",
        select=("admission__patient", "doctor"),
        search=ADMISSION_SEARCH + ["doctor__first_name", "doctor__last_name"],
        ordering=("-assigned_date", "-id"),
        filter_field="role",
        filter_label="All roles",
        filter_choices=IPDDoctorAssignment.Role.choices,
        form_base=module_forms.IPDDoctorAssignmentForm,
        form_fields=("admission", "doctor", "role", "reason", "notes"),
        creator=wf.create_doctor_assignment,
        allow_edit=False,
        allow_delete=False,
        actions=[
            Action(
                "end", "End assignment", run=wf.act_end_assignment,
                form=wf.ReasonForm, style="danger",
                visible=lambda o: o.is_active
                and o.role != IPDDoctorAssignment.Role.PRIMARY,
            ),
        ],
        columns=[
            ("Admission", "admission.admission_number", "mono"),
            ("Patient", "admission.patient.full_name", None),
            ("Doctor", lambda o: user_doctor_name(o.doctor), None),
            ("Role", "get_role_display", None),
            ("Assigned", "assigned_date", None),
            ("Ended", "end_date", None),
            ("Current", "is_active", "yesno"),
        ],
    ),
    Entity(
        key="ipd-doctor-notes",
        model=IPDDoctorNote,
        title="Doctor Note",
        plural="Doctor Notes",
        group="Inpatient",
        subtitle="Progress notes written by the treating doctors",
        select=("admission__patient", "doctor"),
        search=ADMISSION_SEARCH + ["clinical_note", "note_type"],
        ordering=("-note_date", "-id"),
        form_base=module_forms.IPDDoctorNoteForm,
        form_fields=("admission", "doctor", "note_type", "clinical_note"),
        creator=wf.create_doctor_note,
        allow_delete=False,
        columns=[
            ("Admission", "admission.admission_number", "mono"),
            ("Patient", "admission.patient.full_name", None),
            ("Doctor", lambda o: user_doctor_name(o.doctor), None),
            ("Type", "note_type", None),
            ("Note", "clinical_note", "trunc"),
            ("When", "note_date", None),
        ],
    ),
    Entity(
        key="ipd-vitals",
        model=IPDNursingVital,
        title="Nursing Vitals",
        plural="Nursing Vitals",
        group="Inpatient",
        subtitle="Vital signs charted by nursing staff",
        select=("admission", "patient", "recorded_by"),
        search=ADMISSION_SEARCH,
        ordering=("-recorded_at", "-id"),
        form_base=module_forms.IPDNursingVitalForm,
        form_fields=(
            "admission", "temperature", "systolic_bp", "diastolic_bp",
            "pulse", "respiratory_rate", "spo2", "weight", "height",
            "blood_glucose", "pain_score", "nursing_notes",
        ),
        creator=wf.create_ipd_vitals,
        allow_delete=False,
        columns=[
            ("Admission", "admission.admission_number", "mono"),
            ("Patient", "patient.full_name", None),
            ("BP (mmHg)", lambda o: bp_text(o.systolic_bp, o.diastolic_bp), None),
            ("Pulse", "pulse", "num"),
            ("Temp", "temperature", "num"),
            ("SpO₂ %", "spo2", "num"),
            ("Recorded", "recorded_at", None),
            ("By", lambda o: person_name(o.recorded_by), None),
        ],
    ),
    Entity(
        key="ipd-nursing-notes",
        model=IPDNursingNote,
        title="Nursing Note",
        plural="Nursing Notes",
        group="Inpatient",
        subtitle="Observations, handovers and intake / output",
        select=("admission", "patient", "nurse"),
        search=ADMISSION_SEARCH + ["notes"],
        ordering=("-note_date", "-id"),
        filter_field="note_type",
        filter_label="All types",
        filter_choices=IPDNursingNote.NoteType.choices,
        form_base=module_forms.IPDNursingNoteForm,
        form_fields=("admission", "note_type", "notes", "intake_ml", "output_ml"),
        creator=wf.create_nursing_note,
        allow_delete=False,
        columns=[
            ("Admission", "admission.admission_number", "mono"),
            ("Patient", "patient.full_name", None),
            ("Type", "get_note_type_display", None),
            ("Note", "notes", "trunc"),
            ("Intake ml", "intake_ml", "num"),
            ("Output ml", "output_ml", "num"),
            ("When", "note_date", None),
            ("Nurse", lambda o: person_name(o.nurse), None),
        ],
    ),
    Entity(
        key="ipd-medication-orders",
        model=IPDMedicationOrder,
        title="Medication Order",
        plural="Medication Orders",
        group="Inpatient",
        subtitle="Medicines ordered for admitted patients",
        select=("admission", "patient", "medicine", "prescribed_by"),
        search=ADMISSION_SEARCH + ["medicine__name"],
        ordering=("-created_at", "-id"),
        filter_field="status",
        filter_label="All statuses",
        filter_choices=IPDMedicationOrder.Status.choices,
        form_base=module_forms.IPDMedicationOrderForm,
        form_fields=(
            "admission", "medicine", "prescribed_by", "dose", "route",
            "frequency", "duration_days", "quantity", "start_date",
            "end_date", "instructions", "status",
        ),
        creator=wf.create_medication_order,
        allow_delete=False,
        actions=[
            Action(
                "give", "Give dose", perm="ipd.add_ipdmedicationadministration",
                link=lambda o: new_url("ipd-medication-doses", medication_order=o.pk),
                style="primary",
                visible=lambda o: o.status == IPDMedicationOrder.Status.ACTIVE,
            ),
            Action(
                "stop", "Stop order", run=wf.act_stop_order,
                confirm="Stop this medication order?", style="danger",
                visible=lambda o: o.status == IPDMedicationOrder.Status.ACTIVE,
            ),
        ],
        columns=[
            ("Admission", "admission.admission_number", "mono"),
            ("Patient", "patient.full_name", None),
            ("Medicine", "medicine.name", None),
            ("Dose", "dose", None),
            ("Frequency", "frequency", None),
            ("From", "start_date", None),
            ("To", "end_date", None),
            ("Status", "status", "status"),
        ],
    ),
    Entity(
        key="ipd-medication-doses",
        model=IPDMedicationAdministration,
        title="Medication Dose",
        plural="Medication Doses",
        group="Inpatient",
        subtitle="Each dose given, missed or refused (stock is deducted when given)",
        select=(
            "medication_order__medicine", "admission", "patient",
            "administered_by",
        ),
        search=ADMISSION_SEARCH + ["medication_order__medicine__name"],
        ordering=("-scheduled_at", "-id"),
        filter_field="status",
        filter_label="All statuses",
        filter_choices=IPDMedicationAdministration.Status.choices,
        form_base=module_forms.IPDMedicationAdministrationForm,
        form_fields=(
            "medication_order", "status", "scheduled_at", "quantity_given",
            "medicine_batch", "reason", "notes",
        ),
        creator=wf.create_medication_administration,
        allow_edit=False,
        allow_delete=False,
        columns=[
            ("Patient", "patient.full_name", None),
            ("Medicine", "medication_order.medicine.name", None),
            ("Scheduled", "scheduled_at", None),
            ("Given at", "administered_at", None),
            ("Qty", "quantity_given", "num"),
            ("Status", "status", "status"),
            ("By", lambda o: person_name(o.administered_by), None),
        ],
    ),

    # ---- Laboratory -------------------------------------------------------------
    Entity(
        key="lab-samples",
        model=LabSample,
        title="Lab Sample",
        plural="Lab Samples",
        group="Laboratory",
        subtitle="Collect, receive and reject samples",
        select=("order__patient", "order_item__test", "sample_type"),
        search=[
            "sample_number", "barcode", "order__order_number",
            "order__patient__uhid", "order__patient__first_name",
            "order__patient__last_name", "order_item__test__name",
        ],
        ordering=("-id",),
        filter_field="status",
        filter_label="All statuses",
        filter_choices=LabSample.Status.choices,
        form_base=module_forms.LabSampleForm,
        form_fields=("order_item", "sample_type", "remarks"),
        creator=wf.create_lab_sample,
        allow_delete=False,
        actions=[
            Action(
                "collect", "Collect", run=wf.act_collect_sample, style="primary",
                visible=lambda o: o.status == LabSample.Status.PENDING,
            ),
            Action(
                "receive", "Receive in lab", run=wf.act_receive_sample,
                style="primary",
                visible=lambda o: o.status == LabSample.Status.COLLECTED,
            ),
            Action(
                "result", "Enter result", perm="laboratory.add_labresult",
                link=lambda o: new_url("lab-results", sample=o.pk),
                style="primary",
                visible=lambda o: o.status in (
                    LabSample.Status.RECEIVED, LabSample.Status.PROCESSED
                ),
            ),
            Action(
                "reject", "Reject", run=wf.act_reject_sample,
                form=wf.ReasonForm, style="danger",
                visible=lambda o: o.status in (
                    LabSample.Status.PENDING,
                    LabSample.Status.COLLECTED,
                    LabSample.Status.RECEIVED,
                ),
            ),
        ],
        columns=[
            ("Sample no.", "sample_number", "mono"),
            ("Patient", "order.patient.full_name", None),
            ("Test", "order_item.test.name", None),
            ("Sample type", "sample_type.name", None),
            ("Order", "order.order_number", "mono"),
            ("Collected", "collected_at", None),
            ("Status", "status", "status"),
        ],
    ),
    Entity(
        key="lab-results",
        model=LabResult,
        title="Lab Result",
        plural="Lab Results",
        group="Laboratory",
        subtitle="Enter and verify test results; abnormal values are flagged automatically",
        select=("sample__order__patient", "test"),
        search=[
            "sample__sample_number", "sample__order__order_number",
            "sample__order__patient__uhid", "sample__order__patient__first_name",
            "sample__order__patient__last_name", "test__name",
        ],
        ordering=("-id",),
        filter_field="status",
        filter_label="All statuses",
        filter_choices=LabResult.ResultStatus.choices,
        form_base=module_forms.LabResultForm,
        form_fields=("sample", "result_value", "numeric_value", "remarks"),
        creator=wf.save_lab_result,
        creator_on_edit=True,
        allow_delete=False,
        guard=wf.lab_result_guard,
        actions=[
            Action(
                "verify", "Verify", run=wf.act_verify_result, style="primary",
                visible=lambda o: o.status in (
                    LabResult.ResultStatus.ENTERED,
                    LabResult.ResultStatus.AMENDED,
                ),
            ),
        ],
        columns=[
            ("Sample", "sample.sample_number", "mono"),
            ("Patient", "sample.order.patient.full_name", None),
            ("Test", "test.name", None),
            ("Result", "result_value", None),
            ("Unit", "unit", None),
            ("Reference", "reference_range", None),
            ("Flag", result_flag, "flag"),
            ("Status", "status", "status"),
        ],
    ),
    Entity(
        key="lab-reports",
        model=LabReport,
        title="Lab Report",
        plural="Lab Reports",
        group="Laboratory",
        subtitle="Verify, finalize and print patient reports",
        select=("patient", "order"),
        search=PATIENT_SEARCH + ["report_number", "order__order_number"],
        ordering=("-report_date", "-id"),
        filter_field="status",
        filter_label="All statuses",
        filter_choices=LabReport.Status.choices,
        form_base=module_forms.LabReportForm,
        form_fields=("order", "clinical_summary", "report_notes"),
        creator=wf.create_lab_report,
        guard=wf.lab_report_guard,
        actions=[
            Action(
                "verify", "Verify", run=wf.act_verify_report, style="primary",
                visible=lambda o: o.status in (
                    LabReport.Status.DRAFT, LabReport.Status.READY
                ),
            ),
            Action(
                "finalize", "Finalize", run=wf.act_finalize_report,
                style="primary",
                confirm="Finalize this report? It will be locked.",
                visible=lambda o: o.status == LabReport.Status.VERIFIED,
            ),
            Action(
                "print", "Print", perm="view",
                link=lambda o: reverse(
                    "laboratory:lab_report_print", kwargs={"pk": o.pk}
                ),
                new_tab=True,
            ),
        ],
        columns=[
            ("Report no.", "report_number", "mono"),
            ("Patient", "patient.full_name", None),
            ("Order", "order.order_number", "mono"),
            ("Report date", "report_date", None),
            ("Status", "status", "status"),
        ],
    ),

    # ---- Lab setup -------------------------------------------------------------
    Entity(
        key="lab-tests",
        model=LabTest,
        title="Lab Test",
        plural="Lab Tests",
        group="Lab setup",
        subtitle="Tests offered, their price and normal ranges",
        select=("category", "sample_type"),
        search=["test_code", "name", "short_name", "category__name"],
        ordering=("name", "id"),
        filter_field="is_active",
        filter_label="Active & inactive",
        filter_choices=ACTIVE_CHOICES,
        filter_cast=cast_bool,
        form_exclude=("test_code",),
        inlines=[
            Inline(
                "ranges",
                "Normal / critical ranges",
                module_forms.line_formset(
                    LabTest,
                    LabReferenceRange,
                    fields=(
                        "gender", "age_min", "age_max", "normal_min",
                        "normal_max", "critical_low", "critical_high",
                        "normal_text",
                    ),
                ),
                hint="Results are flagged normal / abnormal / critical against these ranges.",
            ),
        ],
        columns=[
            ("Code", "test_code", "mono"),
            ("Test", "name", None),
            ("Category", "category.name", None),
            ("Sample", "sample_type.name", None),
            ("Unit", "unit", None),
            ("Price", "price", "num"),
            ("TAT (min)", "turnaround_time_minutes", "num"),
            ("Status", "is_active", "active"),
        ],
    ),
    Entity(
        key="lab-packages",
        model=LabPackage,
        title="Lab Package",
        plural="Lab Packages",
        group="Lab setup",
        subtitle="Bundles of tests sold together",
        search=["package_code", "name"],
        ordering=("name", "id"),
        filter_field="is_active",
        filter_label="Active & inactive",
        filter_choices=ACTIVE_CHOICES,
        filter_cast=cast_bool,
        form_exclude=("package_code",),
        inlines=[
            Inline(
                "tests",
                "Tests in this package",
                module_forms.line_formset(
                    LabPackage, LabPackageItem, fields=("test",)
                ),
            ),
        ],
        columns=[
            ("Code", "package_code", "mono"),
            ("Package", "name", None),
            ("Price", "price", "num"),
            ("Discount", "discount", "num"),
            ("Final price", "final_price", "num"),
            ("Status", "is_active", "active"),
        ],
    ),
    Entity(
        key="lab-categories",
        model=LabCategory,
        title="Lab Category",
        plural="Lab Categories",
        group="Lab setup",
        subtitle="Groups such as Haematology or Biochemistry",
        search=["name", "code"],
        ordering=("name",),
        filter_field="is_active",
        filter_label="Active & inactive",
        filter_choices=ACTIVE_CHOICES,
        filter_cast=cast_bool,
        columns=[
            ("Code", "code", "mono"),
            ("Name", "name", None),
            ("Description", "description", "trunc"),
            ("Status", "is_active", "active"),
        ],
    ),
    Entity(
        key="sample-types",
        model=SampleType,
        title="Sample Type",
        plural="Sample Types",
        group="Lab setup",
        subtitle="Blood, urine, swab ...",
        search=["name", "code"],
        ordering=("name",),
        filter_field="is_active",
        filter_label="Active & inactive",
        filter_choices=ACTIVE_CHOICES,
        filter_cast=cast_bool,
        columns=[
            ("Code", "code", "mono"),
            ("Name", "name", None),
            ("Description", "description", "trunc"),
            ("Status", "is_active", "active"),
        ],
    ),

    # ---- Pharmacy ----------------------------------------------------------------
    Entity(
        key="prescriptions",
        model=Prescription,
        title="Prescription",
        plural="Prescriptions",
        group="Pharmacy",
        subtitle="Medicines prescribed after an OPD consultation",
        select=("patient", "doctor__user", "opd_visit"),
        annotate=count_items,
        search=PATIENT_SEARCH + [
            "prescription_number", "opd_visit__visit_number",
            "doctor__user__first_name", "doctor__user__last_name",
        ],
        ordering=("-prescription_date", "-id"),
        filter_field="status",
        filter_label="All statuses",
        filter_choices=Prescription.Status.choices,
        form_base=module_forms.PrescriptionForm,
        form_exclude=("prescription_number", "patient", "doctor", "created_by"),
        before_save=wf.before_prescription,
        guard=wf.prescription_guard,
        inlines=[
            Inline(
                "items",
                "Medicines",
                module_forms.line_formset(
                    Prescription,
                    PrescriptionItem,
                    fields=(
                        "medicine", "dose", "frequency", "duration_value",
                        "duration_unit", "route", "quantity_prescribed",
                        "instructions",
                    ),
                ),
            ),
        ],
        actions=[
            Action(
                "dispense", "Dispense", perm="pharmacy.add_pharmacydispensing",
                link=lambda o: new_url("dispensing", prescription=o.pk),
                style="primary",
                visible=lambda o: o.status in (
                    Prescription.Status.ACTIVE,
                    Prescription.Status.PARTIALLY_DISPENSED,
                ),
            ),
            Action(
                "cancel", "Cancel", run=wf.act_cancel_prescription,
                confirm="Cancel this prescription?", style="danger",
                visible=lambda o: o.status in (
                    Prescription.Status.DRAFT, Prescription.Status.ACTIVE
                ),
            ),
        ],
        columns=[
            ("Rx no.", "prescription_number", "mono"),
            ("Patient", "patient.full_name", None),
            ("Doctor", lambda o: doctor_profile_name(o.doctor), None),
            ("Date", "prescription_date", None),
            ("Medicines", "item_count", "num"),
            ("Status", "status", "status"),
        ],
    ),
    Entity(
        key="dispensing",
        model=PharmacyDispensing,
        title="Dispensing",
        plural="Dispensing",
        group="Pharmacy",
        subtitle="Hand medicines to patients (earliest-expiry batch is chosen for you)",
        select=("patient", "prescription", "dispensed_by"),
        annotate=count_items,
        search=PATIENT_SEARCH + ["dispensing_number", "prescription__prescription_number"],
        ordering=("-id",),
        filter_field="status",
        filter_label="All statuses",
        filter_choices=PharmacyDispensing.Status.choices,
        form_base=module_forms.PharmacyDispensingForm,
        form_fields=("prescription", "notes"),
        after_save=wf.after_dispensing,
        guard=wf.dispensing_guard,
        edit_after_create=True,
        inlines=[
            Inline(
                "items",
                "Items to dispense",
                module_forms.line_formset(
                    PharmacyDispensing,
                    PharmacyDispensingItem,
                    fields=(
                        "prescription_item", "medicine_batch",
                        "quantity_dispensed", "discount",
                    ),
                    form=module_forms.DispensingLineForm,
                ),
                hint="Check the batches and quantities, then press Dispense on the list.",
                edit_only=True,
            ),
        ],
        actions=[
            Action(
                "dispense", "Dispense", run=wf.act_dispense, style="primary",
                confirm="Hand over these medicines and reduce stock?",
                visible=lambda o: o.status in (
                    PharmacyDispensing.Status.PENDING,
                    PharmacyDispensing.Status.PARTIALLY_DISPENSED,
                ),
            ),
            Action(
                "cancel", "Cancel", run=wf.act_cancel_dispensing,
                confirm="Cancel this dispensing?", style="danger",
                visible=lambda o: o.status == PharmacyDispensing.Status.PENDING,
            ),
        ],
        columns=[
            ("Dispensing no.", "dispensing_number", "mono"),
            ("Patient", "patient.full_name", None),
            ("Prescription", "prescription.prescription_number", "mono"),
            ("Items", "item_count", "num"),
            ("Dispensed", "dispensed_at", None),
            ("Status", "status", "status"),
        ],
    ),
    Entity(
        key="purchases",
        model=PharmacyPurchase,
        title="Purchase (GRN)",
        plural="Purchases (GRN)",
        group="Pharmacy",
        subtitle="Stock received from suppliers; stock is added when you press Receive",
        select=("supplier",),
        prefetch=("items",),
        annotate=count_items,
        search=["grn_number", "invoice_number", "supplier__name"],
        ordering=("-grn_date", "-id"),
        filter_field="status",
        filter_label="All statuses",
        filter_choices=PharmacyPurchase.Status.choices,
        form_fields=(
            "supplier", "grn_date", "invoice_number", "invoice_date",
            "payment_status", "notes",
        ),
        guard=wf.purchase_guard,
        inlines=[
            Inline(
                "items",
                "Items received",
                module_forms.line_formset(
                    PharmacyPurchase,
                    PharmacyPurchaseItem,
                    fields=(
                        "medicine", "batch_number", "manufacturing_date",
                        "expiry_date", "quantity_received", "purchase_price",
                        "selling_price", "gst_rate", "discount",
                    ),
                ),
            ),
        ],
        actions=[
            Action(
                "receive", "Receive stock", run=wf.act_receive_purchase,
                style="primary",
                confirm="Add these items to stock? This cannot be undone.",
                visible=lambda o: o.status == PharmacyPurchase.Status.DRAFT,
            ),
            Action(
                "paid", "Mark paid", run=wf.act_mark_paid,
                visible=lambda o: o.status == PharmacyPurchase.Status.RECEIVED
                and o.payment_status != PharmacyPurchase.PaymentStatus.PAID,
            ),
            Action(
                "cancel", "Cancel", run=wf.act_cancel_purchase,
                confirm="Cancel this purchase?", style="danger",
                visible=lambda o: o.status == PharmacyPurchase.Status.DRAFT,
            ),
        ],
        columns=[
            ("GRN no.", "grn_number", "mono"),
            ("Supplier", "supplier.name", None),
            ("GRN date", "grn_date", None),
            ("Invoice", "invoice_number", None),
            ("Items", "item_count", "num"),
            ("Total", "grand_total", "num"),
            ("Payment", "payment_status", "status"),
            ("Status", "status", "status"),
        ],
    ),
    Entity(
        key="purchase-returns",
        model=PharmacyPurchaseReturn,
        title="Purchase Return",
        plural="Purchase Returns",
        group="Pharmacy",
        subtitle="Goods sent back to a supplier",
        select=("supplier", "purchase"),
        prefetch=("items",),
        annotate=count_items,
        search=["return_number", "supplier__name", "purchase__grn_number"],
        ordering=("-return_date", "-id"),
        filter_field="status",
        filter_label="All statuses",
        filter_choices=PharmacyPurchaseReturn.Status.choices,
        form_base=module_forms.PurchaseReturnForm,
        form_fields=("purchase", "return_date", "reason"),
        guard=wf.purchase_return_guard,
        edit_after_create=True,
        inlines=[
            Inline(
                "items",
                "Items to return",
                module_forms.line_formset(
                    PharmacyPurchaseReturn,
                    PharmacyPurchaseReturnItem,
                    fields=(
                        "purchase_item", "medicine_batch", "quantity_returned",
                        "return_price", "reason",
                    ),
                    form=module_forms.PurchaseReturnLineForm,
                ),
                hint="Pick the purchase line; the stock batch is found for you.",
                edit_only=True,
            ),
        ],
        actions=[
            Action(
                "process", "Process return", run=wf.act_process_return,
                style="primary",
                confirm="Send these items back and reduce stock?",
                visible=lambda o: o.status == PharmacyPurchaseReturn.Status.DRAFT,
            ),
            Action(
                "cancel", "Cancel", run=wf.act_cancel_return,
                confirm="Cancel this return?", style="danger",
                visible=lambda o: o.status == PharmacyPurchaseReturn.Status.DRAFT,
            ),
        ],
        columns=[
            ("Return no.", "return_number", "mono"),
            ("Supplier", "supplier.name", None),
            ("GRN", "purchase.grn_number", "mono"),
            ("Date", "return_date", None),
            ("Items", "item_count", "num"),
            ("Status", "status", "status"),
        ],
    ),
    Entity(
        key="stock",
        model=MedicineBatch,
        title="Stock Batch",
        plural="Stock Batches",
        group="Pharmacy",
        subtitle="Medicine batches, expiry dates and quantities in hand",
        select=("medicine",),
        search=["batch_number", "medicine__name", "medicine__generic_name", "medicine__medicine_code"],
        ordering=("expiry_date", "medicine__name", "id"),
        filter_field="is_active",
        filter_label="Active & inactive",
        filter_choices=ACTIVE_CHOICES,
        filter_cast=cast_bool,
        form_base=module_forms.MedicineBatchForm,
        form_fields=(
            "medicine", "batch_number", "manufacturing_date", "expiry_date",
            "purchase_price", "selling_price", "quantity_received",
            "received_date", "is_active",
        ),
        after_save=wf.after_batch,
        columns=[
            ("Medicine", "medicine.name", None),
            ("Batch", "batch_number", "mono"),
            ("Expiry", "expiry_date", None),
            ("In stock", "available_quantity", "num"),
            ("Received", "quantity_received", "num"),
            ("Selling price", "selling_price", "num"),
            ("Expired", "is_expired", None),
            ("Status", "is_active", "active"),
        ],
    ),
    Entity(
        key="stock-ledger",
        model=StockTransaction,
        title="Stock Adjustment",
        plural="Stock Ledger",
        group="Pharmacy",
        subtitle="Every stock movement; add a count correction or write off expired / damaged stock",
        select=("medicine_batch__medicine", "created_by"),
        search=[
            "reference_number", "medicine_batch__batch_number",
            "medicine_batch__medicine__name",
        ],
        ordering=("-created_at", "-id"),
        filter_field="transaction_type",
        filter_label="All movements",
        filter_choices=StockTransaction.TransactionType.choices,
        form_base=wf.StockAdjustmentForm,
        form_fields=("medicine_batch", "transaction_type", "quantity", "notes"),
        creator=wf.create_stock_adjustment,
        allow_edit=False,
        allow_delete=False,
        columns=[
            ("When", "created_at", None),
            ("Medicine", "medicine_batch.medicine.name", None),
            ("Batch", "medicine_batch.batch_number", "mono"),
            ("Type", "get_transaction_type_display", None),
            ("Quantity", "quantity", "num"),
            ("Reference", "reference_number", "mono"),
            ("By", lambda o: person_name(o.created_by), None),
        ],
    ),

    # ---- Pharmacy setup -----------------------------------------------------------
    Entity(
        key="medicines",
        model=Medicine,
        title="Medicine",
        plural="Medicines",
        group="Pharmacy setup",
        subtitle="Medicine catalogue",
        select=("category", "manufacturer"),
        annotate=medicine_stock,
        search=["medicine_code", "name", "generic_name", "brand_name", "category__name"],
        ordering=("name", "id"),
        filter_field="dosage_form",
        filter_label="All forms",
        filter_choices=Medicine.DosageForm.choices,
        form_exclude=("medicine_code",),
        columns=[
            ("Code", "medicine_code", "mono"),
            ("Medicine", "name", None),
            ("Strength", "strength", None),
            ("Form", "get_dosage_form_display", None),
            ("Category", "category.name", None),
            ("In stock", lambda o: o.stock_total or 0, "num"),
            ("Reorder at", "reorder_level", "num"),
            ("Status", "is_active", "active"),
        ],
    ),
    Entity(
        key="medicine-categories",
        model=MedicineCategory,
        title="Medicine Category",
        plural="Medicine Categories",
        group="Pharmacy setup",
        subtitle="Antibiotics, analgesics ...",
        search=["name", "code"],
        ordering=("name",),
        filter_field="is_active",
        filter_label="Active & inactive",
        filter_choices=ACTIVE_CHOICES,
        filter_cast=cast_bool,
        columns=[
            ("Code", "code", "mono"),
            ("Name", "name", None),
            ("Description", "description", "trunc"),
            ("Status", "is_active", "active"),
        ],
    ),
    Entity(
        key="manufacturers",
        model=Manufacturer,
        title="Manufacturer",
        plural="Manufacturers",
        group="Pharmacy setup",
        subtitle="Medicine makers",
        search=["name", "code", "contact_person", "phone"],
        ordering=("name",),
        filter_field="is_active",
        filter_label="Active & inactive",
        filter_choices=ACTIVE_CHOICES,
        filter_cast=cast_bool,
        columns=[
            ("Code", "code", "mono"),
            ("Name", "name", None),
            ("Contact", "contact_person", None),
            ("Phone", "phone", None),
            ("Status", "is_active", "active"),
        ],
    ),
    Entity(
        key="suppliers",
        model=Supplier,
        title="Supplier",
        plural="Suppliers",
        group="Pharmacy setup",
        subtitle="Vendors medicines are bought from",
        search=["supplier_code", "name", "gstin", "contact_person", "phone", "city"],
        ordering=("name",),
        filter_field="is_active",
        filter_label="Active & inactive",
        filter_choices=ACTIVE_CHOICES,
        filter_cast=cast_bool,
        form_exclude=("supplier_code",),
        columns=[
            ("Code", "supplier_code", "mono"),
            ("Name", "name", None),
            ("GSTIN", "gstin", "mono"),
            ("Contact", "contact_person", None),
            ("Phone", "phone", None),
            ("City", "city", None),
            ("Status", "is_active", "active"),
        ],
    ),

    # ---- Setup (extra) ---------------------------------------------------------
    Entity(
        key="doctor-availability",
        model=DoctorAvailability,
        title="Doctor Availability",
        plural="Doctor Availability",
        group="Setup",
        subtitle="Weekly working hours of each doctor",
        select=("doctor__user",),
        search=["doctor__doctor_id", "doctor__user__first_name", "doctor__user__last_name"],
        ordering=("doctor__user__first_name", "day_of_week", "start_time"),
        filter_field="day_of_week",
        filter_label="Every day",
        filter_choices=[(str(n), label) for n, label in WEEKDAYS],
        filter_cast=int,
        columns=[
            ("Doctor", lambda o: doctor_profile_name(o.doctor), None),
            ("Day", lambda o: weekday_name(o.day_of_week), None),
            (
                "Hours",
                lambda o: f"{o.start_time:%I:%M %p} – {o.end_time:%I:%M %p}",
                None,
            ),
            ("Slot (min)", "consultation_duration", "num"),
            ("Max patients", "max_patients", "num"),
            ("Available", "is_available", "yesno"),
        ],
    ),

    # ---- Setup -----------------------------------------------------------
    Entity(
        key="doctors",
        model=Doctor,
        title="Doctor",
        plural="Doctors",
        group="Setup",
        subtitle="Doctor profiles and fees",
        select=("user", "department"),
        search=[
            "doctor_id", "user__first_name", "user__last_name",
            "specialization", "medical_registration_number", "phone",
            "department__name",
        ],
        ordering=("user__first_name", "user__last_name", "id"),
        filter_field="is_active",
        filter_label="Active & inactive",
        filter_choices=ACTIVE_CHOICES,
        filter_cast=cast_bool,
        form_base=portal_forms.DoctorForm,
        columns=[
            ("Doctor ID", "doctor_id", "mono"),
            ("Name", lambda o: doctor_profile_name(o), None),
            ("Specialization", "specialization", None),
            ("Department", "department.name", None),
            ("Phone", "phone", None),
            ("Consultation fee", "consultation_fee", "num"),
            ("Available", "is_available", "yesno"),
            ("Status", "is_active", "active"),
        ],
        form_exclude=(),
    ),
    Entity(
        key="schedules",
        model=DoctorSchedule,
        title="Doctor Schedule",
        plural="Doctor Schedules",
        group="Setup",
        subtitle="Weekly clinic timings",
        select=("doctor__user", "department"),
        search=[
            "doctor__doctor_id", "doctor__user__first_name",
            "doctor__user__last_name", "schedule_name", "room_name",
            "department__name",
        ],
        ordering=("doctor__user__first_name", "day_of_week", "start_time"),
        filter_field="day_of_week",
        filter_label="Every day",
        filter_choices=[(str(n), label) for n, label in WEEKDAYS],
        filter_cast=int,
        form_base=portal_forms.DoctorScheduleForm,
        columns=[
            ("Doctor", lambda o: doctor_profile_name(o.doctor), None),
            ("Schedule", "schedule_name", None),
            ("Day", lambda o: weekday_name(o.day_of_week), None),
            (
                "Timing",
                lambda o: f"{o.start_time:%I:%M %p} – {o.end_time:%I:%M %p}",
                None,
            ),
            ("Room", "room_name", None),
            ("Max patients", "max_patients", "num"),
            ("Slot (min)", "consultation_duration", "num"),
            ("Status", "is_active", "active"),
        ],
    ),
    Entity(
        key="hospitals",
        model=Hospital,
        title="Hospital",
        plural="Hospitals",
        group="Setup",
        subtitle="Hospital profile used on reports",
        search=["name", "code", "city", "phone", "email"],
        ordering=("name", "id"),
        filter_field="is_active",
        filter_label="Active & inactive",
        filter_choices=ACTIVE_CHOICES,
        filter_cast=cast_bool,
        columns=[
            ("Code", "code", "mono"),
            ("Name", "name", None),
            ("City", "city", None),
            ("Phone", "phone", None),
            ("Email", "email", None),
            ("Status", "is_active", "active"),
        ],
    ),
    Entity(
        key="departments",
        model=Department,
        title="Department",
        plural="Departments",
        group="Setup",
        subtitle="Clinical and support departments",
        select=("hospital", "head"),
        search=["name", "code", "hospital__name"],
        ordering=("hospital__name", "name"),
        filter_field="is_active",
        filter_label="Active & inactive",
        filter_choices=ACTIVE_CHOICES,
        filter_cast=cast_bool,
        columns=[
            ("Code", "code", "mono"),
            ("Name", "name", None),
            ("Hospital", "hospital.name", None),
            ("Head", lambda o: person_name(o.head), None),
            ("Phone", "phone", None),
            ("Status", "is_active", "active"),
        ],
    ),
    Entity(
        key="buildings",
        model=Building,
        title="Building",
        plural="Buildings",
        group="Setup",
        subtitle="Buildings of the hospital",
        select=("hospital",),
        search=["name", "code", "hospital__name"],
        ordering=("hospital__name", "name"),
        filter_field="is_active",
        filter_label="Active & inactive",
        filter_choices=ACTIVE_CHOICES,
        filter_cast=cast_bool,
        columns=[
            ("Code", "code", "mono"),
            ("Name", "name", None),
            ("Hospital", "hospital.name", None),
            ("Status", "is_active", "active"),
        ],
    ),
    Entity(
        key="floors",
        model=Floor,
        title="Floor",
        plural="Floors",
        group="Setup",
        subtitle="Floors inside each building",
        select=("building",),
        search=["name", "building__name"],
        ordering=("building__name", "number"),
        filter_field="is_active",
        filter_label="Active & inactive",
        filter_choices=ACTIVE_CHOICES,
        filter_cast=cast_bool,
        columns=[
            ("Name", "name", None),
            ("Number", "number", "num"),
            ("Building", "building.name", None),
            ("Status", "is_active", "active"),
        ],
    ),
    Entity(
        key="wards",
        model=Ward,
        title="Ward",
        plural="Wards",
        group="Setup",
        subtitle="Inpatient wards",
        select=("floor", "department"),
        search=["name", "code", "department__name", "floor__name"],
        ordering=("name", "id"),
        filter_field="ward_type",
        filter_label="All ward types",
        filter_choices=Ward.WardType.choices,
        columns=[
            ("Code", "code", "mono"),
            ("Name", "name", None),
            ("Type", "get_ward_type_display", None),
            ("Floor", "floor.name", None),
            ("Department", "department.name", None),
            ("Capacity", "capacity", "num"),
            ("Status", "is_active", "active"),
        ],
    ),
    Entity(
        key="rooms",
        model=Room,
        title="Room",
        plural="Rooms",
        group="Setup",
        subtitle="Rooms inside wards",
        select=("ward",),
        search=["room_number", "ward__name"],
        ordering=("ward__name", "room_number"),
        filter_field="room_type",
        filter_label="All room types",
        filter_choices=Room.RoomType.choices,
        columns=[
            ("Room no.", "room_number", "mono"),
            ("Ward", "ward.name", None),
            ("Type", "get_room_type_display", None),
            ("Floor no.", "floor_number", "num"),
            ("Capacity", "capacity", "num"),
            ("Status", "is_active", "active"),
        ],
    ),
    Entity(
        key="beds",
        model=Bed,
        title="Bed",
        plural="Beds",
        group="Setup",
        subtitle="Beds and their current availability",
        select=("room__ward",),
        search=["bed_number", "room__room_number", "room__ward__name"],
        ordering=("room__ward__name", "room__room_number", "bed_number"),
        filter_field="status",
        filter_label="All statuses",
        filter_choices=Bed.Status.choices,
        columns=[
            ("Bed no.", "bed_number", "mono"),
            ("Room", "room.room_number", None),
            ("Ward", "room.ward.name", None),
            ("Type", "get_bed_type_display", None),
            ("Charge / day", "daily_charge", "num"),
            ("Status", "status", "status"),
        ],
    ),

    # ---- Administration --------------------------------------------------
    Entity(
        key="users",
        model=User,
        title="User",
        plural="Users",
        group="Administration",
        subtitle="Staff logins and roles",
        search=[
            "username", "first_name", "last_name", "email",
            "employee_id", "phone", "department",
        ],
        ordering=("username",),
        filter_field="role",
        filter_label="All roles",
        filter_choices=User.Role.choices,
        form_base=portal_forms.UserForm,
        form_fields=(
            "username", "first_name", "last_name", "email", "role",
            "employee_id", "phone", "department", "is_active",
        ),
        guard=user_guard,
        columns=[
            ("Username", "username", "mono"),
            ("Name", lambda o: o.get_full_name() or None, None),
            ("Role", "get_role_display", None),
            ("Department", "department", None),
            ("Phone", "phone", None),
            ("Status", "is_active", "active"),
        ],
    ),
]

ENTITIES = {entity.key: entity for entity in ENTITY_LIST}

GROUP_ORDER = [
    "Clinical",
    "Inpatient",
    "Laboratory",
    "Lab setup",
    "Pharmacy",
    "Pharmacy setup",
    "Setup",
    "Administration",
]
