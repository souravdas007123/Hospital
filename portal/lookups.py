"""Type-ahead search for long lists (patients, medicines).

A plain drop-down with thousands of patients is slow to load and hard to use.
Fields for these models get a ``LookupSelect`` widget instead: it renders only
the chosen record and fetches matches from ``/lookup/<key>/?q=`` as you type.
"""

from django.db.models import Q

from patients.models import Patient
from pharmacy.models import Medicine


LIMIT = 20


def _patient_label(patient):
    parts = [patient.full_name, patient.uhid]
    if patient.phone:
        parts.append(patient.phone)
    return " · ".join(part for part in parts if part)


def _medicine_label(medicine):
    parts = [medicine.name]
    if medicine.strength:
        parts.append(medicine.strength)
    parts.append(medicine.get_dosage_form_display())
    return " · ".join(part for part in parts if part)


LOOKUPS = {
    "patients": {
        "model": Patient,
        "base": lambda: Patient.objects.filter(is_active=True),
        "search": [
            "uhid", "first_name", "middle_name", "last_name", "phone",
            "alternate_phone", "national_id",
        ],
        "order": ("first_name", "last_name", "id"),
        "label": _patient_label,
        "perm": "patients.view_patient",
    },
    "medicines": {
        "model": Medicine,
        "base": lambda: Medicine.objects.filter(is_active=True),
        "search": ["name", "generic_name", "brand_name", "medicine_code"],
        "order": ("name", "id"),
        "label": _medicine_label,
        "perm": "pharmacy.view_medicine",
    },
}

BY_MODEL = {config["model"]: key for key, config in LOOKUPS.items()}


def search(key, query):
    """Return ``[{"id": .., "text": ..}, ...]`` for the typed text."""
    config = LOOKUPS[key]
    queryset = config["base"]()

    for term in query.split():
        clause = Q()
        for field in config["search"]:
            clause |= Q(**{f"{field}__icontains": term})
        queryset = queryset.filter(clause)

    return [
        {"id": obj.pk, "text": config["label"](obj)}
        for obj in queryset.order_by(*config["order"])[:LIMIT]
    ]
