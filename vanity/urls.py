from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("generate/", views.generate_address, name="generate_address"),
    path("stop/", views.stop_generation_view, name="stop_generation"),
]