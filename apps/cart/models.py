# ---------------- NEW: Cart ----------------
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from apps.products.models import ProductVariant


class CartPageSettings(models.Model):
    """One row. Texts and delivery rules for the Cart page (editable in admin)."""
    arrival_text = models.CharField(max_length=80, default="Free & Fast arriving by")
    countdown_text = models.CharField(max_length=60, default="Order within")
    summary_title = models.CharField(max_length=40, default="Summary")
    total_label = models.CharField(max_length=40, default="Total")
    delivery_label = models.CharField(max_length=40, default="Delivery")
    free_label = models.CharField(max_length=40, default="Free")
    delivery_info_text = models.CharField(max_length=80, default="Delivery & return information")
    delivery_info_link = models.CharField(max_length=200, blank=True, default="/shipping-policy")
    checkout_button_text = models.CharField(max_length=40, default="Checkout Securely")
    express_title = models.CharField(max_length=40, default="Express Checkout")
    empty_cart_text = models.CharField(max_length=120, default="Your cart is empty.")
    delivery_days = models.PositiveSmallIntegerField(default=2, help_text="Days to deliver. Used for 'arriving by <day>'.")
    cutoff_hour = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(23)],
        help_text="Hour (0-23) when the countdown ends. 0 = midnight.")
    max_quantity = models.PositiveSmallIntegerField(default=10, help_text="Most pairs one customer can order per size.")
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"),
                                       help_text="0 = delivery is always free.")
    free_delivery_above = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"),
                                              help_text="Orders at or above this amount get free delivery. 0 = no limit.")

    def save(self, *args, **kwargs):
        self.pk = 1  # only one row allowed
        super().save(*args, **kwargs)

    def __str__(self):
        return "Cart page settings"

    class Meta:
        verbose_name_plural = "Cart page settings"


class ExpressCheckoutOption(models.Model):
    name = models.CharField(max_length=50, help_text="For example G Pay, PayPal.")
    image = models.ImageField(upload_to="express_checkout/", blank=True, null=True)
    link = models.CharField(max_length=200, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.name


class Cart(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Customer carts"

    def __str__(self):
        return f"Cart of {self.user}"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("products.Product", on_delete=models.CASCADE, related_name="cart_items")
    size = models.CharField(max_length=10)
    color = models.CharField(max_length=30, blank=True)
    quantity = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-added_at"]
        constraints = [models.UniqueConstraint(fields=["cart", "product", "size", "color"], name="unique_cart_line")]

    def __str__(self):
        return f"{self.product.name} / {self.size} x {self.quantity}"


class OutOfStock(Exception):
    pass


def get_page_settings():
    return CartPageSettings.objects.first() or CartPageSettings()


def delivery_fee_for(subtotal, s=None):
    s = s or get_page_settings()
    if s.delivery_fee <= 0:
        return Decimal("0.00")
    if s.free_delivery_above > 0 and subtotal >= s.free_delivery_above:
        return Decimal("0.00")
    return s.delivery_fee


def delivery_info(s):
    now = timezone.localtime()
    cutoff = now.replace(hour=s.cutoff_hour, minute=0, second=0, microsecond=0)
    if cutoff <= now:
        cutoff += timedelta(days=1)
    return {"arrive_by": (now + timedelta(days=s.delivery_days)).strftime("%A"),
            "seconds_left": int((cutoff - now).total_seconds())}


def _matching(product, size, color):
    qs = ProductVariant.objects.filter(product=product, size=size)
    if color and qs.filter(color__iexact=color).exists():
        return qs.filter(color__iexact=color)
    return qs


def available_stock(product, size, color=""):
    return sum(v.stock for v in _matching(product, size, color))


def take_stock(product, size, color, qty):
    """Call inside transaction.atomic(). Reduces stock or raises OutOfStock."""
    variants = list(_matching(product, size, color).select_for_update().order_by("-stock"))
    have = sum(v.stock for v in variants)
    if have < qty:
        raise OutOfStock(f"Only {have} left for {product.name}, size {size}.")
    left = qty
    for v in variants:
        used = min(v.stock, left)
        v.stock -= used
        v.save(update_fields=["stock"])
        left -= used
        if not left:
            break