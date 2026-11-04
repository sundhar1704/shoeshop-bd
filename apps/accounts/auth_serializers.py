import re

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

User = get_user_model()

PHONE_RE = re.compile(r"^[6-9]\d{9}$")  # Indian 10-digit mobile


def check_password_strength(value):
    errors = []
    if len(value) < 8:
        errors.append("Password must be at least 8 characters.")
    if not re.search(r"[A-Z]", value):
        errors.append("Add at least one capital letter.")
    if not re.search(r"[a-z]", value):
        errors.append("Add at least one small letter.")
    if not re.search(r"\d", value):
        errors.append("Add at least one number.")
    if errors:
        raise serializers.ValidationError(errors)
    try:
        validate_password(value)  # Django's built-in rules (common passwords etc.)
    except DjangoValidationError as e:
        raise serializers.ValidationError(list(e.messages))
    return value


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="first_name", read_only=True)
    is_manager = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "username", "email", "full_name", "phone", "role", "is_manager")
        read_only_fields = fields

    def get_is_manager(self, obj):
        return bool(obj.is_superuser or obj.role in ("admin", "staff"))


class RegisterSerializer(serializers.Serializer):
    full_name = serializers.CharField(min_length=2, max_length=100)
    email = serializers.EmailField()
    phone = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirm_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_full_name(self, value):
        value = " ".join(value.split())
        if any(ch.isdigit() for ch in value):
            raise serializers.ValidationError("Name cannot contain numbers.")
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("This email is already registered.")
        return value

    def validate_phone(self, value):
        value = re.sub(r"[\s-]", "", value)
        if value.startswith("+91"):
            value = value[3:]
        if not PHONE_RE.match(value):
            raise serializers.ValidationError("Enter a valid 10-digit mobile number.")
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError("This phone number is already registered.")
        return value

    def validate_password(self, value):
        return check_password_strength(value)

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data["email"],
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data["full_name"],
            phone=validated_data["phone"],
            role="customer",  # fixed here, never taken from the request
        )


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()  # email or username
    password = serializers.CharField(trim_whitespace=False)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirm_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_password(self, value):
        return check_password_strength(value)

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs