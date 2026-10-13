"""One place that describes every section of the portal.

Each ``Entity`` knows its model, how to list it, and how to build its
add/edit form. The generic views in ``views.py`` do the rest.
"""

from django.contrib.auth import get_user_model
from django.db.models import Max
from django.forms import modelform_factory

from appointments.models import Appointment
from doctors.models import Doctor, DoctorSchedule
from hospitals.models import Bed, Building, Department, Floor, Hospital, Room, Ward
from ipd.models import IPDAdmission
from laboratory.models import LabOrder
from laboratory.services import update_order_total
from opd.models import OPDVisit
from patients.models import Patient

from . import forms as portal_forms
from .utils import (
    WEEKDAYS,
    doctor_profile_name,
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
        filter_field=None,
        filter_label="All",
        filter_choices=(),
        filter_cast=None,
        form_base=None,
        form_fields=None,
        form_exclude=(),
        inline=None,
        inline_title="",
        before_save=None,
        after_save=None,
        guard=None,
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
        self.filter_field = filter_field
        self.filter_label = filter_label
        self.filter_choices = list(filter_choices)
        self.filter_cast = filter_cast
        self.form_base = form_base or portal_forms.PortalForm
        self.form_fields = form_fields
        self.form_exclude = tuple(form_exclude)
        self.inline = inline            # callable(extra) -> formset class
        self.inline_title = inline_title
        self.before_save = before_save  # callable(instance, request)
        self.after_save = after_save    # callable(instance)
        self.guard = guard              # callable(obj, request, action) -> error or None
        self._form_class = None

    # -- permissions ------------------------------------------------------
    def perm(self, action):
        opts = self.model._meta
        return f"{opts.app_label}.{action}_{opts.model_name}"

    # -- data ---------------------------------------------------------------
    def queryset(self):
        queryset = self.model.objects.all()

        # select_related() with no arguments would follow every FK, so only
        # call it when this section names specific relations.
        if self.select:
            queryset = queryset.select_related(*self.select)

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


def refresh_lab_total(order):
    update_order_total(order)


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
        select=("patient", "doctor__user", "department"),
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
        select=("patient", "doctor__user", "department"),
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
        group="Clinical",
        subtitle="Laboratory orders and their progress",
        select=("patient", "doctor"),
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
        inline=portal_forms.lab_item_formset,
        inline_title="Tests",
        after_save=refresh_lab_total,
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

GROUP_ORDER = ["Clinical", "Setup", "Administration"]
