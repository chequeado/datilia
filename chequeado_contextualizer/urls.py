from pathlib import Path
from django.urls import path, include
from django.http import HttpResponse
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin


def _serve(filename):
    def view(request, **kwargs):
        html = (settings.BASE_DIR / "static" / filename).read_text()
        return HttpResponse(html, content_type="text/html")
    return view


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", _serve("contextualize-text.html"), name="home"),
    path("history", _serve("history.html"), name="history"),
    path("run/<uuid:trace_id>", _serve("run.html"), name="run-detail-page"),
    path("", include("api.urls")),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
