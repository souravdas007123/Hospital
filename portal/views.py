"""Hospital portal: dashboard, searchable lists and add / edit / delete pages.

Everything is driven by ``registry.ENTITIES``. Access to each action follows
the normal Django model permissions (view / add / change / delete), so the
role groups created by ``manage.py setup_roles`` decide who can do what.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from datetime import timedelta

from django.db.models import (
    DecimalField,
    F,
    ProtectedError,
    Q,
    RestrictedError,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from appointments.models import Appointment
from hospitals.models import Bed, Hospital
from ipd.models import IPDAdmission
from laboratory.models import LabOrder, LabResult, LabSample
from opd.models import OPDVisit
from patients.models import Patient
from pharmacy.models import Medicine, MedicineBatch, Prescription

from .lookups import LOOKUPS, search as lookup_search
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


def make_table(objects, columns, user=None, entity=None, request=None):
    """columns: list of (label, accessor, kind) tuples."""
    headers = [
        {"label": label, "num": kind == "num"}
        for label, _accessor, kind in columns
    ]

    can_edit = bool(
        entity and user and entity.allow_edit
        and user.has_perm(entity.perm("change"))
    )
    can_delete = bool(
        entity and user and entity.allow_delete
        and user.has_perm(entity.perm("delete"))
    )

    # Row buttons this user may use at all (permission is checked once).
    actions = []
    if entity and user:
        actions = [
            action for action in entity.actions
            if user.has_perm(entity.action_perm(action))
        ]

    def blocked(obj, kind):
        if entity.guard is None:
            return False
        return entity.guard(obj, request, kind) is not None

    rows = []
    for obj in objects:
        edit_url = delete_url = None
        buttons = []

        if can_edit and not blocked(obj, "change"):
            edit_url = reverse(
                "portal:edit", kwargs={"section": entity.key, "pk": obj.pk}
            )
        if can_delete and not blocked(obj, "delete"):
            delete_url = reverse(
                "portal:delete", kwargs={"section": entity.key, "pk": obj.pk}
            )

        for action in actions:
            if action.visible and not action.visible(obj):
                continue

            if action.link:
                buttons.append(
                    {
                        "label": action.label,
                        "href": action.link(obj),
                        "style": action.style,
                        "new_tab": action.new_tab,
                    }
                )
            else:
                buttons.append(
                    {
                        "label": action.label,
                        "href": reverse(
                            "portal:action",
                            kwargs={
                                "section": entity.key,
                                "pk": obj.pk,
                                "action": action.key,
                            },
                        ),
                        "style": action.style,
                        "confirm": action.confirm,
                        "post": action.form is None,
                    }
                )

        rows.append(
            {
                "cells": [
                    build_cell(obj, accessor, kind)
                    for _label, accessor, kind in columns
                ],
                "edit_url": edit_url,
                "delete_url": delete_url,
                "buttons": buttons,
            }
        )

    return {
        "headers": headers,
        "rows": rows,
        "has_actions": can_edit or can_delete or any(r["buttons"] for r in rows),
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
            groups.append(
                {
                    "title": group,
                    "items": items,
                    "open": group == "Clinical"
                    or any(item["key"] == active for item in items),
                }
            )

    patient_search_url = (
        reverse("portal:list", kwargs={"section": "patients"})
        if request.user.has_perm("patients.view_patient")
        else None
    )

    return {
        "patient_search_url": patient_search_url,
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
                page.object_list, entity.columns, request.user, entity, request
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

def edit_url(entity, obj):
    return reverse("portal:edit", kwargs={"section": entity.key, "pk": obj.pk})


@login_required
def entity_form(request, section, pk=None):
    entity = get_entity(section)

    obj = get_object_or_404(entity.model, pk=pk) if pk is not None else None

    action = "change" if obj is not None else "add"
    require(request.user, entity.perm(action))

    if obj is not None and not entity.allow_edit:
        messages.error(
            request,
            f"{entity.plural} are a permanent record and cannot be edited.",
        )
        return redirect(list_url(entity))

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

    formsets = []
    for inline in entity.inlines:
        if inline.edit_only and obj is None:
            continue

        formset_class = inline.factory(extra=2 if obj is not None else 5)
        formsets.append(
            {
                "inline": inline,
                "formset": formset_class(
                    data, files, instance=form.instance, prefix=inline.prefix
                ),
            }
        )

    if is_post:
        form_ok = form.is_valid()
        formsets_ok = all(item["formset"].is_valid() for item in formsets)

        if form_ok and formsets_ok:
            created = obj is None

            try:
                with transaction.atomic():
                    if entity.creator and (created or entity.creator_on_edit):
                        instance = entity.creator(form, request)
                    else:
                        instance = form.save(commit=False)

                        if created:
                            for attr in ("created_by",) + entity.auto_user:
                                if (
                                    hasattr(instance, f"{attr}_id")
                                    and getattr(instance, f"{attr}_id") is None
                                ):
                                    setattr(instance, attr, request.user)

                        if entity.before_save:
                            entity.before_save(instance, request)

                        instance.save()
                        form.save_m2m()

                        for item in formsets:
                            item["formset"].save()

                    if entity.after_save:
                        entity.after_save(instance, form, request, created)

            except ValidationError as exc:
                # Model-level checks that only run inside save().
                for message in exc.messages:
                    form.add_error(None, message)
            except IntegrityError:
                form.add_error(
                    None,
                    "This record could not be saved because it clashes with "
                    "an existing one (a duplicate number or code).",
                )
            else:
                verb = "created" if created else "updated"
                messages.success(
                    request, f"{entity.title} “{instance}” was {verb}."
                )

                if created and entity.edit_after_create:
                    messages.info(
                        request, "Review the items below, then use the buttons on the list."
                    )
                    return redirect(edit_url(entity, instance))

                return redirect(list_url(entity))

    context = base_context(request, entity.key)
    context.update(
        {
            "entity": entity,
            "form": form,
            "formsets": formsets,
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
# Row buttons (check-in, receive stock, dispense ...)
# ---------------------------------------------------------------------------

def safe_next(request, fallback):
    target = request.POST.get("next") or request.GET.get("next")

    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}
    ):
        return target

    return fallback


@login_required
def entity_action(request, section, pk, action):
    entity = get_entity(section)

    spec = next(
        (a for a in entity.actions if a.key == action and a.run), None
    )
    if spec is None:
        raise Http404("Unknown action.")

    require(request.user, entity.action_perm(spec))

    obj = get_object_or_404(entity.queryset(), pk=pk)
    back = safe_next(request, list_url(entity))

    if spec.visible and not spec.visible(obj):
        messages.error(request, "That action is not available for this record right now.")
        return redirect(back)

    form = None

    if spec.form is not None:
        form = spec.form(request.POST or None)

        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
        else:
            return render_action_form(request, entity, spec, obj, form, back)
    else:
        if request.method != "POST":
            return redirect(back)
        data = None

    try:
        with transaction.atomic():
            if form is not None:
                message = spec.run(obj, request, data)
            else:
                message = spec.run(obj, request)
    except ValidationError as exc:
        text = " ".join(exc.messages)

        if form is not None:
            form.add_error(None, text)
            return render_action_form(request, entity, spec, obj, form, back)

        messages.error(request, text)
    else:
        messages.success(request, message)

    return redirect(back)


def render_action_form(request, entity, spec, obj, form, back):
    context = base_context(request, entity.key)
    context.update(
        {
            "entity": entity,
            "action": spec,
            "object": obj,
            "form": form,
            "cancel_url": back,
            "next": back,
        }
    )
    return render(request, "portal/action_form.html", context)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@login_required
def entity_delete(request, section, pk):
    entity = get_entity(section)
    obj = get_object_or_404(entity.model, pk=pk)

    require(request.user, entity.perm("delete"))

    if not entity.allow_delete:
        messages.error(
            request,
            f"{entity.plural} are a permanent record and cannot be deleted.",
        )
        return redirect(list_url(entity))

    if entity.guard:
        problem = entity.guard(obj, request, "delete")
        if problem:
            messages.error(request, problem)
            return redirect(list_url(entity))

    if request.method == "POST":
        label = str(obj)

        try:
            with transaction.atomic():
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
# Type-ahead search used by patient / medicine drop-downs
# ---------------------------------------------------------------------------

@login_required
def lookup(request, key):
    if key not in LOOKUPS:
        raise Http404("Unknown lookup.")

    query = request.GET.get("q", "").strip()[:60]

    return JsonResponse({"results": lookup_search(key, query)})


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

    # --- things that need attention -------------------------------------
    def attention(label, value, note, section, filter_value=None):
        url = reverse("portal:list", kwargs={"section": section})
        if filter_value:
            url += f"?filter={filter_value}"
        stats.append(
            {"label": label, "value": value, "note": note, "url": url}
        )

    if user.has_perm("laboratory.view_labsample"):
        pending = LabSample.objects.filter(status=LabSample.Status.PENDING).count()
        collected = LabSample.objects.filter(status=LabSample.Status.COLLECTED).count()
        attention(
            "Samples to collect", pending, f"{collected} collected, not yet received",
            "lab-samples", "PENDING",
        )

    if user.has_perm("laboratory.view_labresult"):
        attention(
            "Results to verify",
            LabResult.objects.filter(status=LabResult.ResultStatus.ENTERED).count(),
            "entered, waiting for a second check",
            "lab-results", "ENTERED",
        )

    if user.has_perm("pharmacy.view_prescription"):
        attention(
            "Prescriptions to dispense",
            Prescription.objects.filter(
                status__in=[
                    Prescription.Status.ACTIVE,
                    Prescription.Status.PARTIALLY_DISPENSED,
                ]
            ).count(),
            "waiting at the pharmacy",
            "prescriptions", "ACTIVE",
        )

    if user.has_perm("pharmacy.view_medicinebatch"):
        soon = today + timedelta(days=30)
        expiring = MedicineBatch.objects.filter(
            is_active=True,
            available_quantity__gt=0,
            expiry_date__lte=soon,
        )
        attention(
            "Batches expiring soon",
            expiring.filter(expiry_date__gte=today).count(),
            f"{expiring.filter(expiry_date__lt=today).count()} already expired, still in stock",
            "stock",
        )

    if user.has_perm("pharmacy.view_medicine"):
        low = (
            Medicine.objects.filter(is_active=True, reorder_level__gt=0)
            .annotate(
                stock=Coalesce(
                    Sum(
                        "batches__available_quantity",
                        filter=Q(
                            batches__is_active=True,
                            batches__expiry_date__gte=today,
                        ),
                    ),
                    Value(0, output_field=DecimalField()),
                )
            )
            .filter(stock__lte=F("reorder_level"))
            .count()
        )
        attention("Low-stock medicines", low, "at or below reorder level", "medicines")

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
