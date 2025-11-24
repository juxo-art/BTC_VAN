from django.db import models

class VanityAddress(models.Model):
    #objects = None
    #objects = models.Manager()
    address = models.CharField(max_length=120)
    private_key = models.CharField(max_length=200)
    prefix = models.CharField(max_length=20, blank=True)
    suffix = models.CharField(max_length=20, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    def _str_(self):
        return self.address