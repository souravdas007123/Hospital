"""Small display helpers shared by the portal views and registry."""

from datetime import date, datetime, time

from urllib.parse import urlencode

from django.urls import reverse
from django.utils import timezone


WEEKDAYS = [
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
]


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


def weekday_name(number):
    return dict(WEEKDAYS).get(number)


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

    if kind == "yesno":
        on = bool(getattr(obj, accessor))
        return {
            "text": "Yes" if on else "No",
            "badge": "s-active" if on else "s-inactive",
        }

    if kind == "urgent":
        on = bool(getattr(obj, accessor))
        return {
            "text": "STAT" if on else "Routine",
            "badge": "s-stat" if on else "s-routine",
        }

    value = resolve(obj, accessor)

    # A column function may return a ready-made cell:
    # {"text": ..., "badge": ...} for a coloured label, or {"text", "href"}.
    if isinstance(value, dict):
        return value

    if value is None and kind == "link":
        return {"text": "—"}

    text = format_value(value)

    if kind == "trunc" and len(text) > 60:
        text = text[:57] + "…"

    return {"text": text, "kind": kind}


def new_url(section, **params):
    """Link to a section's "new" page with some fields pre-filled."""
    url = reverse("portal:new", kwargs={"section": section})
    return f"{url}?{urlencode(params)}" if params else url
