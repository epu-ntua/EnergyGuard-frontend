from .auth import keycloak_logout, login_view
from .profile import profile, update_profile_picture
from .teams import team_management
from .registration import (
    ENTRY_FORMS,
    PlatformEntryView,
    REGISTRATION_FORMS,
    RegistrationWizard,
    keycloak_registration_success,
    platform_registration_success,
)

__all__ = [
    "ENTRY_FORMS",
    "PlatformEntryView",
    "REGISTRATION_FORMS",
    "RegistrationWizard",
    "keycloak_logout",
    "keycloak_registration_success",
    "login_view",
    "platform_registration_success",
    "profile",
    "update_profile_picture",
]
