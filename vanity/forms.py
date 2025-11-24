from django import forms

class VanityForm(forms.Form):
    prefix = forms.CharField(required=False, max_length=20)
    suffix = forms.CharField(required=False, max_length=20)