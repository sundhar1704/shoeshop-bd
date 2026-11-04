# ---------------- Checkout, Orders, Thank you, Track, Cancel ----------------
import re
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, serializers
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView
from apps.cart.models import (Cart, OutOfStock, delivery_fee_for, get_page_settings, take_stock)
from apps.cart.views import SelectionSerializer, bad, build_payload, cart_entries, main_image
from apps.products.models import ProductVariant
from .models import Order, OrderItem, OrderPageSettings
from datetime import timedelta


class CheckoutThrottle(SimpleRateThrottle):
    """Limits placing orders: 20 per hour per customer when live."""
    scope = "checkout"

    def get_rate(self):
        return "1000/hour" if settings.DEBUG else "20/hour"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}


class CheckoutSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=["cart", "buy_now"])
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=20)
    address_line1 = serializers.CharField(min_length=5, max_length=255)
    city = serializers.CharField(max_length=100)
    state = serializers.CharField(max_length=100)
    landmark = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    pincode = serializers.CharField(max_length=6)
    payment_method = serializers.ChoiceField(choices=["COD", "ONLINE"])
    # Card fields are only CHECKED, then thrown away. They are never saved or logged.
    card_holder_name = serializers.CharField(max_length=100, required=False, allow_blank=True, write_only=True)
    card_number = serializers.CharField(max_length=25, required=False, allow_blank=True, write_only=True)
    cvv = serializers.CharField(max_length=4, required=False, allow_blank=True, write_only=True)
    expiry = serializers.CharField(max_length=5, required=False, allow_blank=True, write_only=True)

    def validate_first_name(self, v):
        return self._name(v, "First name")

    def validate_last_name(self, v):
        return self._name(v, "Last name")

    @staticmethod
    def _name(v, label):
        v = v.strip()
        if not re.fullmatch(r"[A-Za-z .'-]{1,100}", v):
            raise serializers.ValidationError(f"{label} can have letters only.")
        return v

    def validate_email(self, v):
        return v.strip().lower()

    def validate_phone(self, v):
        phone = re.sub(r"[\s-]", "", v)
        if phone.startswith("+91"):
            phone = phone[3:]
        if not re.fullmatch(r"[6-9]\d{9}", phone):
            raise serializers.ValidationError("Enter a valid 10-digit Indian mobile number.")
        return phone

    def validate_pincode(self, v):
        v = v.strip()
        if not re.fullmatch(r"[1-9]\d{5}", v):
            raise serializers.ValidationError("Enter a valid 6-digit pincode.")
        return v

    def validate(self, data):
        if data["payment_method"] != "ONLINE":
            for k in ("card_holder_name", "card_number", "cvv", "expiry"):
                data.pop(k, None)  # Cash on Delivery: ignore card boxes
            return data
        errors = {}
        name = data.get("card_holder_name", "").strip()
        if not re.fullmatch(r"[A-Za-z .'-]{2,100}", name):
            errors["card_holder_name"] = "Enter the name on the card (letters only)."
        number = re.sub(r"[\s-]", "", data.get("card_number", ""))
        if not re.fullmatch(r"\d{16}", number):
            errors["card_number"] = "Card number must be exactly 16 digits."
        if not re.fullmatch(r"\d{3,4}", data.get("cvv", "").strip()):
            errors["cvv"] = "CVV must be 3 or 4 digits."
        m = re.fullmatch(r"(0[1-9]|1[0-2])/(\d{2})", data.get("expiry", "").strip())
        if not m:
            errors["expiry"] = "Use the format MM/YY."
        else:
            today = timezone.localdate()
            if (2000 + int(m.group(2)), int(m.group(1))) < (today.year, today.month):
                errors["expiry"] = "This card has expired."
        if errors:
            raise serializers.ValidationError(errors)
        for k in ("card_holder_name", "card_number", "cvv", "expiry"):
            data.pop(k, None)  # discard: never saved
        return data


def get_entries(request, params, source):
    """Buy Now -> the one product sent by the page. Cart -> everything in the cart."""
    if source == "buy_now":
        sel = SelectionSerializer(data=params)
        sel.is_valid(raise_exception=True)
        d = sel.validated_data
        return [(d["product"], d["size"], d["color"], d["quantity"], None)], None
    cart = Cart.objects.filter(user=request.user).first()
    return (cart_entries(cart) if cart else []), cart


