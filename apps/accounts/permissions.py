from rest_framework.permissions import SAFE_METHODS, BasePermission


def is_manager(user):
    """True for logged-in superusers, admins and staff."""
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role in ("staff", "admin"))
    )


class IsManagerOrReadOnly(BasePermission):
    """Everyone can read (GET). Only managers can add, edit or delete."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return is_manager(request.user)