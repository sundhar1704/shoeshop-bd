# ---------------- NEW: Cart API ----------------
from decimal import Decimal
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.products.models import Product
from .models import (Cart, CartItem, ExpressCheckoutOption, available_stock,
                     delivery_fee_for, delivery_info, get_page_settings)


def bad(message):
    return Response({"detail": message}, status=400)


class SelectionSerializer(serializers.Serializer):
    """product + size + colour + quantity (used by Add to Cart and Buy Now)."""
    product_id = serializers.IntegerField()
    size = serializers.CharField(max_length=10)
    color = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    quantity = serializers.IntegerField(min_value=1, default=1)

    def validate(self, data):
        product = Product.objects.filter(pk=data["product_id"], is_active=True).first()
        if not product:
            raise serializers.ValidationError({"product_id": "Product not found."})
        data["size"], data["color"] = data["size"].strip(), data["color"].strip()
        if not product.variants.filter(size=data["size"]).exists():
            raise serializers.ValidationError({"size": "This size is not available."})
        if data["color"] and not product.colors.filter(name__iexact=data["color"]).exists():
            raise serializers.ValidationError({"color": "This colour is not available."})
        data["product"] = product
        return data


def main_image(request, product):
    images = list(product.images.all())
    main = next((i for i in images if i.is_main), images[0] if images else None)
    if not main:
        return None
    return request.build_absolute_uri(main.image.url) if request else main.image.url


def _size_key(size):
    return (0, int(size), "") if size.isdigit() else (1, 0, size)


def make_line(request, s, product, size, color, qty, item_id=None):
    stock = available_stock(product, size, color)
    price = product.final_price
    sizes = sorted({v.size for v in product.variants.all()}, key=_size_key)
    return {
        "id": item_id, "product_id": product.id, "slug": product.slug,
        "brand_name": product.brand_link.name if product.brand_link_id else product.brand,
        "name": product.name, "image": main_image(request, product),
        "size": size, "color": color, "quantity": qty, "sizes": sizes,
        "stock": stock, "in_stock": stock >= qty, "max_quantity": min(stock, s.max_quantity),
        "mrp": product.price, "unit_price": price, "line_total": price * qty,
    }


def page_texts(request, s):
    options = ExpressCheckoutOption.objects.filter(is_active=True)
    return {
        "arrival_text": s.arrival_text, "countdown_text": s.countdown_text,
        "summary_title": s.summary_title, "total_label": s.total_label,
        "delivery_label": s.delivery_label, "free_label": s.free_label,
        "delivery_info_text": s.delivery_info_text, "delivery_info_link": s.delivery_info_link,
        "checkout_button_text": s.checkout_button_text, "express_title": s.express_title,
        "empty_cart_text": s.empty_cart_text,
        "express": [{"name": o.name, "link": o.link,
                     "image": request.build_absolute_uri(o.image.url) if o.image else None} for o in options],
    }


def build_payload(request, entries):
    """entries = [(product, size, color, qty, item_id)]. Used by Cart AND Checkout, so totals always match."""
    s = get_page_settings()
    lines = [make_line(request, s, *e) for e in entries]
    subtotal = sum((l["line_total"] for l in lines), Decimal("0.00"))
    fee = delivery_fee_for(subtotal, s) if lines else Decimal("0.00")
    return {
        "items": lines, "count": sum(l["quantity"] for l in lines),
        "totals": {"subtotal": subtotal, "delivery_fee": fee,
                   "delivery_is_free": fee == 0, "total": subtotal + fee},
        "delivery": delivery_info(s), "page": page_texts(request, s),
    }


def cart_entries(cart):
    items = (cart.items.filter(product__is_active=True)
             .select_related("product", "product__brand_link")
             .prefetch_related("product__images", "product__variants", "product__colors"))
    return [(i.product, i.size, i.color, i.quantity, i.id) for i in items]


def cart_count(user):
    return CartItem.objects.filter(cart__user=user).aggregate(n=Sum("quantity"))["n"] or 0


class CartView(APIView):
    """GET /api/cart/"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        cart, _ = Cart.objects.get_or_create(user=request.user)
        return Response(build_payload(request, cart_entries(cart)))


class CartCountView(APIView):
    """GET /api/cart/count/ (number on the navbar cart badge)"""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        n = cart_count(request.user) if request.user.is_authenticated else 0
        return Response({"count": n})


class CartItemAddView(APIView):
    """POST /api/cart/items/  {product_id, size, color, quantity}"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        ser = SelectionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        s = get_page_settings()
        limit = min(available_stock(d["product"], d["size"], d["color"]), s.max_quantity)
        if limit <= 0:
            return bad("This size is out of stock.")
        cart, _ = Cart.objects.get_or_create(user=request.user)
        item, _ = CartItem.objects.get_or_create(
            cart=cart, product=d["product"], size=d["size"], color=d["color"], defaults={"quantity": 0})
        new_qty = item.quantity + d["quantity"]
        if new_qty > limit:
            if not item.quantity:
                item.delete()
            return bad(f"Only {limit} available for this size.")
        item.quantity = new_qty
        item.save()
        return Response({"message": "Added to cart.", "count": cart_count(request.user)}, status=201)


class CartItemDetailView(APIView):
    """PATCH /api/cart/items/<id>/ {size?, quantity?}   DELETE /api/cart/items/<id>/"""
    permission_classes = [permissions.IsAuthenticated]

    def _item(self, request, pk):
        return get_object_or_404(CartItem, pk=pk, cart__user=request.user)

    def patch(self, request, pk):
        item = self._item(request, pk)
        size = str(request.data.get("size", item.size)).strip()
        try:
            qty = int(request.data.get("quantity", item.quantity))
        except (TypeError, ValueError):
            return bad("Quantity must be a number.")
        if qty < 1:
            return bad("Quantity must be at least 1.")
        if not item.product.variants.filter(size=size).exists():
            return bad("This size is not available.")
        limit = min(available_stock(item.product, size, item.color), get_page_settings().max_quantity)
        other = (CartItem.objects.filter(cart=item.cart, product=item.product, size=size, color=item.color)
                 .exclude(pk=item.pk).first())
        total = qty + (other.quantity if other else 0)
        if total > limit:
            return bad(f"Only {limit} available for this size.")
        cart = item.cart
        if other:  # same size already in cart: merge the two lines
            other.quantity = total
            other.save()
            item.delete()
        else:
            item.size, item.quantity = size, qty
            item.save()
        return Response(build_payload(request, cart_entries(cart)))

    def delete(self, request, pk):
        item = self._item(request, pk)
        cart = item.cart
        item.delete()
        return Response(build_payload(request, cart_entries(cart)))