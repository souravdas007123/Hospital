"""Forms used by the portal's add/edit pages.

Most entities use a plain ModelForm built on the fly (see ``registry.py``).
The classes here cover the ones that need smarter behaviour: filtered
drop-downs, values copied from a parent record, passwords, and so on.
"""

from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import (
    NON_FIELD_ERRORS,
    FieldDoesNotExist,
    ObjectDoesNotExist,
    ValidationError,
)
from django.db import models
from django.db.models import Q

from appointments.models import Appointment
from doctors.models import Doctor, DoctorSchedule
from hospitals.models import Bed, Department, Room, Ward
from ipd.models import IPDAdmission
from laboratory.models import LabOrder, LabOrderItem, LabPackage, LabTest
from opd.models import OPDVisit
from patients.models import Patient

from .utils import WEEKDAYS


User = get_user_model()


# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------

def portal_formfield(db_field, **kwargs):
    """Use native date / time pickers instead of plain text boxes."""
    if isinstance(db_field, models.DateTimeField):
        kwargs.setdefault(
            "widget",
            forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
        )
    elif isinstance(db_field, models.DateField):
        kwargs.setdefault(
            "widget",
            forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        )
    elif isinstance(db_field, models.TimeField):
        kwargs.setdefault(
            "widget",
            forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        )

    return db_field.formfield(**kwargs)


class PortalForm(forms.ModelForm):
    """Base for every portal form.

    Class options (all optional):

    * ``derive``: ``{"patient": "admission.patient"}`` copies a value from an
      already chosen field onto the record, so it can never disagree with
      its parent.
    * ``readonly_on_edit``: fields that can be chosen when adding a record
      but are locked afterwards.
    * ``doctor_user_fields``: user fields restricted to active doctors
      (the logged-in doctor is pre-selected).
    """

    derive = {}
    readonly_on_edit = ()
    doctor_user_fields = ()

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)

        self._limit_to_active()

        for name in self.readonly_on_edit:
            if self.instance.pk and name in self.fields:
                self.fields[name].disabled = True

        for name in self.doctor_user_fields:
            field = self.fields.get(name)
            if field is None:
                continue

            current = getattr(self.instance, f"{name}_id", None)
            field.queryset = User.objects.filter(
                _current_or(doctor_users_filter(), current)
            ).order_by("first_name", "last_name", "username")
            field.label_from_instance = _user_label

            if (
                not self.instance.pk
                and request is not None
                and getattr(request.user, "role", None) == "DOCTOR"
            ):
                # ModelForm.initial (built from the empty instance) wins over
                # field.initial, so the default has to go in here.
                self.initial.setdefault(name, request.user.pk)

        self._prefill_from_url()

    def _prefill_from_url(self):
        """/section/new/?patient=12 pre-selects that value, so row buttons
        like "Record vitals" can open a form that is already filled in."""
        request = self.request

        if self.instance.pk or request is None or request.method != "GET":
            return

        for name in self.fields:
            if name in request.GET and request.GET[name]:
                self.initial[name] = request.GET[name]

    def _update_errors(self, errors):
        # Model.clean() may blame a field that is not on this form (because
        # the system fills it in). Django would raise ValueError; show it as
        # a general error instead.
        if hasattr(errors, "error_dict"):
            mapped = {}
            for field, error_list in errors.error_dict.items():
                target = (
                    field
                    if field == NON_FIELD_ERRORS or field in self.fields
                    else NON_FIELD_ERRORS
                )
                mapped.setdefault(target, []).extend(error_list)
            errors = ValidationError(mapped)

        super()._update_errors(errors)

    def _limit_to_active(self):
        """Drop-downs only offer active records (plus the one already saved)."""
        for name, field in self.fields.items():
            if not isinstance(field, forms.ModelChoiceField):
                continue

            model = field.queryset.model

            try:
                model._meta.get_field("is_active")
            except FieldDoesNotExist:
                continue

            current = getattr(self.instance, f"{name}_id", None)
            field.queryset = field.queryset.filter(
                Q(is_active=True) | Q(pk=current)
            )

    def clean(self):
        cleaned = super().clean()

        for target, path in self.derive.items():
            first, *rest = path.split(".")
            value = cleaned.get(first)

            for part in rest:
                if value is None:
                    break
                value = getattr(value, part, None)

            if value is not None:
                setattr(self.instance, target, value)

        return cleaned

    def _post_clean(self):
        # Model.clean() methods assume their foreign keys are present. When a
        # required choice is already invalid the user sees that error, so a
        # crash from the model check would only hide it.
        try:
            super()._post_clean()
        except (ObjectDoesNotExist, AttributeError):
            if not self.errors:
                raise


def _user_label(user):
    name = user.get_full_name() or user.get_username()
    return f"{name} ({user.get_role_display()})"


