from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q

UserModel = get_user_model()

class EmailOrUsernameModelBackend(ModelBackend):
    """
    This is a custom authentication backend.

    It allows users to log in using either their username or their email address.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            # Try to find a user matching either the username or the email, case-insensitive.
            user = UserModel.objects.get(Q(username__iexact=username) | Q(email__iexact=username))
        except UserModel.DoesNotExist:
            return None
        except UserModel.MultipleObjectsReturned:
            # This is a rare edge case where two users have the same email as another's username.
            # You should ensure your data is clean. For now, we fail open to the first match.
             user = UserModel.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).order_by('id').first()

        # Check if the password is correct for the user we found.
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        
        return None