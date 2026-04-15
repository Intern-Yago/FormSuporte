from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard_kpis, name="dashboard_suporte"),
    path("entrada/", views.entrada_kpis, name="entrada"),
    path("equipamentos/", views.dashboard_equipamentos, name="equipamentos"),

    path("api/technicians/", views.api_technicians_list, name="api_technicians_list"),
    path("api/technicians/add/", views.api_technicians_add, name="api_technicians_add"),
    path(
        "api/technicians/<int:tecnico_id>/toggle-active/",
        views.api_technicians_toggle_active,
        name="api_technicians_toggle_active",
    ),

    path("api/records/month/", views.api_records_by_month, name="api_records_by_month"),
    path("api/records/upsert/", views.api_records_upsert, name="api_records_upsert"),
    path("api/records/<int:record_id>/delete/", views.api_records_delete, name="api_records_delete"),

    path("api/kpi/summary/", views.api_kpi_summary, name="api_kpi_summary"),
    path("api/kpi/summary-by-year/", views.api_kpi_summary_by_year, name="api_kpi_summary_by_year"),
    path("api/kpi/summary-range/", views.api_kpi_summary_range, name="api_kpi_summary_range"),
    
    path("api/kpi/time-series/", views.api_kpi_time_series, name="api_kpi_time_series"),
    path("api/kpi/all-time-series/", views.api_kpi_all_time_series, name="api_kpi_all_time_series"),

    path("api/equipamentos/summary/", views.api_equipamentos_summary, name="api_equipamentos_summary"),
]