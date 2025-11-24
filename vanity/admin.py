from django.contrib import admin
from .models import VanityAddress

@admin.register(VanityAddress)
class VanityAddressAdmin(admin.ModelAdmin):
    list_display = ("address", "private_key", "prefix", "suffix", "created")
    search_fields = ("address", "private_key", "prefix", "suffix")