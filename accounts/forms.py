from datetime import date

from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.forms import AuthenticationForm
from django import forms
from accounts.models import User, Profile, Team
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
        fields = ('profile_picture', 'team', 'position', 'birth_date', 'bio')
        widgets = {
            'birth_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'bio': forms.Textarea(attrs={'rows': 5, 'class': 'form-control'}),
            'team': forms.Select(attrs={'class': 'form-control'}),
            'position': forms.TextInput(attrs={'class': 'form-control'}),
            'profile_picture': forms.ClearableFileInput(attrs={'class': 'form-control'})
        }

    # def __init__(self, *args, **kwargs):
    #     super().__init__(*args, **kwargs)
    #     self.fields['team'].queryset = Team.objects.order_by("name")
    #     self.fields['team'].empty_label = 'Select Team'
    #     if 'profile_picture' in self.fields:
    #         css_classes = self.fields['profile_picture'].widget.attrs.get('class', '')
    #         self.fields['profile_picture'].widget.attrs['class'] = (css_classes + ' form-control').strip()
    
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


class ProfileEditForm(forms.ModelForm):
    full_name = forms.CharField(
        max_length=150, 
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'id': 'full_name', 'name': 'full_name'})
    )
    team = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "id": "team",
                "name": "team",
                "readonly": "readonly",
            }
        ),
    )

    year_of_birth = forms.ChoiceField(
        required=False,
        choices=[('', 'Select Year')] + [(str(year), str(year)) for year in range(date.today().year, 1959, -1)],
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
        choices=[('', 'Select Day')] + [(str(i), str(i)) for i in range(1, 32)],
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'day', 'name': 'day_of_birth'})
    )

    class Meta:
        model = Profile
        fields = ("position", "bio")
        widgets = {
            "position": forms.TextInput(attrs={"class": "form-control", "id": "position", "name": "position"}),
            "bio": forms.Textarea(attrs={"rows": 2, "class": "form-control", "id": "short_bio", "name": "short_bio"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        effective_team = self.instance.team
        if not effective_team and self.user:
            effective_team = getattr(self.user, "created_team", None)

        if self.user:
            self.fields["full_name"].initial = f"{self.user.first_name} {self.user.last_name}".strip()
        self.fields["team"].initial = effective_team.name if effective_team else ""

        if not self.fields["team"].initial:
            self.fields["team"].widget.attrs["placeholder"] = "No team yet - create one from Team Management"

        if self.instance.birth_date:
            self.fields["year_of_birth"].initial = str(self.instance.birth_date.year)
            self.fields["month_of_birth"].initial = str(self.instance.birth_date.month)
            self.fields["day_of_birth"].initial = str(self.instance.birth_date.day)

    def clean(self):
        cleaned_data = super().clean()
        year_of_birth = cleaned_data.get("year_of_birth")
        month_of_birth = cleaned_data.get("month_of_birth")
        day_of_birth = cleaned_data.get("day_of_birth")

        date_parts = [year_of_birth, month_of_birth, day_of_birth]
        if not any(date_parts):
            cleaned_data["resolved_birth_date"] = None
            return cleaned_data

        if not all(date_parts):
            self.add_error("year_of_birth", "Please select day, month and year for date of birth.")
            return cleaned_data

        try:
            cleaned_data["resolved_birth_date"] = date(
                int(year_of_birth),
                int(month_of_birth),
                int(day_of_birth),
            )
        except (ValueError, TypeError):
            self.add_error("year_of_birth", "Please provide a valid date of birth.")

        return cleaned_data

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.birth_date = self.cleaned_data.get("resolved_birth_date")
        if commit:
            if profile.pk:
                profile.save(update_fields=["position", "bio", "birth_date"])
            else:
                profile.save()
        return profile


class TeamCreateForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ("name", "description")
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. ICCS-NTUA",
                    "maxlength": 100,
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Describe your team",
                }
            ),
        }


class TeamEditForm(TeamCreateForm):
    pass


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ('profile_picture',)
        widgets = {
            'profile_picture': forms.ClearableFileInput(attrs={'class': 'form-control'})
        }
