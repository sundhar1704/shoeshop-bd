from django.contrib import admin

from .models import Order, OrderItem, OrderStatusHistory, OrderPageSettings


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ("product", "product_name", "brand_name", "size", "color", "quantity", "unit_price", "line_total")

    def has_add_permission(self, request, obj=None):
        return False


class OrderHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    can_delete = False
    readonly_fields = ("status", "note", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(OrderPageSettings)
class OrderPageSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not OrderPageSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "customer", "phone", "total", "payment_method", "payment_status", "status", "created_at")
    list_editable = ("status", "payment_status")
    list_filter = ("status", "payment_method", "payment_status", "created_at")
    search_fields = ("order_number", "first_name", "last_name", "email", "phone", "pincode")
    readonly_fields = ("order_number", "user", "first_name", "last_name", "email", "phone", "address_line1",
                       "city", "state", "landmark", "pincode", "payment_method", "subtotal", "delivery_fee",
                       "total", "created_at", "updated_at")
    inlines = [OrderItemInline, OrderHistoryInline]

    @admin.display(description="Customer")
    def customer(self, obj):
        return f"{obj.first_name} {obj.last_name}"

    def has_add_permission(self, request):
        return False