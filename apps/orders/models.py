from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class Order(models.Model):
    STATUS = [
        ("pending", "Pending"), ("confirmed", "Confirmed"), ("processing", "Processing"),
        ("packed", "Packed"), ("shipped", "Shipped"), ("out_for_delivery", "Out for Delivery"),
        ("delivered", "Delivered"), ("cancelled", "Cancelled"), ("returned", "Returned"),
    ]
    PAYMENT_METHODS = [("COD", "Cash on Delivery"), ("ONLINE", "Online payment")]
    PAYMENT_STATUS = [("pending", "Pending"), ("paid", "Paid"), ("failed", "Failed"), ("refunded", "Refunded")]

    order_number = models.CharField(max_length=20, unique=True, null=True, blank=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="orders")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=15)
    address_line1 = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    landmark = models.CharField(max_length=150, blank=True)
    pincode = models.CharField(max_length=6)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS, default="COD")
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS, default="pending")
    payment_reference = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="pending")
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # NEW for Track Order
    tracking_note = models.CharField(
        max_length=200, blank=True,
        help_text="Shown under 'Order in transit'. Example: Reached at Tenkasi, Post office")
    expected_delivery = models.DateField(
        null=True, blank=True,
        help_text="Filled automatically when the order is placed. You can change it.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._old_status = self.status
        self._old_note = self.tracking_note

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if is_new and not self.expected_delivery:
            s = OrderPageSettings.objects.first()
            self.expected_delivery = timezone.localdate() + timedelta(days=s.expected_days if s else 7)
        if self.status == "delivered" and self.payment_method == "COD" and self.payment_status == "pending":
            self.payment_status = "paid"  # cash is collected on delivery
        super().save(*args, **kwargs)
        if not self.order_number:
            self.order_number = f"SU{timezone.localdate():%y%m%d}{self.pk:05d}"
            super().save(update_fields=["order_number"])
        status_changed = is_new or self.status != self._old_status
        note_changed = (not is_new) and self.tracking_note != self._old_note
        if status_changed or note_changed:  # every change is remembered with its date and time
            OrderStatusHistory.objects.create(
                order=self, status=self.status, note="" if is_new else self.tracking_note)
        self._old_status, self._old_note = self.status, self.tracking_note

    def __str__(self):
        return self.order_number or f"Order {self.pk}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("products.Product", on_delete=models.SET_NULL, null=True, blank=True)
    product_name = models.CharField(max_length=200)
    brand_name = models.CharField(max_length=100, blank=True)
    size = models.CharField(max_length=10)
    color = models.CharField(max_length=30, blank=True)
    quantity = models.PositiveSmallIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.product_name} x {self.quantity}"


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="history")
    status = models.CharField(max_length=20, choices=Order.STATUS)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "Order status history"

    def __str__(self):
        return f"{self.order} - {self.status}"


class OrderPageSettings(models.Model):
    """One row. Texts of the Thank You and Your Order / Track pages."""
    thank_title = models.CharField(max_length=80, default="Thankyou for your ordering")
    thank_text = models.CharField(max_length=120, default="We’ve received your order will ship in")
    ship_days_text = models.CharField(max_length=40, default="5-7 business days")
    order_number_label = models.CharField(max_length=60, default="Your order number is")
    view_button_text = models.CharField(max_length=30, default="View Order")
    track_button_text = models.CharField(max_length=30, default="Track Order")
    track_title = models.CharField(max_length=60, default="Your Order")
    cancel_button_text = models.CharField(max_length=30, default="Cancel Order")
    # NEW for the Track page
    expected_days = models.PositiveSmallIntegerField(default=7, help_text="Days from the order date to the expected delivery date.")
    expected_prefix = models.CharField(max_length=40, default="Exp : Delivery by")
    delivered_prefix = models.CharField(max_length=40, default="Delivered on")
    placed_label = models.CharField(max_length=40, default="Order Placed")
    dispatched_label = models.CharField(max_length=40, default="Order Dispatched")
    transit_label = models.CharField(max_length=40, default="Order in transit")
    delivered_label = models.CharField(max_length=40, default="Delivered successfully")
    dispatched_pending_text = models.CharField(max_length=60, default="Not dispatched yet")
    transit_pending_text = models.CharField(max_length=60, default="Not in transit yet")
    transit_default_text = models.CharField(max_length=60, default="On the way to you")
    delivered_pending_text = models.CharField(max_length=60, default="Not delivered yet")
        # NEW for the Checkout page
    checkout_title = models.CharField(max_length=60, default="Checkout")
    order_summary_title = models.CharField(max_length=60, default="Order Summary")
    complete_title = models.CharField(max_length=60, default="Complete Your Order")
    personal_title = models.CharField(max_length=60, default="Personal Details")
    payment_title = models.CharField(max_length=60, default="Payment Details")
    cod_label = models.CharField(max_length=40, default="Cash on Delivery")
    shipping_title = models.CharField(max_length=60, default="Shipping Address")
    cancel_text = models.CharField(max_length=30, default="Cancel")
    order_button_text = models.CharField(max_length=30, default="Order Now")

    def save(self, *args, **kwargs):
        self.pk = 1  # only one row allowed
        super().save(*args, **kwargs)

    def __str__(self):
        return "Order page settings"

    class Meta:
        verbose_name_plural = "Order page settings"