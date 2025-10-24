from django.core.validators import RegexValidator

strict_email_user_validator = RegexValidator(
    r'^[a-zA-Z0-9_.-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
    'Enter a valid email user. Only letters, numbers, and . - _ are allowed before the @ symbol.'
)

strict_username_validator = RegexValidator(
    r'^[a-zA-Z0-9_.-]+$',
    'Username can only contain letters, numbers, and . - _ characters.'
)