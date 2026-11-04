from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        STAFF = "staff", "Staff"
        ADMIN = "admin", "Admin"

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15, blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CUSTOMER)
    login_count = models.PositiveIntegerField(default=0)  # how many times this user logged in

    def __str__(self):
        return self.username


class LoginActivity(models.Model):
    """One row for every register / login / failed login / logout event."""

    class Action(models.TextChoices):
        REGISTER = "register", "Register"
        LOGIN = "login", "Login"
        LOGIN_FAILED = "login_failed", "Login failed"
        LOGOUT = "logout", "Logout"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="activities",  # history stays if user is deleted
    )
    identifier = models.CharField(max_length=254, blank=True)  # email typed (useful for failed logins)
    action = models.CharField(max_length=15, choices=Action.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)  # browser / device
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Login activities"

    def __str__(self):
        return f"{self.identifier or self.user_id} - {self.action}"