from django.urls import path

from .views import lab_report_print


app_name = "laboratory"


urlpatterns = [
    path(
        "reports/<int:pk>/print/",
        lab_report_print,
        name="lab_report_print",
    ),
]