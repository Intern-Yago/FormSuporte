from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard_comercial'),
    path('api/data/', views.api_dashboard_data, name='api_data_comercial'),
    path('export/csv/', views.export_csv, name='export_csv_comercial'),
]
