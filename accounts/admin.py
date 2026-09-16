from django.contrib import admin
from accounts.models import Role, User

@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "tier")
    list_filter = ("tier",)

admin.site.register(User)