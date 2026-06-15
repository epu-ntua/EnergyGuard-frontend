from django.core.files.uploadedfile import UploadedFile
from django import forms

from accounts.models import Profile, Team

from datetime import date


class ProfileEditForm(forms.ModelForm):
    first_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'id': 'id_first_name', 'name': 'first_name', 'placeholder': 'First name'})
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'id': 'id_last_name', 'name': 'last_name', 'placeholder': 'Last name'})
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
        choices=[('', 'Select Year')] + [(str(year), str(year)) for year in range(date.today().year, 1940, -1)],
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
        existing_team = self.instance.team if self.instance else None

        if self.user:
            self.fields["first_name"].initial = self.user.first_name
            self.fields["last_name"].initial = self.user.last_name
        self.fields["team"].initial = existing_team.name if existing_team else ""

        if not self.fields["team"].initial:
            self.fields["team"].widget.attrs["placeholder"] = "No team yet - create one to unlock collaboration features"

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


class TeamInviteForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'colleague@example.com',
        })
    )


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ('profile_picture',)
        widgets = {
            'profile_picture': forms.ClearableFileInput(attrs={'class': 'form-control'})
        }
 
    def clean_profile_picture(self):
        file = self.cleaned_data.get("profile_picture")

        # Validate only if a NEW file is uploaded (not when clearing the existing one)
        if isinstance(file, UploadedFile):
            
            max_size = 3 * 1024 * 1024      # 3MB limit
            if file.size > max_size:
                raise forms.ValidationError("Profile picture must be smaller than 3MB.")
            
            allowed_types = [
                "image/jpeg",
                "image/jpg",
                "image/pjpeg",
                "image/png",
                "image/x-png",
                "image/webp",
                "image/avif"
            ]
            content_type = getattr(file, "content_type", None)
            
            if content_type not in allowed_types:
                raise forms.ValidationError("Unsupported file type. Allowed types: JPEG, PNG, WEBP, AVIF.")  
                
        return file