from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from hospitals.models import Hospital

from .models import LabReport, LabResult


@login_required
def lab_report_print(request, pk):
    """
    Display a professional printable laboratory report.
    """

    report = get_object_or_404(
        LabReport.objects.select_related(
            "order",
            "patient",
            "prepared_by",
            "verified_by",
            "finalized_by",
            "order__doctor",
            "order__opd_visit",
        ),
        pk=pk,
    )

    hospital = (
        Hospital.objects
        .filter(is_active=True)
        .order_by("id")
        .first()
    )

    results = (
        LabResult.objects
        .filter(
            order_item__order=report.order
        )
        .select_related(
            "test",
            "sample",
            "order_item",
        )
        .order_by(
            "test__category__name",
            "test__name",
            "id",
        )
    )

    patient_age = None

    if report.patient.dob:

        today = timezone.localdate()

        patient_age = (
            today.year
            - report.patient.dob.year
        )

        if (
            (today.month, today.day)
            < (
                report.patient.dob.month,
                report.patient.dob.day,
            )
        ):
            patient_age -= 1

    context = {
        "report": report,
        "hospital": hospital,
        "patient": report.patient,
        "order": report.order,
        "results": results,
        "patient_age": patient_age,
        "printed_by": request.user,
    }

    return render(
        request,
        "laboratory/lab_report.html",
        context,
    )