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
    # Must stay last: matches any single slug and 404s for unknown sections.
    path("<slug:section>/", views.section_list, name="list"),
]
