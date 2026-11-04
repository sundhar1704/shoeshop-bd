from django.conf import settings
from rest_framework import viewsets, filters, generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView
from apps.accounts.permissions import IsManagerOrReadOnly, is_manager
from apps.categories.models import Category
from .models import (Product, ProductImage, ProductVariant, Banner, HomeContent,
                     AboutPage, ContactPage)
from .serializers import (CategorySerializer, ProductSerializer, ProductImageSerializer,
                          ProductVariantSerializer, BannerSerializer,
                          HomeContentSerializer, SubscriberSerializer,
                          AboutPageSerializer, ContactPageSerializer, EnquirySerializer)
def public_only(request):
    # customers always see active items; the website sends ?public=true so admins see the same
    return not is_manager(request.user) or request.query_params.get("public") == "true"


class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    permission_classes = [IsManagerOrReadOnly]
    pagination_class = None

    def get_queryset(self):
        qs = Category.objects.all().order_by("id")
        return qs.filter(is_active=True) if public_only(self.request) else qs


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = [IsManagerOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "brand", "description"]
    ordering_fields = ["price", "created_at", "name"]
    ordering = ["id"]

    def get_queryset(self):
        qs = Product.objects.select_related("category").prefetch_related("images", "variants")
        if public_only(self.request):
            qs = qs.filter(is_active=True)
        p = self.request.query_params
        if p.get("category"):
            qs = qs.filter(category__slug=p["category"])
        if p.get("brand"):
            qs = qs.filter(brand__iexact=p["brand"])
        if p.get("featured") == "true":
            qs = qs.filter(is_featured=True)
        if p.get("min_price"):
            qs = qs.filter(price__gte=p["min_price"])
        if p.get("max_price"):
            qs = qs.filter(price__lte=p["max_price"])
        if p.get("size"):
            qs = qs.filter(variants__size=p["size"]).distinct()
        return qs


class ProductImageViewSet(viewsets.ModelViewSet):
    queryset = ProductImage.objects.all()
    serializer_class = ProductImageSerializer
    permission_classes = [IsManagerOrReadOnly]


class ProductVariantViewSet(viewsets.ModelViewSet):
    queryset = ProductVariant.objects.all()
    serializer_class = ProductVariantSerializer
    permission_classes = [IsManagerOrReadOnly]


class BannerViewSet(viewsets.ModelViewSet):
    serializer_class = BannerSerializer
    permission_classes = [IsManagerOrReadOnly]
    pagination_class = None

    def get_queryset(self):
        qs = Banner.objects.all()
        return qs.filter(is_active=True) if public_only(self.request) else qs


class HomeContentView(APIView):
    permission_classes = [IsManagerOrReadOnly]

    def get(self, request):
        return Response(HomeContentSerializer(HomeContent.load()).data)

    def patch(self, request):
        s = HomeContentSerializer(HomeContent.load(), data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)


class SubscribeView(generics.CreateAPIView):
    serializer_class = SubscriberSerializer
    permission_classes = [permissions.AllowAny]

