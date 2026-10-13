from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from . import views


app_name = "portal"


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path(
        "login/",
        LoginView.as_view(
            template_name="portal/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("lookup/<slug:key>/", views.lookup, name="lookup"),
    path("<slug:section>/new/", views.entity_form, name="new"),
    path("<slug:section>/<int:pk>/edit/", views.entity_form, name="edit"),
    path("<slug:section>/<int:pk>/delete/", views.entity_delete, name="delete"),
    path(
        "<slug:section>/<int:pk>/do/<slug:action>/",
        views.entity_action,
        name="action",
    ),
    # Must stay last: matches any single slug and 404s for unknown sections.
    path("<slug:section>/", views.entity_list, name="list"),
]
