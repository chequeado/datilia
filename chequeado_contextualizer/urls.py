from pathlib import Path
from django.urls import path, include
from django.http import HttpResponse
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin


def sandbox(request):
    html = (settings.BASE_DIR / "static" / "sandbox.html").read_text()
    return HttpResponse(html, content_type="text/html")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", sandbox, name="sandbox"),
    path("", include("api.urls")),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
