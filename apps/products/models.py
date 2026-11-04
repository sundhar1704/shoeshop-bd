import re
from decimal import Decimal
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils.text import slugify
from .validators import validate_image


# ---------------- NEW: filter and menu tables (all editable in admin) ----------------

class Style(models.Model):  # NEW
    """One column of a category menu, for example Sandals under Kids."""
    category = models.ForeignKey("categories.Category", on_delete=models.CASCADE, related_name="styles")
    name = models.CharField(max_length=100, help_text="For example Sandals, Trainers, Boots.")
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "order", "id"]
        unique_together = ("category", "name")

    def __str__(self):
        return f"{self.category.name} - {self.name}"


class SubStyle(models.Model):  # NEW
    """Small item under a style, for example Flat or Flip Flop under Sandals."""
    style = models.ForeignKey(Style, on_delete=models.CASCADE, related_name="substyles")
    name = models.CharField(max_length=100, help_text="For example Flat, Flip Flop, View all.")
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["style", "order", "id"]
        unique_together = ("style", "name")

    def __str__(self):
        return f"{self.style.name} - {self.name}"


class Brand(models.Model):  # NEW
    """Brand shown in the Brands menu (grouped A-Z automatically) and in the Brands filter."""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Color(models.Model):  # NEW
    """Colour swatch in the Color filter and on product cards."""
    name = models.CharField(max_length=30, unique=True, help_text="For example Black, Blue.")
    hex_code = models.CharField(
        max_length=7, default="#000000",
        validators=[RegexValidator(r"^#[0-9A-Fa-f]{6}$", "Use a colour like #FFA0A0.")],
        help_text="Colour code like #FFA0A0.",
    )
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class SizeOption(models.Model):  # NEW
    """Entries of the Size filter, for example group Junior -> UK(3)."""
    group = models.CharField(max_length=30, help_text="For example Junior or Adult.")
    label = models.CharField(max_length=20, help_text="For example UK(3). Must match the size typed in the product variants.")
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]
        unique_together = ("group", "label")

    def __str__(self):
        return f"{self.group} - {self.label}"


class OfferLink(models.Model):  # NEW
    """Lines in the Offers menu."""
    title = models.CharField(max_length=100)
    link = models.CharField(max_length=200, default="/products", blank=True)
    is_heading = models.BooleanField(default=False, help_text="Tick for a plain heading with no link (like SAVE).")
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title


# ---------------- OLD tables (unchanged) + NEW fields on Product ----------------