class CheckoutSummaryView(APIView):
    """GET /api/orders/summary/?source=cart   or   ?source=buy_now&product_id=1&size=41&quantity=1"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        source = request.query_params.get("source", "cart")
        if source not in ("cart", "buy_now"):
            return bad("Invalid source.")
        entries, _ = get_entries(request, request.query_params, source)
        if not entries:
            return bad("Your cart is empty.")
        u = request.user
        data = build_payload(request, entries)
        data["prefill"] = {"first_name": u.first_name, "last_name": u.last_name,
                           "email": u.email, "phone": getattr(u, "phone", "")}
        ps = OrderPageSettings.objects.first() or OrderPageSettings()
        data["checkout"] = {
            "title": ps.checkout_title, "summary_title": ps.order_summary_title,
            "complete_title": ps.complete_title, "personal_title": ps.personal_title,
            "payment_title": ps.payment_title, "cod_label": ps.cod_label,
            "shipping_title": ps.shipping_title, "cancel_text": ps.cancel_text,
            "order_button_text": ps.order_button_text,
        }
        return Response(data)


class CheckoutView(APIView):
    """POST /api/orders/checkout/ - places the order (both Buy Now and Cart go here)."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [CheckoutThrottle]

    def post(self, request):
        ser = CheckoutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        entries, cart = get_entries(request, request.data, d["source"])
        if not entries:
            return bad("Your cart is empty.")
        s = get_page_settings()
        try:
            with transaction.atomic():
                order = Order.objects.create(
                    user=request.user, first_name=d["first_name"].strip(), last_name=d["last_name"].strip(),
                    email=d["email"], phone=d["phone"], address_line1=d["address_line1"].strip(),
                    city=d["city"].strip(), state=d["state"].strip(), landmark=d["landmark"].strip(),
                    pincode=d["pincode"], payment_method=d["payment_method"])
                subtotal = Decimal("0.00")
                for product, size, color, qty, _ in entries:
                    if qty > s.max_quantity:
                        raise OutOfStock(f"You can order at most {s.max_quantity} pairs of one size.")
                    take_stock(product, size, color, qty)
                    price = product.final_price
                    OrderItem.objects.create(
                        order=order, product=product, product_name=product.name,
                        brand_name=product.brand_link.name if product.brand_link_id else product.brand,
                        size=size, color=color, quantity=qty, unit_price=price, line_total=price * qty)
                    subtotal += price * qty
                fee = delivery_fee_for(subtotal, s)
                order.subtotal, order.delivery_fee, order.total = subtotal, fee, subtotal + fee
                order.save()
                if cart:
                    cart.items.all().delete()
        except OutOfStock as e:
            return bad(str(e))
        return Response({
            "order_number": order.order_number, "total": order.total,
            "payment_method": order.payment_method,
            "next": "pay_online" if order.payment_method == "ONLINE" else "done",
            "message": "Thank you! Your order has been placed.",
        }, status=201)


class OrderItemSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = ["product_name", "brand_name", "size", "color", "quantity", "unit_price", "line_total", "image"]

    def get_image(self, obj):
        return main_image(self.context.get("request"), obj.product) if obj.product_id else None


class OrderSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ["order_number", "status", "status_label", "payment_method", "payment_status",
                  "subtotal", "delivery_fee", "total", "first_name", "last_name", "email", "phone",
                  "address_line1", "city", "state", "landmark", "pincode", "created_at", "items"]


class MyOrdersView(generics.ListAPIView):
    """GET /api/orders/"""
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).prefetch_related("items__product__images")


class MyOrderDetailView(generics.RetrieveAPIView):
    """GET /api/orders/<order_number>/"""
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "order_number"

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).prefetch_related("items__product__images")


FLOW = ["pending", "confirmed", "processing", "packed", "shipped", "out_for_delivery", "delivered"]
LABELS = dict(Order.STATUS)

RANK = {"pending": 0, "confirmed": 0, "processing": 0, "packed": 1,
        "shipped": 2, "out_for_delivery": 2, "delivered": 3}


def fmt_time(dt):
    dt = timezone.localtime(dt)
    return dt.strftime("%b %d,%Y | %I:%M ") + dt.strftime("%p").lower()  # May 21,2025 | 03:45 pm


def fmt_day(d):
    return f"{d:%a}, {d:%b} {d.day}"  # Sun, May 31


