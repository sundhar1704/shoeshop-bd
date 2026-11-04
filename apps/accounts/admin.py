from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, LoginActivity


class LoginActivityInline(admin.TabularInline):
    """Shows this user's register / login / logout history on the user page."""
    model = LoginActivity
    extra = 0
    can_delete = False
    ordering = ("-created_at",)
    fields = ("created_at", "action", "identifier", "ip_address", "user_agent")
    readonly_fields = ("created_at", "action", "identifier", "ip_address", "user_agent")
    verbose_name_plural = "Login activities (this user)"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Shop info", {"fields": ("phone", "role", "login_count")}),)
    list_display = ("username", "email", "phone", "role", "login_count",
                    "date_joined", "last_login", "is_staff")
    readonly_fields = ("login_count",)  # only the system changes this number
    ordering = ("-date_joined",)  # newest customers first
    inlines = [LoginActivityInline]


@admin.register(LoginActivity)
class LoginActivityAdmin(admin.ModelAdmin):
    list_display = ("created_at", "identifier", "action", "ip_address", "user")
    list_filter = ("action", "created_at")
    search_fields = ("identifier", "ip_address", "user__email")
    readonly_fields = ("user", "identifier", "action", "ip_address", "user_agent", "created_at")

    # history is a record: nobody can add, edit or delete it from the admin
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False