class EnquiryThrottle(SimpleRateThrottle):
    """Limits the enquiry form: 5 per hour per visitor when live."""
    scope = "enquiry"

    def get_rate(self):
        return "1000/hour" if settings.DEBUG else "5/hour"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class AboutPageView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        page = AboutPage.objects.first()
        if page is None:
            return Response({"detail": "About page is not added yet."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(AboutPageSerializer(page, context={"request": request}).data)


class ContactPageView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        page = ContactPage.objects.first()
        if page is None:
            return Response({"detail": "Contact page is not added yet."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(ContactPageSerializer(page, context={"request": request}).data)


class EnquiryCreateView(generics.CreateAPIView):
    serializer_class = EnquirySerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []  # public form: an old login token must not block it
    throttle_classes = [EnquiryThrottle]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"message": "Thank you! We will contact you soon."},
                        status=status.HTTP_201_CREATED)


# ---------------- NEW: Products listing page, menu and filters ----------------
from django.db.models import Prefetch  # NEW
from .models import Style, SubStyle, Brand, Color, SizeOption, OfferLink  # NEW
from .serializers import ShopProductSerializer, ColorMiniSerializer  # NEW


def _values(params, key):
    """Accepts ?key=a&key=b or ?key=a,b and returns ['a', 'b']."""
    out = []
    for raw in params.getlist(key):
        out += [v.strip() for v in raw.split(",") if v.strip()]
    return out


class ShopProductListView(generics.ListAPIView):
    serializer_class = ShopProductSerializer
    permission_classes = [permissions.AllowAny]

    SORTS = {
        "featured": ["-is_featured", "-created_at"],
        "new": ["-created_at"],
        "price_asc": ["price"],
        "price_desc": ["-price"],
        "rating": ["-rating", "-created_at"],
    }

    def get_queryset(self):
        p = self.request.query_params
        qs = (Product.objects.filter(is_active=True)
              .select_related("category", "brand_link")
              .prefetch_related("images", "colors"))
        if p.get("category"):
            qs = qs.filter(category__slug=p["category"])
        styles = [v for v in _values(p, "style") if v.isdigit()]
        if styles:
            qs = qs.filter(style_id__in=styles)
        substyles = [v for v in _values(p, "substyle") if v.isdigit()]
        if substyles:
            qs = qs.filter(substyle_id__in=substyles)
        brands = _values(p, "brand")
        if brands:
            qs = qs.filter(brand_link__slug__in=brands)
        colors = _values(p, "color")
        if colors:
            qs = qs.filter(colors__name__in=colors)
        sizes = _values(p, "size")
        if sizes:
            qs = qs.filter(variants__size__in=sizes)
        if p.get("q"):
            qs = qs.filter(name__icontains=p["q"].strip())
        order = self.SORTS.get(p.get("sort"), self.SORTS["featured"])
        return qs.distinct().order_by(*order, "-id")


class MenuView(APIView):
    """Mega menus (category -> styles -> sub styles), brands A-Z, offers."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        substyles = Prefetch("substyles", queryset=SubStyle.objects.filter(is_active=True))
        styles = Prefetch("styles", queryset=Style.objects.filter(is_active=True).prefetch_related(substyles))
        categories = Category.objects.filter(is_active=True).order_by("id").prefetch_related(styles)

        cats = [{
            "id": c.id, "name": c.name, "slug": c.slug,
            "styles": [{
                "id": s.id, "name": s.name,
                "substyles": [{"id": ss.id, "name": ss.name} for ss in s.substyles.all()],
            } for s in c.styles.all()],
        } for c in categories]

        groups = {}
        for b in sorted(Brand.objects.filter(is_active=True), key=lambda b: b.name.lower()):
            groups.setdefault(b.name[0].upper(), []).append({"id": b.id, "name": b.name, "slug": b.slug})
        brands = [{"letter": k, "brands": v} for k, v in sorted(groups.items())]

        offers = [{"id": o.id, "title": o.title, "link": o.link, "is_heading": o.is_heading}
                  for o in OfferLink.objects.filter(is_active=True)]
        return Response({"categories": cats, "brands": brands, "offers": offers})


class FiltersView(APIView):
    """Options for the Style, Size, Brands and Color dropdowns."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        styles = Style.objects.filter(is_active=True)
        if request.query_params.get("category"):
            styles = styles.filter(category__slug=request.query_params["category"])

        size_groups = {}
        for s in SizeOption.objects.filter(is_active=True):
            size_groups.setdefault(s.group, []).append(s.label)

        return Response({
            "styles": [{"id": s.id, "name": s.name} for s in styles],
            "sizes": [{"group": g, "labels": labels} for g, labels in size_groups.items()],
            "brands": [{"id": b.id, "name": b.name, "slug": b.slug}
                       for b in Brand.objects.filter(is_active=True)],
            "colors": ColorMiniSerializer(Color.objects.filter(is_active=True), many=True).data,
            "sort_options": [
                {"key": "featured", "label": "Featured"},
                {"key": "new", "label": "New Arrivals"},
                {"key": "price_asc", "label": "Price:Low-High"},
                {"key": "price_desc", "label": "Price:High-Low"},
                {"key": "rating", "label": "Overall Rating"},
            ],
        })

# ---------------- NEW: Product details API ----------------
class ShopProductDetailView(APIView):
    """One product with images, colours, sizes and stock."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, slug):
        # Try finding by exact slug first, then fallback to matching ID if slug has a suffix
        p = Product.objects.filter(is_active=True, slug=slug).first()
        if not p:
            # Try matching slug without trailing numbers or grab first active product matching similar text
            base_slug = slug.rsplit("-", 1)[0]
            p = Product.objects.filter(is_active=True, slug__startswith=base_slug).first()
        
        if not p:
            return Response({"detail": "Product not found."}, status=status.HTTP_404_NOT_FOUND)

        p = (
            Product.objects.filter(pk=p.pk)
            .select_related("category", "brand_link")
            .prefetch_related("images", "colors", "variants")
            .first()
        )

        images = sorted(p.images.all(), key=lambda i: (not i.is_main, i.id))
        return Response({
            "id": p.id,
            "name": p.name,
            "slug": p.slug,
            "brand_name": p.brand_link.name if p.brand_link else (p.brand or ""),
            "description": p.description,
            "price": p.price,
            "discount_percent": p.discount_percent,
            "final_price": p.final_price,
            "rating": p.rating,
            "is_multicolor": p.is_multicolor,
            "category_slug": p.category.slug if p.category else "",
            "images": [request.build_absolute_uri(i.image.url) for i in images if i.image],
            "colors": [{"id": c.id, "name": c.name, "hex": c.hex_code} for c in p.colors.all()],
            "sizes": [{"id": v.id, "size": v.size, "color": v.color or "",
            "stock": v.stock}
                      for v in p.variants.all()],
        })