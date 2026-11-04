from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Product, ProductImage, ProductVariant, Banner, HomeContent, Subscriber,
    AboutPage, AboutFeature, ContactPage, Enquiry,
    Style, SubStyle, Brand, Color, SizeOption, OfferLink,  # NEW
)


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1


class SingleRowAdmin(admin.ModelAdmin):
    """For pages that must have only one row (About, Contact)."""

    def has_add_permission(self, request):
        return not self.model.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "brand_link", "style", "price", "discount_percent", "rating", "is_featured", "is_active")  # NEW columns
    list_filter = ("category", "brand_link", "style", "is_multicolor", "is_featured", "is_active")  # NEW filters
    search_fields = ("name", "brand")
    list_editable = ("is_featured", "is_active")
    filter_horizontal = ("colors",)  # NEW: easy colour picker
    inlines = [ProductImageInline, ProductVariantInline]


# ---------------- NEW: menu, filter and offer pages ----------------

class SubStyleInline(admin.TabularInline):  # NEW
    model = SubStyle
    extra = 3


@admin.register(Style)  # NEW
class StyleAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "order", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name",)
    list_editable = ("order", "is_active")
    inlines = [SubStyleInline]


@admin.register(Brand)  # NEW
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    search_fields = ("name",)
    list_editable = ("is_active",)


@admin.register(Color)  # NEW
class ColorAdmin(admin.ModelAdmin):
    list_display = ("name", "swatch", "hex_code", "order", "is_active")
    list_editable = ("hex_code", "order", "is_active")

    @admin.display(description="Colour")
    def swatch(self, obj):
        return format_html(
            '<span style="display:inline-block;width:22px;height:22px;border-radius:50%;'
            'border:1px solid #999;background:{}"></span>',
            obj.hex_code,
        )


@admin.register(SizeOption)  # NEW
class SizeOptionAdmin(admin.ModelAdmin):
    list_display = ("group", "label", "order", "is_active")
    list_filter = ("group", "is_active")
    list_editable = ("order", "is_active")


@admin.register(OfferLink)  # NEW
class OfferLinkAdmin(admin.ModelAdmin):
    list_display = ("title", "link", "is_heading", "order", "is_active")
    list_editable = ("order", "is_active")


# ---------------- OLD pages (unchanged) ----------------

@admin.register(AboutPage)
class AboutPageAdmin(SingleRowAdmin):
    pass


@admin.register(AboutFeature)
class AboutFeatureAdmin(admin.ModelAdmin):
    list_display = ("title", "order", "is_active")
    list_editable = ("order", "is_active")


@admin.register(ContactPage)
class ContactPageAdmin(SingleRowAdmin):
    pass


@admin.register(Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "created_at", "is_read")
    list_filter = ("is_read", "created_at")
    search_fields = ("name", "email", "phone", "message")
    list_editable = ("is_read",)
    readonly_fields = ("name", "email", "phone", "message", "created_at")

    def has_add_permission(self, request):
        return False  # enquiries come only from the website form


admin.site.register(Banner)
admin.site.register(HomeContent)
admin.site.register(Subscriber)

# ---------------- NEW: group the admin home page in a fixed order ----------------
# Only changes how the admin home page is arranged. No database change.

ADMIN_SECTIONS = [
    ("1. Home Page", "home_page", ["Banner", "HomeContent", "Subscriber"]),
    ("2. About Page", "about_page", ["AboutPage", "AboutFeature"]),
    ("3. Contact Page", "contact_page", ["ContactPage", "Enquiry"]),
    ("4. Shop Products", "shop_products", ["Category", "Product"]),
    ("5. Menus and Filters", "menus_filters", ["Style", "Brand", "Color", "SizeOption", "OfferLink"]),
    ("6. Product Details Page", "product_page", ["ProductPageSettings", "ProductHighlight", "PaymentLogo", "ProductReview"]),
    ("7. Cart Page", "cart_page", ["CartPageSettings", "ExpressCheckoutOption", "Cart"]),
    ("8. Orders", "orders_section", ["Order", "OrderPageSettings"]),
    ("9. Customers and Login", "customers_login", ["User", "LoginActivity"]),
    ("10. Other", "other", ["Group"]),
]

# nicer names shown on the admin home page only
DISPLAY_NAMES = {
    "Banner": "Banners (home slider)",
    "HomeContent": "Home content (overview, offer bar, footer)",
    "Subscriber": "Subscribers",
    "AboutPage": "About page text and images",
    "AboutFeature": "About page 3 feature blocks",
    "ContactPage": "Contact page text and image",
    "Enquiry": "Enquiries (from website form)",
    "Category": "Categories (Womens, Mens, Kids)",
    "Product": "Products",
    "Style": "Styles and sub styles (menu)",
    "Brand": "Brands",
    "Color": "Colors",
    "SizeOption": "Size options",
    "OfferLink": "Offers menu lines",
    "User": "Users",
    "LoginActivity": "Login activities",
    "Group": "Groups",
}

_original_get_app_list = admin.site.get_app_list


def _grouped_app_list(request, app_label=None):
    app_list = _original_get_app_list(request, app_label)
    if app_label:  # keep the normal page when one app is opened
        return app_list

    found = {}
    for app in app_list:
        for m in app["models"]:
            found[m["object_name"]] = m

    grouped, used = [], set()
    for title, slug, names in ADMIN_SECTIONS:
        items = [{**found[n], "name": DISPLAY_NAMES.get(n, found[n]["name"])}
                 for n in names if n in found]  # keeps the order written above
        if not items:
            continue
        used.update(n for n in names if n in found)
        grouped.append({
            "name": title,
            "app_label": slug,
            "app_url": items[0].get("admin_url") or "#",
            "has_module_perms": True,
            "models": items,
        })

    rest = [m for app in app_list for m in app["models"] if m["object_name"] not in used]
    if rest:  # anything new we add later (Cart, Orders...) still shows here
        grouped.append({"name": "8. More", "app_label": "more",
                        "app_url": rest[0].get("admin_url") or "#",
                        "has_module_perms": True, "models": rest})
    return grouped


admin.site.get_app_list = _grouped_app_list