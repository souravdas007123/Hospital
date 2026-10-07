from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import (
    MedicineCategory,
    Manufacturer,
    Medicine,
    MedicineBatch,
    StockTransaction,
    Supplier,
    PharmacyPurchase,
    PharmacyPurchaseItem,
    Prescription,
    PrescriptionItem,
    PharmacyDispensing,
    PharmacyDispensingItem,
)


# ============================================================
# MEDICINE CATEGORY
# ============================================================

@admin.register(MedicineCategory)
class MedicineCategoryAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "is_active",
        "created_at",
    )

    list_filter = ("is_active",)

    search_fields = (
        "code",
        "name",
    )

    list_editable = ("is_active",)

    ordering = ("name",)


# ============================================================
# MANUFACTURER
# ============================================================

@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "contact_person",
        "phone",
        "email",
        "is_active",
    )

    list_filter = ("is_active",)

    search_fields = (
        "code",
        "name",
        "contact_person",
        "phone",
        "email",
    )

    list_editable = ("is_active",)

    ordering = ("name",)


# ============================================================
# MEDICINE BATCH INLINE
# ============================================================

class MedicineBatchInline(admin.TabularInline):
    model = MedicineBatch
    extra = 0
    show_change_link = True

    fields = (
        "batch_number",
        "manufacturing_date",
        "expiry_date",
        "purchase_price",
        "selling_price",
        "quantity_received",
        "available_quantity",
        "received_date",
        "is_active",
    )

    readonly_fields = (
        "available_quantity",
    )


# ============================================================
# MEDICINE
# ============================================================

