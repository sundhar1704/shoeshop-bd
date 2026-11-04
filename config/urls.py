from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.products.views import AboutPageView, ContactPageView, EnquiryCreateView
from apps.cart.views import CartView, CartCountView, CartItemAddView, CartItemDetailView
from apps.orders.views import (CheckoutSummaryView, CheckoutView, MyOrdersView, MyOrderDetailView,
                               OrderThanksView, OrderTrackView, OrderCancelView, OrderViewDetailsView)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.accounts.auth_urls")),  # register, login, forgot password
    path("api/about/", AboutPageView.as_view()),
    path("api/contact/", ContactPageView.as_view()),
    path("api/enquiry/", EnquiryCreateView.as_view()),
    path("api/cart/", CartView.as_view()),
    path("api/cart/count/", CartCountView.as_view()),
    path("api/cart/items/", CartItemAddView.as_view()),
    path("api/cart/items/<int:pk>/", CartItemDetailView.as_view()),
    path("api/orders/summary/", CheckoutSummaryView.as_view()),
    path("api/orders/checkout/", CheckoutView.as_view()),
    path("api/orders/", MyOrdersView.as_view()),
    path("api/orders/<str:order_number>/thanks/", OrderThanksView.as_view()),
    path("api/orders/<str:order_number>/track/", OrderTrackView.as_view()),
    path("api/orders/<str:order_number>/cancel/", OrderCancelView.as_view()),
    path("api/orders/<str:order_number>/view/", OrderViewDetailsView.as_view()),  # NEW: View Order page
    path("api/orders/<str:order_number>/", MyOrderDetailView.as_view()),
    path("api/", include("apps.products.urls")),            # products, categories, banners, etc.
]

# show uploaded images (media folder) while developing
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)