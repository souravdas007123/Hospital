
from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


def build_ipd_discharge_pdf(admission):
    """
    Generate a PDF discharge summary for an IPD admission.
    Uses fields available on the existing admission object.
    """
    buffer = BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="IPD Discharge Summary",
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="HospitalTitle",
            parent=styles["Title"],
            alignment=TA_CENTER,
            fontSize=17,
            leading=21,
            textColor=colors.HexColor("#17365D"),
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            parent=styles["Heading2"],
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#17365D"),
            spaceBefore=10,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SmallText",
            parent=styles["BodyText"],
            fontSize=8,
            leading=11,
        )
    )

    def safe(value):
        if value is None or str(value).strip() == "":
            return "—"
        return str(value)

    def para(value):
        # Paragraph escapes HTML-sensitive characters.
        from xml.sax.saxutils import escape
        return Paragraph(escape(safe(value)), styles["BodyText"])

    story = [
        Paragraph("HOSPITAL DISCHARGE SUMMARY", styles["HospitalTitle"]),
        Paragraph(
            f"Generated: {timezone.localtime():%d-%m-%Y %I:%M %p}",
            styles["SmallText"],
        ),
        Spacer(1, 8 * mm),
        Paragraph("Admission & Patient Details", styles["SectionHeading"]),
    ]

    patient = getattr(admission, "patient", None)
    doctor = getattr(admission, "doctor", None)

    details = [
        [para("Admission Number"), para(getattr(admission, "admission_number", ""))],
        [para("Patient"), para(patient)],
        [para("Doctor"), para(doctor)],
        [para("Department"), para(getattr(admission, "department", ""))],
        [para("Ward"), para(getattr(admission, "ward", ""))],
        [para("Room"), para(getattr(admission, "room", ""))],
        [para("Bed"), para(getattr(admission, "bed", ""))],
        [
            para("Admission Date"),
            para(getattr(admission, "admission_date", "")),
        ],
        [
            para("Discharge Date"),
            para(getattr(admission, "discharge_date", "")),
        ],
        [
            para("Admission Status"),
            para(getattr(admission, "get_status_display", lambda: "")()),
        ],
    ]

    details_table = Table(details, colWidths=[48 * mm, 115 * mm])
    details_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF0F7")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B7C9D6")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(details_table)

    story.append(Paragraph("Clinical Discharge Details", styles["SectionHeading"]))

    clinical_fields = [
        ("Provisional Diagnosis", "provisional_diagnosis"),
        ("Final Diagnosis", "final_diagnosis"),
        ("Treatment Summary", "treatment_summary"),
        ("Discharge Instructions", "discharge_instructions"),
        ("Discharge Disposition", "get_discharge_disposition_display"),
    ]

    for label, field_name in clinical_fields:
        value = getattr(admission, field_name, "")
        if field_name.startswith("get_"):
            getter = getattr(admission, field_name, None)
            value = getter() if callable(getter) else ""
        story.append(Paragraph(label, styles["Heading3"]))
        story.append(para(value))
        story.append(Spacer(1, 3 * mm))

    story.extend(
        [
            Spacer(1, 12 * mm),
            Paragraph(
                "Doctor's Signature: ______________________________",
                styles["BodyText"],
            ),
            Spacer(1, 8 * mm),
            Paragraph(
                "Authorized Hospital Stamp: ________________________",
                styles["BodyText"],
            ),
        ]
    )

    document.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def discharge_pdf_response(admission):
    pdf_bytes = build_ipd_discharge_pdf(admission)
    filename = f"discharge_{admission.pk}.pdf"

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response