@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):

    list_display = (
        "medicine_code",
        "name",
        "generic_name",
        "brand_name",
        "dosage_form",
        "gst_rate",
        "current_stock_display",
        "reorder_level",
        "stock_status",
        "is_active",
    )

    list_filter = (
        "category",
        "manufacturer",
        "dosage_form",
        "is_active",
    )

    search_fields = (
        "medicine_code",
        "name",
        "generic_name",
        "brand_name",
        "strength",
    )

    autocomplete_fields = (
        "category",
        "manufacturer",
    )

    readonly_fields = (
        "medicine_code",
        "created_at",
        "updated_at",
    )

    list_editable = (
        "is_active",
    )

    inlines = (
        MedicineBatchInline,
    )

    fieldsets = (
        (
            "Medicine Identification",
            {
                "fields": (
                    "medicine_code",
                    "name",
                    "generic_name",
                    "brand_name",
                    "strength",
                    "dosage_form",
                    "unit",
                )
            },
        ),
        (
            "Classification",
            {
                "fields": (
                    "category",
                    "manufacturer",
                )
            },
        ),
        (
            "Pricing & Stock Control",
            {
                "fields": (
                    "gst_rate",
                    "reorder_level",
                )
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "is_active",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(description="Current Stock")
    def current_stock_display(self, obj):
        return obj.current_stock

    @admin.display(description="Stock Status")
    def stock_status(self, obj):
        if obj.is_low_stock:
            return "LOW STOCK"

        return "OK"


# ============================================================
# MEDICINE BATCH
# ============================================================

@admin.register(MedicineBatch)
class MedicineBatchAdmin(admin.ModelAdmin):

    list_display = (
        "medicine",
        "batch_number",
        "expiry_date",
        "purchase_price",
        "selling_price",
        "quantity_received",
        "available_quantity",
        "expiry_status",
        "is_active",
    )

    list_filter = (
        "is_active",
        "expiry_date",
        "medicine__category",
    )

    search_fields = (
        "medicine__name",
        "medicine__medicine_code",
        "batch_number",
    )

    autocomplete_fields = (
        "medicine",
    )

    readonly_fields = (
        "available_quantity",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Expiry Status")
    def expiry_status(self, obj):

        if obj.is_expired:
            return "EXPIRED"

        if obj.is_near_expiry:
            return "NEAR EXPIRY"

        return "OK"


# ============================================================
# STOCK TRANSACTION
# ============================================================

@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):

    list_display = (
        "created_at",
        "medicine_batch",
        "transaction_type",
        "quantity",
        "reference_number",
        "created_by",
    )

    list_filter = (
        "transaction_type",
        "created_at",
    )

    search_fields = (
        "medicine_batch__medicine__name",
        "medicine_batch__medicine__medicine_code",
        "medicine_batch__batch_number",
        "reference_number",
    )

    autocomplete_fields = (
        "medicine_batch",
        "created_by",
    )

    readonly_fields = (
        "created_at",
    )

    ordering = (
        "-created_at",
    )


# ============================================================
# SUPPLIER
# ============================================================

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):

    list_display = (
        "supplier_code",
        "name",
        "gstin",
        "contact_person",
        "phone",
        "email",
        "city",
        "state",
        "is_active",
    )

    list_filter = (
        "is_active",
        "state",
    )

    search_fields = (
        "supplier_code",
        "name",
        "gstin",
        "contact_person",
        "phone",
        "email",
    )

    list_editable = (
        "is_active",
    )

    readonly_fields = (
        "supplier_code",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Supplier Information",
            {
                "fields": (
                    "supplier_code",
                    "name",
                    "gstin",
                    "contact_person",
                    "phone",
                    "alternate_phone",
                    "email",
                )
            },
        ),
        (
            "Address",
            {
                "fields": (
                    "address",
                    "city",
                    "state",
                    "postal_code",
                )
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "is_active",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )


# ============================================================
# PURCHASE / GRN ITEM INLINE
# ============================================================

class PharmacyPurchaseItemInline(admin.TabularInline):

    model = PharmacyPurchaseItem

    extra = 1

    autocomplete_fields = (
        "medicine",
    )

    fields = (
        "medicine",
        "batch_number",
        "manufacturing_date",
        "expiry_date",
        "quantity_received",
        "purchase_price",
        "selling_price",
        "gst_rate",
        "discount",
        "subtotal_display",
        "gst_display",
        "total_display",
        "stock_processed",
    )

    readonly_fields = (
        "subtotal_display",
        "gst_display",
        "total_display",
        "stock_processed",
    )

    @admin.display(description="Subtotal")
    def subtotal_display(self, obj):
        if not obj.pk:
            return "-"

        return obj.subtotal

    @admin.display(description="GST")
    def gst_display(self, obj):
        if not obj.pk:
            return "-"

        return obj.gst_amount

    @admin.display(description="Total")
    def total_display(self, obj):
        if not obj.pk:
            return "-"

        return obj.total_amount


# ============================================================
# PURCHASE / GRN
# ============================================================

@admin.action(description="Receive selected GRNs and update stock")
def receive_selected_grns(modeladmin, request, queryset):

    from .services import process_pharmacy_purchase

    success_count = 0

    for purchase in queryset:

        if purchase.status == PharmacyPurchase.Status.CANCELLED:
            modeladmin.message_user(
                request,
                f"{purchase.grn_number} is cancelled.",
                level=messages.WARNING,
            )
            continue

        if purchase.stock_processed:
            modeladmin.message_user(
                request,
                f"{purchase.grn_number} is already processed.",
                level=messages.WARNING,
            )
            continue

        try:

            purchase.status = PharmacyPurchase.Status.RECEIVED
            purchase.received_by = request.user
            purchase.save(
                update_fields=[
                    "status",
                    "received_by",
                    "received_at",
                    "updated_at",
                ]
            )

            process_pharmacy_purchase(
                purchase,
                user=request.user,
            )

            success_count += 1

        except ValidationError as exc:

            modeladmin.message_user(
                request,
                f"{purchase.grn_number}: {exc}",
                level=messages.ERROR,
            )

    if success_count:
        modeladmin.message_user(
            request,
            f"{success_count} GRN(s) received successfully "
            "and stock updated.",
            level=messages.SUCCESS,
        )


@admin.register(PharmacyPurchase)
class PharmacyPurchaseAdmin(admin.ModelAdmin):

    list_display = (
        "grn_number",
        "grn_date",
        "supplier",
        "invoice_number",
        "status",
        "payment_status",
        "grand_total_display",
        "stock_status",
        "created_by",
        "received_by",
    )

    list_filter = (
        "status",
        "payment_status",
        "grn_date",
        "supplier",
    )

    search_fields = (
        "grn_number",
        "invoice_number",
        "supplier__supplier_code",
        "supplier__name",
    )

    autocomplete_fields = (
        "supplier",
        "created_by",
        "received_by",
    )

    readonly_fields = (
        "grn_number",
        "received_at",
        "stock_processed",
        "created_at",
        "updated_at",
        "grand_total_display",
    )

    date_hierarchy = "grn_date"

    actions = (
        receive_selected_grns,
    )

    inlines = (
        PharmacyPurchaseItemInline,
    )

    fieldsets = (
        (
            "GRN Information",
            {
                "fields": (
                    "grn_number",
                    "supplier",
                    "grn_date",
                    "invoice_number",
                    "invoice_date",
                )
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "status",
                    "payment_status",
                    "stock_processed",
                )
            },
        ),
        (
            "Stock Receipt",
            {
                "fields": (
                    "received_by",
                    "received_at",
                )
            },
        ),
        (
            "Totals",
            {
                "fields": (
                    "grand_total_display",
                )
            },
        ),
        (
            "Notes",
            {
                "fields": (
                    "notes",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def save_model(self, request, obj, form, change):

        if not obj.created_by_id:
            obj.created_by = request.user

        super().save_model(
            request,
            obj,
            form,
            change,
        )

    @admin.display(description="Grand Total")
    def grand_total_display(self, obj):
        return obj.grand_total

    @admin.display(description="Stock")
    def stock_status(self, obj):

        if obj.stock_processed:
            return "PROCESSED"

        if obj.status == PharmacyPurchase.Status.RECEIVED:
            return "PENDING"

        return "NOT RECEIVED"

    def save_related(
        self,
        request,
        form,
        formsets,
        change,
    ):
        super().save_related(
            request,
            form,
            formsets,
            change,
        )

        purchase = form.instance

        if purchase.status == PharmacyPurchase.Status.RECEIVED:
            from .services import process_pharmacy_purchase

            try:
                process_pharmacy_purchase(
                    purchase,
                    user=request.user,
                )

            except ValidationError as exc:

                self.message_user(
                    request,
                    str(exc),
                    level=messages.ERROR,
                )


# ============================================================
# PURCHASE ITEM
# ============================================================

@admin.register(PharmacyPurchaseItem)
class PharmacyPurchaseItemAdmin(admin.ModelAdmin):

    list_display = (
        "purchase",
        "medicine",
        "batch_number",
        "quantity_received",
        "purchase_price",
        "selling_price",
        "gst_rate",
        "total_display",
        "stock_processed",
    )

    list_filter = (
        "stock_processed",
        "gst_rate",
        "purchase__status",
    )

    search_fields = (
        "purchase__grn_number",
        "medicine__name",
        "medicine__medicine_code",
        "batch_number",
    )

    autocomplete_fields = (
        "purchase",
        "medicine",
    )

    readonly_fields = (
        "stock_processed",
        "created_at",
    )

    @admin.display(description="Total")
    def total_display(self, obj):
        return obj.total_amount


# ============================================================
# PRESCRIPTION ITEM
# ============================================================

class PrescriptionItemInline(admin.TabularInline):

    model = PrescriptionItem

    extra = 1

    autocomplete_fields = (
        "medicine",
    )

    fields = (
        "medicine",
        "dose",
        "frequency",
        "duration_value",
        "duration_unit",
        "route",
        "quantity_prescribed",
        "instructions",
        "is_discontinued",
    )


@admin.register(PrescriptionItem)
class PrescriptionItemAdmin(admin.ModelAdmin):

    list_display = (
        "prescription",
        "medicine",
        "dose",
        "frequency",
        "duration_value",
        "duration_unit",
        "route",
        "quantity_prescribed",
        "is_discontinued",
        "created_at",
    )

    list_filter = (
        "duration_unit",
        "route",
        "is_discontinued",
    )

    search_fields = (
        "prescription__prescription_number",
        "prescription__patient__uhid",
        "prescription__patient__first_name",
        "prescription__patient__last_name",
        "medicine__medicine_code",
        "medicine__name",
        "medicine__generic_name",
    )

    autocomplete_fields = (
        "prescription",
        "medicine",
    )

    readonly_fields = (
        "created_at",
    )

    ordering = (
        "-created_at",
    )


# ============================================================
# PRESCRIPTION
# ============================================================

@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):

    list_display = (
        "prescription_number",
        "prescription_date",
        "patient",
        "doctor",
        "opd_visit",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
        "prescription_date",
    )

    search_fields = (
        "prescription_number",
        "patient__uhid",
        "patient__first_name",
        "patient__last_name",
        "doctor__doctor_id",
        "doctor__user__first_name",
        "doctor__user__last_name",
    )

    autocomplete_fields = (
        "opd_visit",
        "patient",
        "doctor",
        "created_by",
    )

    readonly_fields = (
        "prescription_number",
        "created_at",
        "updated_at",
    )

    date_hierarchy = "prescription_date"

    inlines = (
        PrescriptionItemInline,
    )

    fieldsets = (
        (
            "Prescription Information",
            {
                "fields": (
                    "prescription_number",
                    "opd_visit",
                    "patient",
                    "doctor",
                    "prescription_date",
                )
            },
        ),
        (
            "Clinical Information",
            {
                "fields": (
                    "diagnosis_summary",
                    "instructions",
                )
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "status",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def save_model(
        self,
        request,
        obj,
        form,
        change,
    ):

        if not obj.created_by_id:
            obj.created_by = request.user

        super().save_model(
            request,
            obj,
            form,
            change,
        )


# ============================================================
# PHARMACY DISPENSING ITEM INLINE
# ============================================================

class PharmacyDispensingItemInline(admin.TabularInline):

    model = PharmacyDispensingItem

    extra = 1

    autocomplete_fields = (
        "prescription_item",
        "medicine_batch",
    )

    fields = (
        "prescription_item",
        "medicine_batch",
        "quantity_dispensed",
        "selling_price",
        "discount",
        "gst_rate",
        "stock_applied",
    )

    readonly_fields = (
        "stock_applied",
    )


# ============================================================
# PHARMACY DISPENSING
# ============================================================

@admin.register(PharmacyDispensing)
class PharmacyDispensingAdmin(admin.ModelAdmin):

    list_display = (
        "dispensing_number",
        "prescription",
        "patient",
        "status",
        "dispensed_by",
        "dispensed_at",
        "created_at",
    )

    list_filter = (
        "status",
        "dispensed_at",
        "created_at",
    )

    search_fields = (
        "dispensing_number",
        "prescription__prescription_number",
        "patient__uhid",
        "patient__first_name",
        "patient__last_name",
    )

    autocomplete_fields = (
        "prescription",
        "patient",
        "dispensed_by",
    )

    readonly_fields = (
        "dispensing_number",
        "dispensed_at",
        "created_at",
        "updated_at",
    )

    date_hierarchy = "created_at"

    inlines = (
        PharmacyDispensingItemInline,
    )

    fieldsets = (
        (
            "Dispensing Information",
            {
                "fields": (
                    "dispensing_number",
                    "prescription",
                    "patient",
                    "status",
                )
            },
        ),
        (
            "Pharmacy",
            {
                "fields": (
                    "dispensed_by",
                    "dispensed_at",
                    "notes",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def save_model(
        self,
        request,
        obj,
        form,
        change,
    ):

        if not obj.dispensed_by_id:
            obj.dispensed_by = request.user

        super().save_model(
            request,
            obj,
            form,
            change,
        )

    def save_related(
        self,
        request,
        form,
        formsets,
        change,
    ):

        from .services import process_pharmacy_dispensing

        super().save_related(
            request,
            form,
            formsets,
            change,
        )

        if (
            form.instance.status
            != PharmacyDispensing.Status.CANCELLED
        ):

            try:
                process_pharmacy_dispensing(
                    form.instance
                )

            except ValidationError as exc:

                self.message_user(
                    request,
                    str(exc),
                    level=messages.ERROR,
                )


# ============================================================
# PHARMACY DISPENSING ITEM
# ============================================================

@admin.register(PharmacyDispensingItem)
class PharmacyDispensingItemAdmin(admin.ModelAdmin):

    list_display = (
        "dispensing",
        "prescription_item",
        "medicine_batch",
        "quantity_dispensed",
        "selling_price",
        "discount",
        "gst_rate",
        "stock_applied",
        "subtotal_display",
        "gst_display",
        "total_display",
    )

    list_filter = (
        "stock_applied",
        "gst_rate",
    )

    search_fields = (
        "dispensing__dispensing_number",
        "prescription_item__medicine__name",
        "prescription_item__medicine__medicine_code",
        "medicine_batch__batch_number",
    )

    autocomplete_fields = (
        "dispensing",
        "prescription_item",
        "medicine_batch",
    )

    readonly_fields = (
        "stock_applied",
        "created_at",
    )

    ordering = (
        "-created_at",
    )

    @admin.display(description="Subtotal")
    def subtotal_display(self, obj):
        return obj.subtotal

    @admin.display(description="GST")
    def gst_display(self, obj):
        return obj.gst_amount

    @admin.display(description="Total")
    def total_display(self, obj):
        return obj.total_amount