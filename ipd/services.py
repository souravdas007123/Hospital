
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    IPDAdmission,
    IPDBedTransfer,
    IPDDoctorAssignment,
    IPDDoctorNote,
    IPDNursingVital,
    IPDNursingNote,
    IPDMedicationOrder,
    IPDMedicationAdministration,
)


ACTIVE_ADMISSION_STATUSES = ("ADMITTED", "ON_HOLD")


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
    Transfer an admitted patient to another available bed.
    Transfer history is saved and bed statuses are updated.
    """

    admission = (
        IPDAdmission.objects
        .select_for_update()
        .select_related("patient", "ward", "room", "bed")
        .get(pk=admission.pk)
    )

    if admission.status not in ACTIVE_ADMISSION_STATUSES:
        raise ValidationError(
            "Only an active IPD admission can be transferred."
        )

    if not to_ward or not to_room or not to_bed:
        raise ValidationError(
            "Destination ward, room and bed are required."
        )

    if to_room.ward_id != to_ward.pk:
        raise ValidationError(
            "Selected room does not belong to the selected ward."
        )

    if to_bed.room_id != to_room.pk:
        raise ValidationError(
            "Selected bed does not belong to the selected room."
        )

    destination_bed = (
        to_bed.__class__.objects
        .select_for_update()
        .get(pk=to_bed.pk)
    )

    if admission.bed_id == destination_bed.pk:
        raise ValidationError(
            "Patient is already allocated to this bed."
        )

    if destination_bed.status != "AVAILABLE":
        raise ValidationError(
            "Selected destination bed is not available."
        )

    destination_occupied = (
        IPDAdmission.objects
        .filter(
            bed=destination_bed,
            status__in=ACTIVE_ADMISSION_STATUSES,
        )
        .exclude(pk=admission.pk)
        .exists()
    )

    if destination_occupied:
        raise ValidationError(
            "Selected destination bed is already assigned "
            "to another patient."
        )

    old_ward = admission.ward
    old_room = admission.room
    old_bed = admission.bed

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

    # Occupy destination bed before updating admission.
    destination_bed.status = "OCCUPIED"
    destination_bed.save(update_fields=["status"])

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

    # Release the previous bed only after admission is updated.
    if old_bed:
        old_bed.status = "AVAILABLE"
        old_bed.save(update_fields=["status"])

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
    Assign a doctor to an active IPD admission.
    Supports PRIMARY and CONSULTANT assignments.
    """

    admission = (
        IPDAdmission.objects
        .select_for_update()
        .get(pk=admission.pk)
    )

    if admission.status not in ACTIVE_ADMISSION_STATUSES:
        raise ValidationError(
            "Doctor can only be assigned to an active IPD admission."
        )

    if not doctor:
        raise ValidationError("Doctor is required.")

    if doctor.role != "DOCTOR":
        raise ValidationError(
            "Selected user is not registered as a Doctor."
        )

    if not doctor.is_active:
        raise ValidationError("Selected doctor is inactive.")

    role = str(role).upper()

    if role not in ("PRIMARY", "CONSULTANT"):
        raise ValidationError("Invalid doctor assignment role.")

    duplicate = IPDDoctorAssignment.objects.filter(
        admission=admission,
        doctor=doctor,
        is_active=True,
    ).exists()

    if duplicate:
        raise ValidationError(
            "This doctor is already actively assigned "
            "to this admission."
        )

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
    End an active consultant assignment.
    A primary doctor cannot be removed directly.
    """

    assignment = (
        IPDDoctorAssignment.objects
        .select_for_update()
        .select_related("admission", "doctor")
        .get(pk=assignment.pk)
    )

    if not assignment.is_active:
        raise ValidationError(
            "This doctor assignment is already inactive."
        )

    if assignment.role == "PRIMARY":
        raise ValidationError(
            "Primary doctor cannot be removed directly. "
            "Assign a replacement primary doctor first."
        )

    assignment.is_active = False
    assignment.end_date = timezone.now()

    if reason:
        if assignment.notes:
            assignment.notes += f"\nRemoval reason: {reason}"
        else:
            assignment.notes = f"Removal reason: {reason}"

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

    admission = (
        IPDAdmission.objects
        .select_for_update()
        .get(pk=admission.pk)
    )

    if admission.status not in ACTIVE_ADMISSION_STATUSES:
        raise ValidationError(
            "Doctor notes can only be added to an active admission."
        )

    if not clinical_note or not clinical_note.strip():
        raise ValidationError("Clinical note cannot be empty.")

    if not doctor:
        raise ValidationError("Doctor is required.")

    if doctor.role != "DOCTOR":
        raise ValidationError(
            "Selected user is not registered as a Doctor."
        )

    assigned = IPDDoctorAssignment.objects.filter(
        admission=admission,
        doctor=doctor,
        is_active=True,
    ).exists()

    if not assigned:
        raise ValidationError(
            "Doctor must be actively assigned to this IPD admission."
        )

    note = IPDDoctorNote.objects.create(
        admission=admission,
        doctor=doctor,
        note_date=timezone.now(),
        note_type=note_type or "Progress Note",
        clinical_note=clinical_note.strip(),
    )

    return note


# ============================================================
# IPD NURSING VITALS
# ============================================================

@transaction.atomic
def record_ipd_vitals(admission, user, **vitals):
    """
    Record nursing vitals for an active IPD admission.
    """

    admission = (
        IPDAdmission.objects
        .select_for_update()
        .get(pk=admission.pk)
    )

    if admission.status not in ACTIVE_ADMISSION_STATUSES:
        raise ValidationError(
            "Vitals can only be recorded for an active admission."
        )

    if not user or user.role not in ("NURSE", "ADMIN", "STAFF"):
        raise ValidationError(
            "User is not authorized to record IPD vitals."
        )

    allowed_fields = {
        "temperature",
        "systolic_bp",
        "diastolic_bp",
        "pulse",
        "respiratory_rate",
        "spo2",
        "weight",
        "height",
        "blood_glucose",
        "pain_score",
        "nursing_notes",
    }

    unknown_fields = set(vitals) - allowed_fields

    if unknown_fields:
        raise ValidationError(
            "Unsupported vital fields: "
            + ", ".join(sorted(unknown_fields))
        )

    vital = IPDNursingVital(
        admission=admission,
        patient=admission.patient,
        recorded_by=user,
        **vitals,
    )

    vital.full_clean()
    vital.save()

    return vital


# ============================================================
# IPD NURSING NOTE
# ============================================================

@transaction.atomic
def create_ipd_nursing_note(
    admission,
    nurse,
    notes,
    note_type=IPDNursingNote.NoteType.OBSERVATION,
    intake_ml=None,
    output_ml=None,
):
    """
    Create a nursing note for an active IPD admission.
    """

    admission = (
        IPDAdmission.objects
        .select_for_update()
        .get(pk=admission.pk)
    )

    if admission.status not in ACTIVE_ADMISSION_STATUSES:
        raise ValidationError(
            "Notes can only be added to an active admission."
        )

    if not nurse or nurse.role not in ("NURSE", "ADMIN", "STAFF"):
        raise ValidationError(
            "User is not authorized to create nursing notes."
        )

    note = IPDNursingNote(
        admission=admission,
        patient=admission.patient,
        nurse=nurse,
        notes=notes,
        note_type=note_type,
        intake_ml=intake_ml,
        output_ml=output_ml,
    )

    note.full_clean()
    note.save()

    return note


# ============================================================
# IPD MEDICATION ORDER
# ============================================================

@transaction.atomic
def create_ipd_medication_order(
    admission,
    medicine,
    prescribed_by,
    dose,
    frequency,
    start_date,
    end_date,
    quantity=1,
    duration_days=1,
    route="ORAL",
    instructions="",
):
    """
    Create a medication order for an active IPD admission.
    """

    admission = (
        IPDAdmission.objects
        .select_for_update()
        .get(pk=admission.pk)
    )

    if admission.status not in ACTIVE_ADMISSION_STATUSES:
        raise ValidationError(
            "Medication orders require an active admission."
        )

    if not prescribed_by or prescribed_by.role != "DOCTOR":
        raise ValidationError(
            "Only doctors can prescribe medication."
        )

    if not medicine or not medicine.is_active:
        raise ValidationError("This medicine is inactive or missing.")

    order = IPDMedicationOrder(
        admission=admission,
        patient=admission.patient,
        medicine=medicine,
        prescribed_by=prescribed_by,
        dose=dose,
        frequency=frequency,
        start_date=start_date,
        end_date=end_date,
        quantity=quantity,
        duration_days=duration_days,
        route=route,
        instructions=instructions,
    )

    order.full_clean()
    order.save()

    return order


# ============================================================
# IPD MEDICATION ADMINISTRATION
# ============================================================

@transaction.atomic
def record_ipd_medication_administration(
    medication_order,
    user,
    status,
    scheduled_at,
    quantity_given=0,
    medicine_batch=None,
    reason="",
    notes="",
):
    """
    Record a medication dose as given, missed, refused,
    held or not available.

    Pharmacy stock deduction is intentionally not performed here.
    """

    order = (
        IPDMedicationOrder.objects
        .select_for_update()
        .select_related("admission", "patient", "medicine")
        .get(pk=medication_order.pk)
    )

    if order.status != IPDMedicationOrder.Status.ACTIVE:
        raise ValidationError("This medication order is not active.")

    if order.admission.status not in ACTIVE_ADMISSION_STATUSES:
        raise ValidationError("Patient admission is not active.")

    if not user or user.role not in ("NURSE", "ADMIN"):
        raise ValidationError(
            "Only authorized nursing staff or administrators "
            "can record medication administration."
        )

    if status not in IPDMedicationAdministration.Status.values:
        raise ValidationError(
            "Invalid medication administration status."
        )

    administered_at = (
        timezone.now()
        if status == IPDMedicationAdministration.Status.GIVEN
        else None
    )

    if status == IPDMedicationAdministration.Status.GIVEN:
        if medicine_batch is None:
            raise ValidationError(
                "A medicine batch is required when recording "
                "a dose as given."
            )

        medicine_batch = (
            medicine_batch.__class__.objects
            .select_for_update()
            .get(pk=medicine_batch.pk)
        )

        if medicine_batch.medicine_id != order.medicine_id:
            raise ValidationError(
                "Selected batch does not belong to the prescribed medicine."
            )

        if medicine_batch.expiry_date < timezone.localdate():
            raise ValidationError(
                "Expired medicine cannot be administered."
            )

        if quantity_given <= 0:
            raise ValidationError(
                "Quantity given must be greater than zero."
            )

        if medicine_batch.available_quantity < quantity_given:
            raise ValidationError(
                "Insufficient stock in the selected medicine batch."
            )

    record = IPDMedicationAdministration(
        medication_order=order,
        admission=order.admission,
        patient=order.patient,
        medicine_batch=medicine_batch,
        scheduled_at=scheduled_at,
        administered_at=administered_at,
        administered_by=user,
        quantity_given=quantity_given,
        status=status,
        reason=reason,
        notes=notes,
    )

    record.full_clean()
    record.save()

    # Stock deduction must be integrated with the pharmacy
    # stock service before using this workflow in production.
    return record


# ============================================================
# IPD PATIENT DISCHARGE
# ============================================================

@transaction.atomic
def discharge_ipd_patient(
    admission,
    user,
    final_diagnosis,
    treatment_summary,
    discharge_instructions,
    discharge_disposition,
):
    """
    Discharge an active IPD admission.

    Required:
        - Final diagnosis
        - Treatment summary
        - Discharge instructions
        - Valid discharge disposition

    The IPDAdmission model's save() method is expected to
    update the bed status when admission status becomes DISCHARGED.
    """

    admission = (
        IPDAdmission.objects
        .select_for_update()
        .select_related("patient", "ward", "room", "bed")
        .get(pk=admission.pk)
    )

    if admission.status not in ACTIVE_ADMISSION_STATUSES:
        raise ValidationError(
            "Only an active IPD admission can be discharged."
        )

    final_diagnosis = (final_diagnosis or "").strip()
    treatment_summary = (treatment_summary or "").strip()
    discharge_instructions = (discharge_instructions or "").strip()

    if not final_diagnosis:
        raise ValidationError("Final diagnosis is required.")

    if not treatment_summary:
        raise ValidationError("Treatment summary is required.")

    if not discharge_instructions:
        raise ValidationError("Discharge instructions are required.")

    valid_dispositions = {
        value
        for value, label in IPDAdmission.DischargeDisposition.choices
    }

    if discharge_disposition not in valid_dispositions:
        raise ValidationError("Invalid discharge disposition.")

    admission.final_diagnosis = final_diagnosis
    admission.treatment_summary = treatment_summary
    admission.discharge_instructions = discharge_instructions
    admission.discharge_disposition = discharge_disposition
    admission.discharge_date = timezone.now()
    admission.status = "DISCHARGED"

    admission.save()

    return admission