class OrderThanksView(APIView):
    """GET /api/orders/<order_number>/thanks/ (Thank you page)"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, order_number):
        order = get_object_or_404(Order, order_number=order_number, user=request.user)
        s = OrderPageSettings.objects.first() or OrderPageSettings()
        return Response({
            "order_number": order.order_number, "total": order.total, "payment_method": order.payment_method,
            "title": s.thank_title, "text": s.thank_text, "ship_days_text": s.ship_days_text,
            "order_number_label": s.order_number_label,
            "view_button_text": s.view_button_text, "track_button_text": s.track_button_text,
        })

class OrderTrackView(APIView):
    """GET /api/orders/<order_number>/track/ (Your Order + Track page)"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, order_number):
        order = get_object_or_404(
            Order.objects.prefetch_related("history", "items__product__images"),
            order_number=order_number, user=request.user)
        s = OrderPageSettings.objects.first() or OrderPageSettings()
        history = list(order.history.all())
        ended = order.status in ("cancelled", "returned")
        reached = max([RANK[h.status] for h in history if h.status in RANK] or [0]) if ended \
            else RANK.get(order.status, 0)

        def first_time(rank):  # when the order first reached this step
            for h in history:
                if RANK.get(h.status) == rank:
                    return h.created_at
            return order.created_at if rank == 0 else None

        transit_note = next((h.note for h in reversed(history)
                             if RANK.get(h.status) == 2 and h.note), "") or order.tracking_note
        config = [
            ("placed", s.placed_label, "cart"),
            ("dispatched", s.dispatched_label, "home"),
            ("transit", s.transit_label, "truck"),
            ("delivered", s.delivered_label, "thumbs_up"),
        ]
        steps = []
        for i, (key, label, icon) in enumerate(config):
            done = i <= reached
            when = first_time(i) if done else None
            when_text = fmt_time(when) if when else ""
            if i == 0:
                detail = when_text
            elif i == 1:
                detail = when_text if done else s.dispatched_pending_text
            elif i == 2:
                detail = (transit_note or s.transit_default_text) if done else s.transit_pending_text
            else:
                detail = when_text if done else s.delivered_pending_text
            steps.append({"key": key, "label": label, "icon": icon, "done": done,
                          "current": done and i == reached and not ended,
                          "detail": detail, "time": when.isoformat() if when else None})

        exp = order.expected_delivery or (order.created_at.date() + timedelta(days=s.expected_days))
        if order.status == "delivered":
            d = first_time(3)
            expected_text = f"{s.delivered_prefix} {fmt_day(timezone.localtime(d).date())}" if d else ""
        elif ended:
            expected_text = ""
        else:
            expected_text = f"{s.expected_prefix} {fmt_day(exp)}"

        end_time = next((h.created_at for h in history if h.status == order.status), None) if ended else None
        if order.payment_method == "COD":
            payment_label = "Cash on Delivery"
        else:
            payment_label = "Paid online" if order.payment_status == "paid" else "Online payment"

        return Response({
            "title": s.track_title, "order_number": order.order_number,
            "status": order.status, "status_label": LABELS[order.status],
            "payment_label": payment_label, "payment_status": order.payment_status, "total": order.total,
            "placed_text": fmt_time(order.created_at), "expected_text": expected_text,
            "items": OrderItemSerializer(order.items.all(), many=True, context={"request": request}).data,
            "steps": steps,
            "updates": [{"status_label": LABELS[h.status], "note": h.note, "time_text": fmt_time(h.created_at)}
                        for h in reversed(history) if h.note],
            "ended": {"label": LABELS[order.status], "time_text": fmt_time(end_time) if end_time else ""}
                     if ended else None,
            "can_cancel": order.status in ("pending", "confirmed"),
            "cancel_button_text": s.cancel_button_text,
        })

class OrderCancelView(APIView):
    """POST /api/orders/<order_number>/cancel/ (only before it is processed)"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, order_number):
        with transaction.atomic():
            order = get_object_or_404(Order.objects.select_for_update(), order_number=order_number, user=request.user)
            if order.status not in ("pending", "confirmed"):
                return bad("This order can no longer be cancelled.")
            for item in order.items.all():  # give the stock back
                if item.product_id:
                    v = ProductVariant.objects.select_for_update().filter(
                        product_id=item.product_id, size=item.size).order_by("-stock").first()
                    if v:
                        v.stock += item.quantity
                        v.save(update_fields=["stock"])
            order.status = "cancelled"
            order.save()
        return Response({"message": "Your order has been cancelled.", "status": order.status})




class OrderViewDetailsView(APIView):
    """GET /api/orders/<order_number>/view/ (View Order page: items + amount details)"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, order_number):
        order = get_object_or_404(
            Order.objects.prefetch_related("items__product__images"),
            order_number=order_number, user=request.user)
        s = OrderPageSettings.objects.first() or OrderPageSettings()

        if order.payment_method == "COD":
            payment_label = "Cash on Delivery"
        else:
            payment_label = "Paid online" if order.payment_status == "paid" else "Online payment"

        items = OrderItemSerializer(order.items.all(), many=True, context={"request": request}).data
        parts = [order.address_line1, order.landmark, order.city, order.state, order.pincode]

        return Response({
            "title": s.track_title,
            "order_number": order.order_number,
            "status": order.status,
            "status_label": LABELS[order.status],
            "placed_text": fmt_time(order.created_at),
            "payment_label": payment_label,
            "payment_status": order.payment_status,
            "items": items,
            "total_quantity": sum(i["quantity"] for i in items),
            "amount": {
                "subtotal": order.subtotal,
                "delivery_fee": order.delivery_fee,
                "delivery_text": "Free" if order.delivery_fee == 0 else None,
                "total": order.total,
            },
            "address": {
                "name": f"{order.first_name} {order.last_name}".strip(),
                "phone": order.phone,
                "email": order.email,
                "text": ", ".join(p for p in parts if p),
            },
            "can_cancel": order.status in ("pending", "confirmed"),
        })