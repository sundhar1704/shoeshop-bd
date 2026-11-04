import ipaddress
import logging
import os

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import IntegrityError
from django.db.models import F, Q
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from .auth_serializers import (
    ForgotPasswordSerializer,
    LoginSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
    UserSerializer,
)
from .models import LoginActivity

User = get_user_model()
logger = logging.getLogger(__name__)


# ---------------- Login history helpers ----------------
def client_ip(request):
    """IP address of the visitor (works behind Render / a proxy too)."""
    raw = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() \
        or request.META.get("REMOTE_ADDR", "")
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def log_activity(request, action, user=None, identifier=""):
    """Saves one row in Login activities. If saving fails, login still works."""
    try:
        LoginActivity.objects.create(
            user=user,
            identifier=(identifier or (user.email if user else ""))[:254],
            action=action,
            ip_address=client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
        )
    except Exception:
        logger.exception("Could not save login activity")


def mark_logged_in(request, user):
    """Updates last login time and login count, then saves a 'login' row."""
    try:
        User.objects.filter(pk=user.pk).update(
            last_login=timezone.now(), login_count=F("login_count") + 1)
    except Exception:
        logger.exception("Could not update login count")
    log_activity(request, LoginActivity.Action.LOGIN, user=user)


# ---------------- Throttles ----------------
class LoginThrottle(AnonRateThrottle):
    scope = "auth_login"
    rate = "100/min" if settings.DEBUG else "5/min"


class RegisterThrottle(AnonRateThrottle):
    scope = "auth_register"
    rate = "100/min" if settings.DEBUG else "5/min"


class ForgotThrottle(AnonRateThrottle):
    scope = "auth_forgot"
    rate = "100/min" if settings.DEBUG else "3/min"


# ---------------- Register / Login / Logout ----------------
class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # public page: an old token must not block it
    throttle_classes = [RegisterThrottle]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        log_activity(request, LoginActivity.Action.REGISTER, user=user)
        return Response(
            {"detail": "Account created. Please log in.", "user": UserSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # public page: an old token must not block it
    throttle_classes = [LoginThrottle]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["username"].strip()
        password = serializer.validated_data["password"]

        found = User.objects.filter(
            Q(email__iexact=identifier) | Q(username__iexact=identifier)
        ).first()
        user = authenticate(request, username=found.username, password=password) if found else None

        if user is None:
            log_activity(request, LoginActivity.Action.LOGIN_FAILED,
                         user=found, identifier=identifier)
            # same message for wrong email, wrong password or inactive user
            return Response(
                {"detail": "Invalid email or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        mark_logged_in(request, user)
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            }
        )


class LogoutView(APIView):
    """POST /api/auth/logout/  body: {"refresh": "<refresh token>"}
    Blocks the refresh token and saves a 'Logout' row in Login activities."""
    permission_classes = [AllowAny]
    authentication_classes = []  # an expired access token must not stop logout

    def post(self, request):
        refresh = request.data.get("refresh", "")
        user = None
        if refresh:
            try:
                token = RefreshToken(refresh)
                user = User.objects.filter(pk=token[api_settings.USER_ID_CLAIM]).first()
                token.blacklist()  # this refresh token can never be used again
            except TokenError:
                pass  # token already used or expired: nothing more to block
        if user:
            log_activity(request, LoginActivity.Action.LOGOUT, user=user)
        return Response({"detail": "Logged out."})


# ---------------- Forgot / Reset password ----------------
class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # public page: an old token must not block it
    throttle_classes = [ForgotThrottle]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user and user.has_usable_password():
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            link = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"
            try:
                send_mail(
                    subject="Reset your StepUp.in password",
                    message=(
                        f"Hi {user.first_name or 'there'},\n\n"
                        f"Click this link to set a new password (valid for 1 hour):\n{link}\n\n"
                        "If you did not ask for this, you can ignore this email."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                )
            except Exception:
                logger.exception("Password reset email failed")

        # same answer for every email, so nobody can check who is registered
        return Response({"detail": "If this email is registered, a reset link has been sent."})


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # public page: an old token must not block it
    throttle_classes = [ForgotThrottle]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            pk = force_str(urlsafe_base64_decode(data["uid"]))
            user = User.objects.get(pk=pk, is_active=True)
        except (ValueError, TypeError, OverflowError, User.DoesNotExist):
            user = None

        if user is None or not default_token_generator.check_token(user, data["token"]):
            return Response(
                {"detail": "This reset link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(data["password"])
        user.save(update_fields=["password"])  # the old link stops working now
        return Response({"detail": "Password changed. Please log in."})


# ---------------- Me ----------------
class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


# ---------------- Google login ----------------
class GoogleLoginView(APIView):
    """Log in (or create a customer account) with a Google account."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginThrottle]

    def post(self, request):
        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        if not client_id:
            return Response(
                {"detail": "Google login is not set up yet."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        credential = request.data.get("credential", "")
        if not credential:
            return Response({"detail": "Google token is missing."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            info = google_id_token.verify_oauth2_token(
                credential, google_requests.Request(), client_id
            )
        except ValueError:
            return Response(
                {"detail": "Google sign-in failed. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = (info.get("email") or "").strip().lower()
        if not email or not info.get("email_verified"):
            return Response(
                {"detail": "Your Google email is not verified."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(email__iexact=email).first()
        created = False
        if user is None:
            try:
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    first_name=(info.get("name") or "").strip()[:100],
                    role="customer",
                )
                created = True
            except IntegrityError:
                return Response(
                    {"detail": "Could not create your account. Please use the Register form."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # staff and admin must use email + password
        if not user.is_active or user.role != "customer":
            return Response(
                {"detail": "Please log in with your email and password."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if created:
            log_activity(request, LoginActivity.Action.REGISTER, user=user)
        mark_logged_in(request, user)
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            }
        )