from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .forms import AdminUserChangeForm, AdminUserCreationForm
from .models import Club, University, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = AdminUserChangeForm
    add_form = AdminUserCreationForm
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "role", "university", "is_active")
    list_filter = ("role", "university", "is_active")
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "university")}),
        ("EUnited role", {
            "fields": ("role", "is_active"),
            "description": "Superadmin = full access. Editor and Moderator = admin panel with "
            "limited rights. Student club = can submit posts for approval.",
        }),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "role", "university", "password1", "password2"),
        }),
    )


@admin.register(University)
class UniversityAdmin(admin.ModelAdmin):
    list_display = ("short_name", "name", "email_domain", "website")


@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = ("name", "university", "verified", "contact_email")
    list_filter = ("verified", "university")
    filter_horizontal = ("members",)
