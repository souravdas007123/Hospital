from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),

    path(
        "laboratory/",
        include("laboratory.urls"),
    ),

    # Portal (dashboard + list pages) lives at the site root; keep it last
    # because its "<section>/" pattern matches any single path segment.
    path("", include("portal.urls")),
]


if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )