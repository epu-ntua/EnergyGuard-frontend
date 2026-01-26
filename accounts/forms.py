from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.forms import AuthenticationForm
from django.conf import settings
from django import forms
from accounts.models import User, Profile
from billing.models import PaymentMethod
from .validators import strict_email_user_validator


class UserWizardForm(UserCreationForm):
    class Meta(UserCreationForm.Meta): # Inherit from UserCreationForm's Meta, which says not to use default forms.CharField for username. Use UsernameField instead.
        model = User
        fields = ('email', 'first_name', 'last_name')

        """widgets = {
            'email': forms.EmailInput(attrs={'placeholder': 'e.g., yourname@example.com', 'class': 'form-control'}),
            'username': forms.TextInput(attrs={'placeholder': 'e.g., john_doe', 'class': 'form-control'}),
            'password': forms.PasswordInput(attrs={'placeholder': 'Enter your password', 'class': 'form-control'}),
            'password2': forms.PasswordInput(attrs={'placeholder': 'Confirm your password', 'class': 'form-control'})
        }"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].validators.append(strict_email_user_validator)

        for name in ['first_name', 'last_name', 'email', 'password1', 'password2']:
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
            'company': forms.Select(attrs={'class': 'form-select'}, choices=Profile.CompanyChoices),
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

class CustomAuthenticationForm(AuthenticationForm):
    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['username'].widget.attrs.update(
            {'class': 'form-control', 'placeholder': 'name@example.com'}
        )
        self.fields['password'].widget.attrs.update(
            {'class': 'form-control', 'placeholder': '*********'}
        )


class ProfileForm(forms.Form):
    full_name = forms.CharField(
        max_length=150, 
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'id': 'full_name', 'name': 'full_name'})
    )
    company = forms.CharField(
        max_length=100, 
        required=False, 
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'company', 'name': 'company'}, choices=Profile.CompanyChoices))
    
    position = forms.CharField(
        max_length=100, 
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control', 'id': 'position', 'name': 'position'}))
    
    year_of_birth = forms.ChoiceField(
        required=False,
        choices=[('', 'Select Year')] + [(year, year) for year in range(2020, 1959, -1)], 
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'year', 'name': 'year_of_birth'})
    )

    month_of_birth = forms.ChoiceField(
        required=False,
        choices=[('', 'Select Month')] + [
            (i, ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][i-1]) 
            for i in range(1, 13)
        ],
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'month', 'name': 'month_of_birth'})
    )
    
    day_of_birth = forms.ChoiceField(
        required=False,
        choices=[('', 'Select Day')] + [(i, i) for i in range(1, 32)],
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'day', 'name': 'day_of_birth'})
    )
    short_bio = forms.CharField(
        required=False, 
        widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'id': 'short_bio', 'name': 'short_bio'}))


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ('profile_picture',)
        widgets = {
            'profile_picture': forms.ClearableFileInput(attrs={'class': 'form-control'})
        }