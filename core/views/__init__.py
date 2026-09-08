from .ai_models import ai_models, deeptsf_detail, request_ai_model_access, tirex_detail
from .dashboard import dashboard
from .hpc import hpc
from .public import (
    collaboration_hub,
    contact_form,
    documentation,
    error_does_not_exist,
    home,
)
from .wizard import BaseWizardView

__all__ = [
    "ai_models",
    "deeptsf_detail",
    "request_ai_model_access",
    "tirex_detail",
    "BaseWizardView",
    "collaboration_hub",
    "contact_form",
    "dashboard",
    "documentation",
    "error_does_not_exist",
    "home",
    "hpc",
]
