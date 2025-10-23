from django import forms
from django.contrib.auth.forms import UserCreationForm

from core.models import User, Profile, PaymentMethod
from django.conf import settings


class UserWizardForm(UserCreationForm):
    class Meta(UserCreationForm.Meta): # Inherit from UserCreationForm's Meta, which says not to use default forms.CharField for username. Use UsernameField instead.
        model = User
        fields = ('email', 'username')

        # widgets = {
        #     'email': forms.EmailInput(attrs={'placeholder': 'e.g., yourname@example.com', 'class': 'form-control'}),
        #     'username': forms.TextInput(attrs={'placeholder': 'e.g., john_doe', 'class': 'form-control'}),
        #     # Για password/password2, μπορείς να τα ορίσεις κι αυτά αν θες, αλλά η UserCreationForm έχει defaults
        #     'password': forms.PasswordInput(attrs={'placeholder': 'Enter your password', 'class': 'form-control'}),
        #     'password2': forms.PasswordInput(attrs={'placeholder': 'Confirm your password', 'class': 'form-control'})
        # }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
        labels = {
            'profile_picture': 'Profile Picture',
            'birth_date': 'Date of Birth',
            'bio': 'Short Biography',
        }

    # def __init__(self, *args, **kwargs):
    #     super().__init__(*args, **kwargs)
    #     # Ensure file input and any missing widgets carry Bootstrap styling
    #     if 'profile_picture' in self.fields:
    #         css_classes = self.fields['profile_picture'].widget.attrs.get('class', '')
    #         self.fields['profile_picture'].widget.attrs['class'] = (css_classes + ' form-control').strip()