class Product(models.Model):
    category = models.ForeignKey("categories.Category", on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, blank=True)
    brand = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_percent = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # NEW fields for the Products listing page
    brand_link = models.ForeignKey(
        Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name="products",
        help_text="Choose the brand. The old Brand text above is filled automatically.",
    )
    style = models.ForeignKey(Style, on_delete=models.SET_NULL, null=True, blank=True, related_name="products")
    substyle = models.ForeignKey(SubStyle, on_delete=models.SET_NULL, null=True, blank=True, related_name="products")
    colors = models.ManyToManyField(Color, blank=True, related_name="products")
    is_multicolor = models.BooleanField(default=False, help_text="Tick to show the text 'Multi-color' instead of colour dots.")
    rating = models.DecimalField(
        max_digits=2, decimal_places=1, default=Decimal("0.0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("5"))],
        help_text="0 to 5, one decimal (for example 4.5).",
    )

    class Meta:
        ordering = ["-created_at"]

    @property
    def final_price(self):
        return (self.price * (100 - self.discount_percent) / Decimal(100)).quantize(Decimal("0.01"))

    def save(self, *args, **kwargs):
        if self.brand_link_id:  # NEW: keep the old brand text in sync
            self.brand = self.brand_link.name
        if not self.slug:
            base = slugify(self.name)
            slug, n = base, 1
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                n += 1
                slug = f"{base}-{n}"
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(
        upload_to="products/",
        validators=[validate_image],  # NEW
        help_text="Recommended 1000 x 1050 px (min 600 x 600, max 3 MB). Auto-cropped to the card frame.",  # NEW
    )
    is_main = models.BooleanField(default=False)


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    size = models.CharField(max_length=10)
    color = models.CharField(max_length=30, blank=True)
    stock = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("product", "size", "color")


class Banner(models.Model):
    POSITIONS = [("left", "Left"), ("right", "Right")]

    title = models.CharField(max_length=200)
    image = models.ImageField(upload_to="banners/")
    button_text = models.CharField(max_length=40, default="Shop Now")
    link = models.CharField(max_length=200, default="/products")
    text_box = models.BooleanField(default=False, help_text="Dark rounded box behind the text")
    text_position = models.CharField(
        max_length=5, choices=POSITIONS, default="right",
        help_text="Which side the text and the button sit on this slide.")
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title

class HomeContent(models.Model):
    overview_text = models.TextField(default="Explore our curated selection of high-quality shoes for every occasion. From durable athletic shoes designed for peak performance to stylish casual sneakers and elegant dress shoes, we offer a diverse range of footwear to suit your needs. Our user-friendly interface makes it easy to browse our collection and find the perfect pair, while detailed product descriptions and high-quality images ensure you make an informed decision. Join our community of style and discover your next favorite shoe!")
    offer_text_1 = models.CharField(max_length=120, default="Get your first order with free gift")
    offer_text_2 = models.CharField(max_length=60, default="& 50 % offer")
    landline = models.CharField(max_length=30, default="XXXXXXXXXX", blank=True)
    whatsapp = models.CharField(max_length=30, default="+91XXXXXXXXXX", blank=True)
    email = models.CharField(max_length=100, default="stepup@gmail.com", blank=True)
    address = models.TextField(default="2/38, yyyyyyyyyyy, Tenkasi, Tamilnadu, India.", blank=True)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]


class Subscriber(models.Model):
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email


class AboutPage(models.Model):
    about_title = models.CharField(max_length=100, default="About StepUp")
    about_text = models.TextField()
    mission_title = models.CharField(max_length=100, default="Our Mission")
    mission_text = models.TextField()
    side_image = models.ImageField(
        upload_to="about/", blank=True, null=True,
        validators=[validate_image],
        help_text="Square image. Recommended 1000 x 1000 px (min 600 x 600, max 3 MB). Shown in a circle and auto-cropped.",
    )
    center_image = models.ImageField(
        upload_to="about/", blank=True, null=True,
        validators=[validate_image],
        help_text="Square image. Recommended 800 x 800 px (min 600 x 600, max 3 MB). Shown in a circle and auto-cropped.",
    )

    def save(self, *args, **kwargs):
        self.pk = 1  # only one row allowed
        super().save(*args, **kwargs)

    def __str__(self):
        return "About page"

    class Meta:
        verbose_name_plural = "About page"


class AboutFeature(models.Model):
    title = models.CharField(max_length=100)
    text = models.TextField()
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title


class ContactPage(models.Model):
    title = models.CharField(max_length=100, default="Contact Us")
    section_title = models.CharField(max_length=100, default="For Online Orders")
    inquiry_label = models.CharField(max_length=100, default="Inquiry / Complaint")
    inquiry_phone = models.CharField(max_length=20)
    other_label = models.CharField(max_length=100, default="Any other queries")
    other_phone_1 = models.CharField(max_length=20)
    other_phone_2 = models.CharField(max_length=20, blank=True)
    working_hours = models.CharField(max_length=50, default="10 AM - 7.00 PM")
    email = models.EmailField()
    image = models.ImageField(
        upload_to="contact/", blank=True, null=True,
        validators=[validate_image],
        help_text="Landscape 16:9 image. Recommended 1600 x 900 px (min 600 px on each side, max 3 MB). Auto-cropped to fit.",
    )
    enquiry_title = models.CharField(max_length=100, default="Enquiry Form")

    def save(self, *args, **kwargs):
        self.pk = 1  # only one row allowed
        super().save(*args, **kwargs)

    def __str__(self):
        return "Contact page"

    class Meta:
        verbose_name_plural = "Contact page"


class Enquiry(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    message = models.TextField(max_length=1000)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Enquiries"

    def __str__(self):
        return f"{self.name} - {self.email}"