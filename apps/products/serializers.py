import re

from rest_framework import serializers
from apps.categories.models import Category
from .models import (Product, ProductImage, ProductVariant, Banner, HomeContent, Subscriber,
                     AboutPage, AboutFeature, ContactPage, Enquiry)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "image", "is_active"]
        read_only_fields = ["slug"]


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "product", "image", "is_main"]


class ProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = ["id", "product", "size", "color", "stock"]


class ProductSerializer(serializers.ModelSerializer):
    final_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)
    # write-only helpers used by the admin form
    main_image = serializers.ImageField(write_only=True, required=False)
    sizes = serializers.CharField(write_only=True, required=False, allow_blank=True)
    stock = serializers.IntegerField(write_only=True, required=False, min_value=0)

    class Meta:
        model = Product
        fields = ["id", "name", "slug", "brand", "description", "price", "discount_percent",
                  "final_price", "category", "category_name", "is_active", "is_featured",
                  "images", "variants", "created_at", "main_image", "sizes", "stock"]
        read_only_fields = ["slug"]

    def validate_discount_percent(self, v):
        if v > 90:
            raise serializers.ValidationError("Discount cannot be more than 90%.")
        return v

    def _extras(self, data):
        return data.pop("main_image", None), data.pop("sizes", ""), data.pop("stock", None)

    def _save_extras(self, product, image, sizes, stock):
        if image:
            product.images.filter(is_main=True).delete()
            ProductImage.objects.create(product=product, image=image, is_main=True)
        for s in [x.strip() for x in (sizes or "").split(",") if x.strip()]:
            ProductVariant.objects.update_or_create(
                product=product, size=s, color="",
                defaults={"stock": 10 if stock is None else stock})

    def create(self, data):
        extras = self._extras(data)
        product = super().create(data)
        self._save_extras(product, *extras)
        return product

    def update(self, instance, data):
        extras = self._extras(data)
        product = super().update(instance, data)
        self._save_extras(product, *extras)
        return product


class BannerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Banner
        fields = "__all__"


class HomeContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = HomeContent
        fields = "__all__"


class SubscriberSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscriber
        fields = ["email"]


class AboutFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = AboutFeature
        fields = ["id", "title", "text"]


class AboutPageSerializer(serializers.ModelSerializer):
    # only the active feature blocks, in the order set in admin
    features = serializers.SerializerMethodField()

    class Meta:
        model = AboutPage
        fields = ["about_title", "about_text", "mission_title", "mission_text",
                  "side_image", "center_image", "features"]

    def get_features(self, obj):
        features = AboutFeature.objects.filter(is_active=True)
        return AboutFeatureSerializer(features, many=True).data


class ContactPageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactPage
        fields = ["title", "section_title", "inquiry_label", "inquiry_phone",
                  "other_label", "other_phone_1", "other_phone_2", "working_hours",
                  "email", "image", "enquiry_title"]


class EnquirySerializer(serializers.ModelSerializer):
    class Meta:
        model = Enquiry
        fields = ["name", "email", "phone", "message"]

    def validate_name(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Name must be at least 2 characters.")
        return value

    def validate_email(self, value):
        return value.strip().lower()  # always save email in lowercase

    def validate_phone(self, value):
        phone = re.sub(r"[\s-]", "", value)  # remove spaces and dashes
        if phone.startswith("+91"):
            phone = phone[3:]
        if not re.fullmatch(r"[6-9]\d{9}", phone):
            raise serializers.ValidationError("Enter a valid 10-digit Indian mobile number.")
        return phone

    def validate_message(self, value):
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError("Message must be at least 10 characters.")
        return value

# ---------------- NEW: Products listing page ----------------
from .models import Color  # NEW


class ColorMiniSerializer(serializers.ModelSerializer):
    hex = serializers.CharField(source="hex_code")

    class Meta:
        model = Color
        fields = ["id", "name", "hex"]


class ShopProductSerializer(serializers.ModelSerializer):
    """Card on the Products listing page."""
    brand_name = serializers.SerializerMethodField()
    final_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    colors = ColorMiniSerializer(many=True, read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)
    image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ["id", "name", "slug", "brand_name", "rating", "price", "discount_percent",
                  "final_price", "colors", "is_multicolor", "category_slug", "image"]

    def get_brand_name(self, obj):
        return obj.brand_link.name if obj.brand_link_id else obj.brand

    def get_image(self, obj):
        images = list(obj.images.all())
        main = next((i for i in images if i.is_main), images[0] if images else None)
        if not main:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(main.image.url) if request else main.image.url