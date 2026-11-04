from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (CategoryViewSet, ProductViewSet, ProductImageViewSet,
                    ProductVariantViewSet, BannerViewSet, HomeContentView, SubscribeView,
                    ShopProductListView, ShopProductDetailView, MenuView, FiltersView)

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("products", ProductViewSet, basename="product")
router.register("product-images", ProductImageViewSet, basename="product-image")
router.register("product-variants", ProductVariantViewSet, basename="product-variant")
router.register("banners", BannerViewSet, basename="banner")

urlpatterns = [
    path("home-content/", HomeContentView.as_view()),
    path("subscribe/", SubscribeView.as_view()),
    path("shop/products/", ShopProductListView.as_view()),
    path("shop/products/<slug:slug>/", ShopProductDetailView.as_view()),  # NEW
    path("menu/", MenuView.as_view()),
    path("filters/", FiltersView.as_view()),
] + router.urls