from django.urls import path
from .views import index  # ou SimuladorIndexView.as_view()

urlpatterns = [
    path('', index, name='simulador_index'),
]