def _current_or(queryset_filter, current_pk):
    """Q object: rows matching the filter, plus the record already saved."""
    return queryset_filter | Q(pk=current_pk)


def doctor_users_filter():
    return Q(role="DOCTOR", is_active=True)


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------

class AppointmentForm(PortalForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        current = self.instance

        self.fields["token_number"].required = False
        self.fields["token_number"].help_text = (
            "Leave blank to give the next free token for that doctor and day."
        )

        self.fields["patient"].queryset = Patient.objects.filter(
            _current_or(Q(is_active=True), current.patient_id)
        ).order_by("first_name", "last_name")

        self.fields["doctor"].queryset = (
            Doctor.objects.select_related("user")
            .filter(
                _current_or(
                    Q(is_active=True, is_available=True),
                    current.doctor_id,
                )
            )
            .order_by("user__first_name", "user__last_name")
        )

        self.fields["department"].queryset = Department.objects.filter(
            _current_or(Q(is_active=True), current.department_id)
        ).order_by("name")

        self.fields["schedule"].queryset = (
            DoctorSchedule.objects.select_related("doctor__user")
            .filter(_current_or(Q(is_active=True), current.schedule_id))
        )


# ---------------------------------------------------------------------------
# OPD visits
# ---------------------------------------------------------------------------

class OPDVisitForm(PortalForm):
    """An OPD visit always belongs to an appointment; patient, doctor and
    department are copied from it so they can never disagree."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        field = self.fields["appointment"]
        field.help_text = (
            "Patient, doctor and department are taken from the appointment."
        )

        if self.instance.pk:
            field.queryset = Appointment.objects.filter(
                pk=self.instance.appointment_id
            )
            field.disabled = True
        else:
            field.queryset = (
                Appointment.objects.select_related("patient", "doctor__user")
                .filter(
                    status__in=[
                        Appointment.Status.BOOKED,
                        Appointment.Status.CONFIRMED,
                        Appointment.Status.CHECKED_IN,
                        Appointment.Status.IN_CONSULTATION,
                    ],
                    opd_visit__isnull=True,
                )
                .order_by("-appointment_date", "-id")
            )

    def clean(self):
        cleaned = super().clean()

        appointment = cleaned.get("appointment")

        if appointment is not None:
            self.instance.patient = appointment.patient
            self.instance.doctor = appointment.doctor
            self.instance.department = appointment.department

        return cleaned


# ---------------------------------------------------------------------------
# IPD admissions
# ---------------------------------------------------------------------------

class IPDAdmissionForm(PortalForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        current = self.instance

        self.fields["patient"].queryset = Patient.objects.filter(
            _current_or(Q(is_active=True), current.patient_id)
        ).order_by("first_name", "last_name")

        self.fields["doctor"].queryset = User.objects.filter(
            _current_or(doctor_users_filter(), current.doctor_id)
        ).order_by("first_name", "last_name", "username")
        self.fields["doctor"].help_text = "Only users with the Doctor role."

        self.fields["department"].queryset = Department.objects.filter(
            _current_or(Q(is_active=True), current.department_id)
        ).order_by("name")

        self.fields["ward"].queryset = Ward.objects.filter(
            _current_or(Q(is_active=True), current.ward_id)
        ).order_by("name")

        self.fields["room"].queryset = (
            Room.objects.select_related("ward")
            .filter(_current_or(Q(is_active=True), current.room_id))
            .order_by("ward__name", "room_number")
        )
        self.fields["room"].label_from_instance = (
            lambda room: f"Room {room.room_number} · {room.ward.name}"
        )

        self.fields["bed"].queryset = (
            Bed.objects.select_related("room__ward")
            .filter(
                _current_or(
                    Q(is_active=True, status=Bed.Status.AVAILABLE),
                    current.bed_id,
                )
            )
            .order_by("room__ward__name", "room__room_number", "bed_number")
        )
        self.fields["bed"].label_from_instance = (
            lambda bed: (
                f"Bed {bed.bed_number} · Room {bed.room.room_number}"
                f" · {bed.room.ward.name}"
            )
        )
        self.fields["bed"].help_text = "Only available beds are listed."

        # Discharge has its own page (Discharge button); moving a patient
        # has its own page (Transfer button). Keep this form simple.
        for name in (
            "discharge_date", "final_diagnosis", "treatment_summary",
            "discharge_instructions", "discharge_disposition",
        ):
            self.fields.pop(name, None)

        if self.instance.pk:
            for name in ("patient", "ward", "room", "bed"):
                self.fields[name].disabled = True

            self.fields["status"].choices = [
                (IPDAdmission.Status.ADMITTED, "Admitted"),
                (IPDAdmission.Status.ON_HOLD, "On Hold"),
                (IPDAdmission.Status.CANCELLED, "Cancelled"),
            ]
        else:
            self.fields.pop("status", None)


# ---------------------------------------------------------------------------
# Laboratory orders (+ test lines)
# ---------------------------------------------------------------------------

class LabOrderForm(PortalForm):

    package = forms.ModelChoiceField(
        queryset=LabPackage.objects.none(),
        required=False,
        label="Add a package",
        help_text="Adds every test of the package below.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        current = self.instance

        self.fields["package"].queryset = (
            LabPackage.objects.filter(is_active=True).order_by("name")
        )
        self.fields["package"].label_from_instance = (
            lambda pkg: f"{pkg.name} (₹{pkg.final_price})"
        )

        if not current.pk:
            self.fields.pop("status", None)

        self.fields["patient"].queryset = Patient.objects.filter(
            _current_or(Q(is_active=True), current.patient_id)
        ).order_by("first_name", "last_name")

        self.fields["doctor"].queryset = User.objects.filter(
            _current_or(doctor_users_filter(), current.doctor_id)
        ).order_by("first_name", "last_name", "username")
        self.fields["doctor"].help_text = "Ordering doctor."

        if (
            not current.pk
            and self.request is not None
            and getattr(self.request.user, "role", None) == "DOCTOR"
        ):
            self.initial.setdefault("doctor", self.request.user.pk)

        self.fields["opd_visit"].queryset = (
            OPDVisit.objects.select_related("patient").order_by("-id")
        )
        self.fields["opd_visit"].label_from_instance = (
            lambda visit: f"{visit.visit_number} · {visit.patient.full_name}"
        )

        self.fields["ipd_admission"].queryset = (
            IPDAdmission.objects.select_related("patient").order_by("-id")
        )
        self.fields["ipd_admission"].label_from_instance = (
            lambda adm: f"{adm.admission_number} · {adm.patient.full_name}"
        )


class LabOrderItemForm(forms.ModelForm):

    class Meta:
        model = LabOrderItem
        fields = ("test", "quantity", "price", "discount")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["test"].queryset = (
            LabTest.objects.filter(is_active=True).order_by("name")
        )
        self.fields["test"].label_from_instance = (
            lambda test: f"{test.name} (₹{test.price})"
        )

        self.fields["price"].required = False
        self.fields["price"].help_text = "Blank = test price"
        self.fields["discount"].required = False

    def clean_price(self):
        value = self.cleaned_data.get("price")
        return value if value is not None else Decimal("0.00")

    def clean_discount(self):
        value = self.cleaned_data.get("discount")
        return value if value is not None else Decimal("0.00")


def lab_item_formset(extra):
    return forms.inlineformset_factory(
        LabOrder,
        LabOrderItem,
        form=LabOrderItemForm,
        extra=extra,
        can_delete=True,
    )


# ---------------------------------------------------------------------------
# Doctors and schedules
# ---------------------------------------------------------------------------

class DoctorForm(PortalForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        user_field = self.fields["user"]
        user_field.queryset = User.objects.filter(
            doctor_users_filter(),
        ).filter(
            Q(doctor_profile__isnull=True) | Q(pk=self.instance.user_id)
        ).order_by("first_name", "last_name", "username")
        user_field.help_text = (
            "Create the login first under Users (role: Doctor), then pick it here."
        )

        if self.instance.pk:
            user_field.disabled = True

        self.fields["department"].queryset = Department.objects.filter(
            _current_or(Q(is_active=True), self.instance.department_id)
        ).order_by("name")


class DoctorScheduleForm(PortalForm):

    day_of_week = forms.TypedChoiceField(
        choices=WEEKDAYS,
        coerce=int,
        label="Day of week",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["doctor"].queryset = (
            Doctor.objects.select_related("user")
            .filter(_current_or(Q(is_active=True), self.instance.doctor_id))
            .order_by("user__first_name", "user__last_name")
        )

        self.fields["department"].queryset = Department.objects.filter(
            _current_or(Q(is_active=True), self.instance.department_id)
        ).order_by("name")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class UserForm(PortalForm):

    password1 = forms.CharField(
        label="Password",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirm password",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk:
            self.fields["password1"].help_text = (
                "Leave both blank to keep the current password."
            )

    def clean(self):
        cleaned = super().clean()

        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")

        if not self.instance.pk and not password1:
            self.add_error("password1", "Password is required for a new user.")

        if password1 or password2:
            if password1 != password2:
                self.add_error("password2", "The two passwords do not match.")
            else:
                try:
                    validate_password(password1, self.instance)
                except forms.ValidationError as exc:
                    self.add_error("password1", exc)

        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)

        password = self.cleaned_data.get("password1")

        if password:
            user.set_password(password)

        if commit:
            user.save()
            self.save_m2m()

        return user
