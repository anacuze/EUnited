from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "EUnited admin"
admin.site.site_title = "EUnited admin"
admin.site.index_title = "Pulse management"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("", include("pulse.urls")),
]
