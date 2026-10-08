from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import (
    IPDAdmission,
    IPDBedTransfer,
    IPDDoctorAssignment,
    IPDDoctorNote,
)


User = get_user_model()


# ============================================================
# IPD BED TRANSFER
# ============================================================

@transaction.atomic
def transfer_patient_bed(
    admission,
    to_ward,
    to_room,
    to_bed,
    user=None,
    reason="",
    notes="",
):
    """
    Transfer an admitted patient from current bed to a new bed.
    """

    admission = (
        IPDAdmission.objects
        .select_for_update()
        .select_related(
            "patient",
            "ward",
            "room",
            "bed",
        )
        .get(pk=admission.pk)
    )

    # --------------------------------------------------------
    # Active admission check
    # --------------------------------------------------------

    if admission.status not in [
        "ADMITTED",
        "ON_HOLD",
    ]:
        raise ValueError(
            "Only an active IPD admission can be transferred."
        )

    if not to_ward:
        raise ValueError("Destination ward is required.")

    if not to_room:
        raise ValueError("Destination room is required.")

    if not to_bed:
        raise ValueError("Destination bed is required.")

    # --------------------------------------------------------
    # Ward / Room / Bed hierarchy
    # --------------------------------------------------------

    if to_room.ward_id != to_ward.id:
        raise ValueError(
            "Selected room does not belong to the selected ward."
        )

    if to_bed.room_id != to_room.id:
        raise ValueError(
            "Selected bed does not belong to the selected room."
        )

    # --------------------------------------------------------
    # Lock destination bed
    # --------------------------------------------------------

    destination_bed = (
        to_bed.__class__.objects
        .select_for_update()
        .get(pk=to_bed.pk)
    )

    # --------------------------------------------------------
    # Same bed
    # --------------------------------------------------------

    if admission.bed_id == destination_bed.id:
        raise ValueError(
            "Patient is already allocated to this bed."
        )

    # --------------------------------------------------------
    # Bed availability
    # --------------------------------------------------------

    if destination_bed.status != "AVAILABLE":
        raise ValueError(
            "Selected destination bed is not available."
        )

    # --------------------------------------------------------
    # Check another active admission
    # --------------------------------------------------------

    destination_occupied = (
        IPDAdmission.objects
        .filter(
            bed=destination_bed,
            status__in=[
                "ADMITTED",
                "ON_HOLD",
            ],
        )
        .exclude(pk=admission.pk)
        .exists()
    )

    if destination_occupied:
        raise ValueError(
            "Selected destination bed is already assigned to another patient."
        )

    # --------------------------------------------------------
    # Old location
    # --------------------------------------------------------

    old_ward = admission.ward
    old_room = admission.room
    old_bed = admission.bed

    # --------------------------------------------------------
    # Create transfer history
    # --------------------------------------------------------

    transfer = IPDBedTransfer.objects.create(
        admission=admission,
        patient=admission.patient,

        from_ward=old_ward,
        from_room=old_room,
        from_bed=old_bed,

        to_ward=to_ward,
        to_room=to_room,
        to_bed=destination_bed,

        transfer_date=timezone.now(),
        reason=reason,
        notes=notes,
        transferred_by=user,
    )

    # --------------------------------------------------------
    # Free old bed
    # --------------------------------------------------------

    if old_bed:
        old_bed.status = "AVAILABLE"
        old_bed.save(
            update_fields=["status"]
        )

    # --------------------------------------------------------
    # Occupy new bed
    # --------------------------------------------------------

    destination_bed.status = "OCCUPIED"
    destination_bed.save(
        update_fields=["status"]
    )

    # --------------------------------------------------------
    # Update admission
    # --------------------------------------------------------

    admission.ward = to_ward
    admission.room = to_room
    admission.bed = destination_bed

    admission.save(
        update_fields=[
            "ward",
            "room",
            "bed",
            "updated_at",
        ]
    )

    return transfer


# ============================================================
# IPD DOCTOR ASSIGNMENT
# ============================================================

