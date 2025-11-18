from django.contrib.auth.forms import UserCreationForm
from django.conf import settings
from django import forms
from core.models import User, Profile, PaymentMethod
from .validators import strict_email_user_validator, strict_username_validator


class UserWizardForm(UserCreationForm):
    class Meta(UserCreationForm.Meta): # Inherit from UserCreationForm's Meta, which says not to use default forms.CharField for username. Use UsernameField instead.
        model = User
        fields = ('email', 'username')

        """widgets = {
            'email': forms.EmailInput(attrs={'placeholder': 'e.g., yourname@example.com', 'class': 'form-control'}),
            'username': forms.TextInput(attrs={'placeholder': 'e.g., john_doe', 'class': 'form-control'}),
            'password': forms.PasswordInput(attrs={'placeholder': 'Enter your password', 'class': 'form-control'}),
            'password2': forms.PasswordInput(attrs={'placeholder': 'Confirm your password', 'class': 'form-control'})
        }"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].validators.append(strict_email_user_validator)
        self.fields['username'].validators.append(strict_username_validator)

        for name in ['username', 'email', 'password1', 'password2']:
            if name in self.fields:
                css_classes = self.fields[name].widget.attrs.get('class', '')
                self.fields[name].widget.attrs['class'] = (css_classes + ' form-control').strip()


class ProfileWizardForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ('profile_picture', 'company', 'position', 'birth_date', 'bio')
        widgets = {
            'birth_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'bio': forms.Textarea(attrs={'rows': 5, 'class': 'form-control'}),
            'company': forms.TextInput(attrs={'class': 'form-control'}),
            'position': forms.TextInput(attrs={'class': 'form-control'}),
            'profile_picture': forms.ClearableFileInput(attrs={'class': 'form-control'})
        }

    """def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'profile_picture' in self.fields:
            css_classes = self.fields['profile_picture'].widget.attrs.get('class', '')
            self.fields['profile_picture'].widget.attrs['class'] = (css_classes + ' form-control').strip()"""
    
class PaymentWizardForm(forms.ModelForm):
    class Meta:
        model = PaymentMethod
        fields = ('card_number', 'cardholder_name', 'expiration_month', 'expiration_year', 'cvv')
        widgets = {
            'card_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'xxxx xxxx xxxx xxxx'}),
            'cardholder_name': forms.TextInput(attrs={'class': 'form-control'}),
            'expiration_month' : forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'MM'}),
            'expiration_year' : forms.TextInput(attrs={'placeholder': 'YY', 'class': 'form-control'}),
            'cvv': forms.TextInput(attrs={'class': 'form-control'})
        }

class AuthenticationForm(forms.Form):
    email_or_username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'name@example.com or username'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '*********'})
    )
    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )