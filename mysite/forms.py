from django import forms
from django.contrib.auth.forms import UserCreationForm

from core.models import User, Profile, PaymentMethod
from django.conf import settings


class UserWizardForm(UserCreationForm):
    class Meta(UserCreationForm.Meta): # Inherit from UserCreationForm's Meta, which says not to use default forms.CharField for username. Use UsernameField instead.
        model = User
        fields = ('email', 'username')

class ProfileWizardForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ('profile_picture', 'company', 'position', 'birth_date', 'bio')
        widgets = {
            'birth_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'bio': forms.Textarea(attrs={'rows': 5, 'class': 'form-control'}),
            'company': forms.TextInput(attrs={'class': 'form-control'}),
            'position': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'profile_picture': 'Profile Picture',
            'birth_date': 'Date of Birth',
            'bio': 'Short Biography',
        }

    