@transaction.atomic
def assign_ipd_doctor(
    admission,
    doctor,
    user=None,
    role="CONSULTANT",
    reason="",
    notes="",
):
    """
    Assign a doctor to an IPD admission.

    role:
        PRIMARY
        CONSULTANT
    """

    # --------------------------------------------------------
    # Lock admission
    # --------------------------------------------------------

    admission = (
        IPDAdmission.objects
        .select_for_update()
        .get(pk=admission.pk)
    )

    # --------------------------------------------------------
    # Active admission check
    # --------------------------------------------------------

    if admission.status not in [
        "ADMITTED",
        "ON_HOLD",
    ]:
        raise ValueError(
            "Doctor can only be assigned to an active IPD admission."
        )

    # --------------------------------------------------------
    # Doctor validation
    # --------------------------------------------------------

    if not doctor:
        raise ValueError(
            "Doctor is required."
        )

    if doctor.role != "DOCTOR":
        raise ValueError(
            "Selected user is not registered as a Doctor."
        )

    if not doctor.is_active:
        raise ValueError(
            "Selected doctor is inactive."
        )

    # --------------------------------------------------------
    # Validate role
    # --------------------------------------------------------

    role = str(role).upper()

    if role not in [
        "PRIMARY",
        "CONSULTANT",
    ]:
        raise ValueError(
            "Invalid doctor assignment role."
        )

    # --------------------------------------------------------
    # Duplicate active assignment
    # --------------------------------------------------------

    duplicate = (
        IPDDoctorAssignment.objects
        .filter(
            admission=admission,
            doctor=doctor,
            is_active=True,
        )
        .exists()
    )

    if duplicate:
        raise ValueError(
            "This doctor is already actively assigned to this admission."
        )

    # --------------------------------------------------------
    # PRIMARY doctor
    # --------------------------------------------------------

    if role == "PRIMARY":

        existing_primary = (
            IPDDoctorAssignment.objects
            .select_for_update()
            .filter(
                admission=admission,
                role="PRIMARY",
                is_active=True,
            )
            .first()
        )

        if existing_primary:
            existing_primary.is_active = False
            existing_primary.end_date = timezone.now()

            existing_primary.save(
                update_fields=[
                    "is_active",
                    "end_date",
                    "updated_at",
                ]
            )

    # --------------------------------------------------------
    # Create doctor assignment
    # --------------------------------------------------------

    assignment = IPDDoctorAssignment.objects.create(
        admission=admission,
        doctor=doctor,
        role=role,
        assigned_date=timezone.now(),
        is_active=True,
        reason=reason,
        notes=notes,
        assigned_by=user,
    )

    return assignment


# ============================================================
# REMOVE / END IPD DOCTOR ASSIGNMENT
# ============================================================

@transaction.atomic
def remove_ipd_doctor(
    assignment,
    user=None,
    reason="",
):
    """
    End an active IPD doctor assignment.

    Primary doctor cannot be removed directly.
    """

    assignment = (
        IPDDoctorAssignment.objects
        .select_for_update()
        .select_related(
            "admission",
            "doctor",
        )
        .get(pk=assignment.pk)
    )

    # --------------------------------------------------------
    # Already inactive
    # --------------------------------------------------------

    if not assignment.is_active:
        raise ValueError(
            "This doctor assignment is already inactive."
        )

    # --------------------------------------------------------
    # Primary doctor protection
    # --------------------------------------------------------

    if assignment.role == "PRIMARY":
        raise ValueError(
            "Primary doctor cannot be removed directly. "
            "Please assign a replacement Primary doctor first."
        )

    # --------------------------------------------------------
    # End assignment
    # --------------------------------------------------------

    assignment.is_active = False
    assignment.end_date = timezone.now()

    if reason:
        if assignment.notes:
            assignment.notes += (
                f"\nRemoval reason: {reason}"
            )
        else:
            assignment.notes = (
                f"Removal reason: {reason}"
            )

    assignment.save(
        update_fields=[
            "is_active",
            "end_date",
            "notes",
            "updated_at",
        ]
    )

    return assignment


# ============================================================
# IPD DOCTOR NOTE
# ============================================================

@transaction.atomic
def create_ipd_doctor_note(
    admission,
    doctor,
    clinical_note,
    note_type="Progress Note",
):
    """
    Create a clinical note by an actively assigned IPD doctor.
    """

    # --------------------------------------------------------
    # Lock admission
    # --------------------------------------------------------

    admission = (
        IPDAdmission.objects
        .select_for_update()
        .get(pk=admission.pk)
    )

    # --------------------------------------------------------
    # Active admission check
    # --------------------------------------------------------

    if admission.status not in [
        "ADMITTED",
        "ON_HOLD",
    ]:
        raise ValueError(
            "Doctor notes can only be added to an active IPD admission."
        )

    # --------------------------------------------------------
    # Note validation
    # --------------------------------------------------------

    if not clinical_note or not clinical_note.strip():
        raise ValueError(
            "Clinical note cannot be empty."
        )

    # --------------------------------------------------------
    # Doctor validation
    # --------------------------------------------------------

    if not doctor:
        raise ValueError(
            "Doctor is required."
        )

    if doctor.role != "DOCTOR":
        raise ValueError(
            "Selected user is not registered as a Doctor."
        )

    # --------------------------------------------------------
    # Doctor must be actively assigned
    # --------------------------------------------------------

    assigned = (
        IPDDoctorAssignment.objects
        .filter(
            admission=admission,
            doctor=doctor,
            is_active=True,
        )
        .exists()
    )

    if not assigned:
        raise ValueError(
            "Doctor must be actively assigned to this IPD admission."
        )

    # --------------------------------------------------------
    # Create doctor note
    # --------------------------------------------------------

    note = IPDDoctorNote.objects.create(
        admission=admission,
        doctor=doctor,
        note_date=timezone.now(),
        note_type=note_type or "Progress Note",
        clinical_note=clinical_note.strip(),
    )

    return note