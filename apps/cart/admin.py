from django.contrib import admin

from .models import Cart, CartItem, CartPageSettings, ExpressCheckoutOption


@admin.register(CartPageSettings)
class CartPageSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not CartPageSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ExpressCheckoutOption)
class ExpressCheckoutOptionAdmin(admin.ModelAdmin):
    list_display = ("name", "order", "is_active")
    list_editable = ("order", "is_active")


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = ("product", "size", "color", "quantity", "added_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    """View only: which customer put which product in the cart."""
    list_display = ("user", "item_count", "updated_at")
    search_fields = ("user__email", "user__username")
    readonly_fields = ("user", "updated_at")
    inlines = [CartItemInline]

    @admin.display(description="Pairs in cart")
    def item_count(self, obj):
        return sum(i.quantity for i in obj.items.all())

    def has_add_permission(self, request):
        return False