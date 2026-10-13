"""Hospital portal: dashboard and searchable list pages.

Read-only front end that sits on top of the existing apps. Access to every
section follows the normal Django model permissions, so the role groups
created by ``manage.py setup_roles`` decide who sees what.
"""

from datetime import date, datetime, time

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from appointments.models import Appointment
from hospitals.models import Bed, Hospital
from ipd.models import IPDAdmission
from laboratory.models import LabOrder
from opd.models import OPDVisit
from patients.models import Patient


PAGE_SIZE = 25


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def person_name(user):
    """Readable name for a user, falling back to the username."""
    if user is None:
        return None
    return user.get_full_name() or user.get_username()


def doctor_profile_name(doctor):
    """Name for a doctors.Doctor row (the name lives on its user)."""
    if doctor is None:
        return None
    name = person_name(doctor.user)
    return f"Dr. {name}" if name else None


def user_doctor_name(user):
    name = person_name(user)
    return f"Dr. {name}" if name else None


def format_value(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%d %b %Y, %I:%M %p")
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    if isinstance(value, time):
        return value.strftime("%I:%M %p")
    return str(value)


def resolve(obj, accessor):
    """Follow a dotted attribute path (or call a function) on ``obj``."""
    if callable(accessor):
        return accessor(obj)

    current = obj
    for part in accessor.split("."):
        if current is None:
            return None
        current = getattr(current, part, None)
        if callable(current):
            current = current()
    return current


def build_cell(obj, accessor, kind=None):
    """Turn one model attribute into something the table template can draw."""
    if kind == "status":
        raw = getattr(obj, accessor)
        display = getattr(obj, f"get_{accessor}_display")()
        return {"text": display, "badge": f"s-{str(raw).lower()}"}

    if kind == "active":
        on = bool(getattr(obj, accessor))
        return {
            "text": "Active" if on else "Inactive",
            "badge": "s-active" if on else "s-inactive",
        }

    if kind == "urgent":
        on = bool(getattr(obj, accessor))
        return {
            "text": "STAT" if on else "Routine",
            "badge": "s-stat" if on else "s-routine",
        }

    text = format_value(resolve(obj, accessor))

    if kind == "trunc" and len(text) > 60:
        text = text[:57] + "…"

    return {"text": text, "kind": kind}


def admin_change_url(obj, user):
    """Link to the admin edit page, only for staff who may change the row."""
    opts = obj._meta

    if not (
        user.is_staff
        and user.has_perm(f"{opts.app_label}.change_{opts.model_name}")
    ):
        return None

    try:
        return reverse(
            f"admin:{opts.app_label}_{opts.model_name}_change",
            args=[obj.pk],
        )
    except NoReverseMatch:
        return None


def make_table(objects, columns, user):
    """columns: list of (label, accessor, kind) tuples."""
    headers = [
        {"label": label, "num": kind == "num"}
        for label, _accessor, kind in columns
    ]

    rows = []
    for obj in objects:
        rows.append(
            {
                "cells": [
                    build_cell(obj, accessor, kind)
                    for _label, accessor, kind in columns
                ],
                "url": admin_change_url(obj, user),
            }
        )

    return {
        "headers": headers,
        "rows": rows,
        "has_links": any(row["url"] for row in rows),
    }


# ---------------------------------------------------------------------------
# Navigation / shared context
# ---------------------------------------------------------------------------

NAV_ITEMS = [
    ("dashboard", "Dashboard", "portal:dashboard", None),
    ("patients", "Patients", "portal:list", "patients.view_patient"),
    ("appointments", "Appointments", "portal:list", "appointments.view_appointment"),
    ("opd", "OPD Visits", "portal:list", "opd.view_opdvisit"),
    ("ipd", "IPD Admissions", "portal:list", "ipd.view_ipdadmission"),
    ("lab-orders", "Lab Orders", "portal:list", "laboratory.view_laborder"),
]


def base_context(request, active):
    hospital = (
        Hospital.objects
        .filter(is_active=True)
        .order_by("id")
        .first()
    )

    nav = []
    for key, label, url_name, perm in NAV_ITEMS:
        if perm and not request.user.has_perm(perm):
            continue
        if key == "dashboard":
            url = reverse(url_name)
        else:
            url = reverse(url_name, kwargs={"section": key})
        nav.append({"key": key, "label": label, "url": url})

    return {
        "hospital": hospital,
        "hospital_name": hospital.name if hospital else "Hospital Management",
        "nav": nav,
        "active": active,
        "today": timezone.localdate(),
    }


# ---------------------------------------------------------------------------
# Section configuration (list pages)
# ---------------------------------------------------------------------------

PATIENT_SEARCH = [
    "patient__uhid",
    "patient__first_name",
    "patient__last_name",
    "patient__phone",
]

SECTIONS = {
    "patients": {
        "title": "Patients",
        "subtitle": "Registered patients",
        "perm": "patients.view_patient",
        "queryset": lambda: Patient.objects.all(),
        "ordering": ("-registration_date", "-id"),
        "search": [
            "uhid", "first_name", "middle_name", "last_name",
            "phone", "email", "city",
        ],
        "filter_field": "gender",
        "filter_label": "All genders",
        "filter_choices": Patient.Gender.choices,
        "columns": [
            ("UHID", "uhid", "mono"),
            ("Patient", "full_name", None),
            ("Gender", "get_gender_display", None),
            ("Blood group", "get_blood_group_display", None),
            ("Phone", "phone", None),
            ("City", "city", None),
            ("Registered", "registration_date", None),
            ("Status", "is_active", "active"),
        ],
    },
    "appointments": {
        "title": "Appointments",
        "subtitle": "Booked, ongoing and past appointments",
        "perm": "appointments.view_appointment",
        "queryset": lambda: Appointment.objects.select_related(
            "patient", "doctor__user", "department"
        ),
        "ordering": ("-appointment_date", "start_time", "-id"),
        "search": PATIENT_SEARCH + [
            "appointment_number",
            "doctor__user__first_name",
            "doctor__user__last_name",
            "department__name",
        ],
        "filter_field": "status",
        "filter_label": "All statuses",
        "filter_choices": Appointment.Status.choices,
        "columns": [
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
    },
    "opd": {
        "title": "OPD Visits",
        "subtitle": "Outpatient visits and consultations",
        "perm": "opd.view_opdvisit",
        "queryset": lambda: OPDVisit.objects.select_related(
            "patient", "doctor__user", "department"
        ),
        "ordering": ("-visit_date", "-id"),
        "search": PATIENT_SEARCH + [
            "visit_number",
            "doctor__user__first_name",
            "doctor__user__last_name",
            "department__name",
            "chief_complaint",
        ],
        "filter_field": "status",
        "filter_label": "All statuses",
        "filter_choices": OPDVisit.Status.choices,
        "columns": [
            ("Visit no.", "visit_number", "mono"),
            ("Patient", "patient.full_name", None),
            ("Doctor", lambda o: doctor_profile_name(o.doctor), None),
            ("Department", "department.name", None),
            ("Visit date", "visit_date", None),
            ("Complaint", "chief_complaint", "trunc"),
            ("Status", "status", "status"),
        ],
    },
    "ipd": {
        "title": "IPD Admissions",
        "subtitle": "Inpatient admissions and bed allocation",
        "perm": "ipd.view_ipdadmission",
        "queryset": lambda: IPDAdmission.objects.select_related(
            "patient", "doctor", "ward", "room", "bed"
        ),
        "ordering": ("-admission_date", "-id"),
        "search": PATIENT_SEARCH + [
            "admission_number",
            "doctor__first_name",
            "doctor__last_name",
            "ward__name",
            "room__room_number",
            "bed__bed_number",
        ],
        "filter_field": "status",
        "filter_label": "All statuses",
        "filter_choices": IPDAdmission.Status.choices,
        "columns": [
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
    },
    "lab-orders": {
        "title": "Lab Orders",
        "subtitle": "Laboratory orders and their progress",
        "perm": "laboratory.view_laborder",
        "queryset": lambda: LabOrder.objects.select_related(
            "patient", "doctor"
        ),
        "ordering": ("-order_date", "-id"),
        "search": PATIENT_SEARCH + [
            "order_number",
            "doctor__first_name",
            "doctor__last_name",
        ],
        "filter_field": "status",
        "filter_label": "All statuses",
        "filter_choices": LabOrder.Status.choices,
        "columns": [
            ("Order no.", "order_number", "mono"),
            ("Patient", "patient.full_name", None),
            ("Ordered by", lambda o: user_doctor_name(o.doctor), None),
            ("Ordered on", "order_date", None),
            ("Priority", "priority", "urgent"),
            ("Amount", "total_amount", "num"),
            ("Status", "status", "status"),
        ],
    },
}


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@login_required
def section_list(request, section):
    config = SECTIONS.get(section)

    if config is None:
        raise Http404("Unknown section.")

    if not request.user.has_perm(config["perm"]):
        raise PermissionDenied

    queryset = config["queryset"]()

    # --- search: every word must match at least one of the search fields ---
    query = request.GET.get("q", "").strip()

    if query:
        for term in query.split():
            clause = Q()
            for field in config["search"]:
                clause |= Q(**{f"{field}__icontains": term})
            queryset = queryset.filter(clause)

    # --- single dropdown filter (status / gender) ---
    selected = request.GET.get("filter", "").strip()
    valid_values = {value for value, _label in config["filter_choices"]}

    if selected in valid_values:
        queryset = queryset.filter(**{config["filter_field"]: selected})
    else:
        selected = ""

    queryset = queryset.order_by(*config["ordering"])

    paginator = Paginator(queryset, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)

    context = base_context(request, section)
    context.update(
        {
            "title": config["title"],
            "subtitle": config["subtitle"],
            "table": make_table(page.object_list, config["columns"], request.user),
            "page": page,
            "total": paginator.count,
            "query": query,
            "selected": selected,
            "filter_label": config["filter_label"],
            "filter_choices": config["filter_choices"],
            "querystring": params.urlencode(),
        }
    )

    return render(request, "portal/list.html", context)


@login_required
def dashboard(request):
    user = request.user
    today = timezone.localdate()

    stats = []
    tables = {}

    if user.has_perm("patients.view_patient"):
        stats.append(
            {
                "label": "Active patients",
                "value": Patient.objects.filter(is_active=True).count(),
                "note": (
                    f"{Patient.objects.filter(registration_date__date=today).count()}"
                    " registered today"
                ),
                "url": reverse("portal:list", kwargs={"section": "patients"}),
            }
        )

    if user.has_perm("appointments.view_appointment"):
        todays = Appointment.objects.filter(appointment_date=today)
        stats.append(
            {
                "label": "Appointments today",
                "value": todays.count(),
                "note": (
                    f"{todays.filter(status=Appointment.Status.CHECKED_IN).count()}"
                    " checked in"
                ),
                "url": reverse("portal:list", kwargs={"section": "appointments"}),
            }
        )

        tables["appointments"] = make_table(
            todays.select_related("patient", "doctor__user")
            .order_by("start_time", "id")[:8],
            [
                ("Token", "token_number", "num"),
                ("Patient", "patient.full_name", None),
                ("Doctor", lambda o: doctor_profile_name(o.doctor), None),
                ("Time", "start_time", None),
                ("Status", "status", "status"),
            ],
            user,
        )

    if user.has_perm("opd.view_opdvisit"):
        visits = OPDVisit.objects.filter(visit_date=today)
        stats.append(
            {
                "label": "OPD visits today",
                "value": visits.count(),
                "note": (
                    f"{visits.filter(status=OPDVisit.Status.WAITING).count()}"
                    " waiting"
                ),
                "url": reverse("portal:list", kwargs={"section": "opd"}),
            }
        )

    if user.has_perm("ipd.view_ipdadmission"):
        admitted = IPDAdmission.objects.filter(
            status=IPDAdmission.Status.ADMITTED
        )
        stats.append(
            {
                "label": "Admitted inpatients",
                "value": admitted.count(),
                "note": (
                    f"{admitted.filter(admission_date__date=today).count()}"
                    " admitted today"
                ),
                "url": reverse("portal:list", kwargs={"section": "ipd"}),
            }
        )

        tables["admissions"] = make_table(
            admitted.select_related("patient", "ward", "bed")
            .order_by("-admission_date")[:6],
            [
                ("Admission no.", "admission_number", "mono"),
                ("Patient", "patient.full_name", None),
                ("Ward", "ward.name", None),
                ("Bed", "bed.bed_number", None),
                ("Admitted on", "admission_date", None),
            ],
            user,
        )

    if user.has_perm("hospitals.view_bed"):
        total_beds = Bed.objects.count()
        available_beds = Bed.objects.filter(
            status=Bed.Status.AVAILABLE
        ).count()
        stats.append(
            {
                "label": "Beds available",
                "value": f"{available_beds} / {total_beds}",
                "note": f"{total_beds - available_beds} in use or unavailable",
                "url": None,
            }
        )

    if user.has_perm("laboratory.view_laborder"):
        open_orders = LabOrder.objects.exclude(
            status__in=[
                LabOrder.Status.DRAFT,
                LabOrder.Status.COMPLETED,
                LabOrder.Status.CANCELLED,
            ]
        )
        stats.append(
            {
                "label": "Open lab orders",
                "value": open_orders.count(),
                "note": f"{open_orders.filter(priority=True).count()} urgent (STAT)",
                "url": reverse("portal:list", kwargs={"section": "lab-orders"}),
            }
        )

    context = base_context(request, "dashboard")
    context.update(
        {
            "stats": stats,
            "appointments_table": tables.get("appointments"),
            "admissions_table": tables.get("admissions"),
            "display_name": person_name(user),
        }
    )

    return render(request, "portal/dashboard.html", context)
