"""Hospital portal: dashboard, searchable lists and add / edit / delete pages.

Everything is driven by ``registry.ENTITIES``. Access to each action follows
the normal Django model permissions (view / add / change / delete), so the
role groups created by ``manage.py setup_roles`` decide who can do what.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import ProtectedError, Q, RestrictedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from appointments.models import Appointment
from hospitals.models import Bed, Hospital
from ipd.models import IPDAdmission
from laboratory.models import LabOrder
from opd.models import OPDVisit
from patients.models import Patient

from .registry import ENTITIES, GROUP_ORDER
from .utils import build_cell, doctor_profile_name, person_name


PAGE_SIZE = 25


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_entity(section):
    entity = ENTITIES.get(section)

    if entity is None:
        raise Http404("Unknown section.")

    return entity


def require(user, perm):
    if not user.has_perm(perm):
        raise PermissionDenied


def list_url(entity):
    return reverse("portal:list", kwargs={"section": entity.key})


def make_table(objects, columns, user=None, entity=None):
    """columns: list of (label, accessor, kind) tuples."""
    headers = [
        {"label": label, "num": kind == "num"}
        for label, _accessor, kind in columns
    ]

    can_edit = bool(entity and user and user.has_perm(entity.perm("change")))
    can_delete = bool(entity and user and user.has_perm(entity.perm("delete")))

    rows = []
    for obj in objects:
        edit_url = delete_url = None

        if can_edit:
            edit_url = reverse(
                "portal:edit", kwargs={"section": entity.key, "pk": obj.pk}
            )
        if can_delete:
            delete_url = reverse(
                "portal:delete", kwargs={"section": entity.key, "pk": obj.pk}
            )

        rows.append(
            {
                "cells": [
                    build_cell(obj, accessor, kind)
                    for _label, accessor, kind in columns
                ],
                "edit_url": edit_url,
                "delete_url": delete_url,
            }
        )

    return {
        "headers": headers,
        "rows": rows,
        "has_actions": can_edit or can_delete,
    }


def base_context(request, active):
    hospital = (
        Hospital.objects
        .filter(is_active=True)
        .order_by("id")
        .first()
    )

    groups = []
    for group in GROUP_ORDER:
        items = [
            {
                "key": entity.key,
                "label": entity.plural,
                "url": list_url(entity),
            }
            for entity in ENTITIES.values()
            if entity.group == group
            and request.user.has_perm(entity.perm("view"))
        ]
        if items:
            groups.append({"title": group, "items": items})

    return {
        "hospital": hospital,
        "hospital_name": hospital.name if hospital else "Hospital Management",
        "nav_groups": groups,
        "active": active,
        "today": timezone.localdate(),
    }


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@login_required
def entity_list(request, section):
    entity = get_entity(section)
    require(request.user, entity.perm("view"))

    queryset = entity.queryset()

    # --- search: every word must match at least one of the search fields ---
    query = request.GET.get("q", "").strip()

    if query:
        for term in query.split():
            clause = Q()
            for field in entity.search:
                clause |= Q(**{f"{field}__icontains": term})
            queryset = queryset.filter(clause)

    # --- single dropdown filter (status / gender / active ...) ---
    selected = request.GET.get("filter", "").strip()
    valid_values = {value for value, _label in entity.filter_choices}

    if entity.filter_field and selected in valid_values:
        value = entity.filter_cast(selected) if entity.filter_cast else selected
        queryset = queryset.filter(**{entity.filter_field: value})
    else:
        selected = ""

    queryset = queryset.order_by(*entity.ordering)

    paginator = Paginator(queryset, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)

    context = base_context(request, entity.key)
    context.update(
        {
            "entity": entity,
            "title": entity.plural,
            "subtitle": entity.subtitle,
            "table": make_table(
                page.object_list, entity.columns, request.user, entity
            ),
            "page": page,
            "total": paginator.count,
            "query": query,
            "selected": selected,
            "can_add": request.user.has_perm(entity.perm("add")),
            "new_url": reverse("portal:new", kwargs={"section": entity.key}),
            "querystring": params.urlencode(),
        }
    )

    return render(request, "portal/list.html", context)


# ---------------------------------------------------------------------------
# Add / edit
# ---------------------------------------------------------------------------

@login_required
def entity_form(request, section, pk=None):
    entity = get_entity(section)

    obj = get_object_or_404(entity.model, pk=pk) if pk is not None else None

    action = "change" if obj is not None else "add"
    require(request.user, entity.perm(action))

    if obj is not None and entity.guard:
        problem = entity.guard(obj, request, "change")
        if problem:
            messages.error(request, problem)
            return redirect(list_url(entity))

    is_post = request.method == "POST"
    data = request.POST if is_post else None
    files = request.FILES if is_post else None

    form = entity.get_form_class()(
        data, files, instance=obj, request=request
    )

    formset = None
    if entity.inline:
        formset_class = entity.inline(extra=2 if obj is not None else 5)
        formset = formset_class(
            data, files, instance=form.instance, prefix="lines"
        )

    if is_post:
        form_ok = form.is_valid()
        formset_ok = formset.is_valid() if formset is not None else True

        if form_ok and formset_ok:
            try:
                with transaction.atomic():
                    instance = form.save(commit=False)

                    if (
                        obj is None
                        and hasattr(instance, "created_by_id")
                        and instance.created_by_id is None
                    ):
                        instance.created_by = request.user

                    if entity.before_save:
                        entity.before_save(instance, request)

                    instance.save()
                    form.save_m2m()

                    if formset is not None:
                        formset.save()

                    if entity.after_save:
                        entity.after_save(instance)

            except ValidationError as exc:
                # Model-level checks that only run inside save().
                for message in exc.messages:
                    form.add_error(None, message)
            else:
                messages.success(
                    request,
                    f"{entity.title} “{instance}” was "
                    f"{'updated' if obj is not None else 'created'}.",
                )
                return redirect(list_url(entity))

    context = base_context(request, entity.key)
    context.update(
        {
            "entity": entity,
            "form": form,
            "formset": formset,
            "inline_title": entity.inline_title,
            "page_title": (
                f"Edit {entity.title}" if obj is not None
                else f"New {entity.title}"
            ),
            "submit_label": "Save changes" if obj is not None else "Create",
            "cancel_url": list_url(entity),
        }
    )

    return render(request, "portal/form.html", context)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@login_required
def entity_delete(request, section, pk):
    entity = get_entity(section)
    obj = get_object_or_404(entity.model, pk=pk)

    require(request.user, entity.perm("delete"))

    if entity.guard:
        problem = entity.guard(obj, request, "delete")
        if problem:
            messages.error(request, problem)
            return redirect(list_url(entity))

    if request.method == "POST":
        label = str(obj)

        try:
            obj.delete()
        except (ProtectedError, RestrictedError):
            messages.error(
                request,
                f"“{label}” cannot be deleted because other records depend "
                "on it. Mark it inactive instead.",
            )
        else:
            messages.success(request, f"{entity.title} “{label}” was deleted.")

        return redirect(list_url(entity))

    context = base_context(request, entity.key)
    context.update(
        {
            "entity": entity,
            "object": obj,
            "cancel_url": list_url(entity),
        }
    )

    return render(request, "portal/confirm_delete.html", context)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

QUICK_ACTIONS = [
    ("patients", "New patient"),
    ("appointments", "Book appointment"),
    ("opd", "New OPD visit"),
    ("ipd", "Admit patient"),
    ("lab-orders", "New lab order"),
]


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
                "url": reverse("portal:list", kwargs={"section": "beds"}),
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

    quick_actions = [
        {
            "label": label,
            "url": reverse("portal:new", kwargs={"section": key}),
        }
        for key, label in QUICK_ACTIONS
        if user.has_perm(ENTITIES[key].perm("add"))
    ]

    context = base_context(request, "dashboard")
    context.update(
        {
            "stats": stats,
            "quick_actions": quick_actions,
            "appointments_table": tables.get("appointments"),
            "admissions_table": tables.get("admissions"),
            "display_name": person_name(user),
        }
    )

    return render(request, "portal/dashboard.html", context)
