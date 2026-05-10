import requests
from django.conf import settings
from allauth.socialaccount.models import SocialAccount
import logging

logger = logging.getLogger(__name__)

class KeycloakUserSyncClient:
    def __init__(self):
        try:
            config = settings.KEYCLOAK_USER_SYNC_CONFIG
            self.base_url = config['SERVER_URL']
            self.realm = config['REALM']
            self.client_id = config['CLIENT_ID']
            self.client_secret = config['CLIENT_SECRET']
            self.token = self._get_service_account_token()
        except (AttributeError, KeyError) as e:
            logger.error(f"Keycloak user sync client is not configured properly in settings.py: {e}")
            self.token = None


    def _get_service_account_token(self):
        token_url = f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }
        try:
            response = requests.post(token_url, data=payload)
            response.raise_for_status()  # Raise an exception for bad status codes
            return response.json().get("access_token")
        except requests.exceptions.RequestException as e:
            status = e.response.status_code if e.response is not None else "N/A"
            logger.error(f"Error getting Keycloak service account token: {type(e).__name__} (status={status})")
            return None

    def update_user(self, user, user_data):
        if not self.token:
            logger.error("Cannot update Keycloak user: user sync client is not authenticated.")
            return {"error": "Authentication failed. Cannot get service account token."}

        try:
            social_account = SocialAccount.objects.get(user=user, provider='keycloak')
            keycloak_user_id = social_account.uid
        except SocialAccount.DoesNotExist:
            logger.warning(f"Cannot update Keycloak user {user.id}: SocialAccount for Keycloak not found.")
            return {"error": "User's SocialAccount for Keycloak not found."}

        user_url = f"{self.base_url}/admin/realms/{self.realm}/users/{keycloak_user_id}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        # Keycloak expects specific field names
        payload = {
            "firstName": user_data.get('first_name'),
            "lastName": user_data.get('last_name'),
        }

        # Remove keys with None values so we don't accidentally clear fields in Keycloak
        payload = {k: v for k, v in payload.items() if v is not None}

        if not payload:
            return {"success": True, "message": "No data to update."} # Nothing to do

        try:
            response = requests.put(user_url, headers=headers, json=payload)
            response.raise_for_status()
            logger.info(f"Successfully updated user {user.id} in Keycloak.")
            return {"success": True}
        except requests.exceptions.RequestException as e:
            status = e.response.status_code if e.response is not None else "No response"
            logger.error(f"Error updating user {user.id} in Keycloak: {type(e).__name__} (status={status})")
            return {"error": f"Failed to update user in Keycloak: {e}"}

    def send_reset_password_email(self, user):
        """Send a password reset email to the user via Keycloak's execute-actions-email endpoint."""
        if not self.token:
            logger.error("Cannot send reset password email: user sync client is not authenticated.")
            return {"error": "Authentication failed. Cannot get service account token."}

        try:
            social_account = SocialAccount.objects.get(user=user, provider='keycloak')
            keycloak_user_id = social_account.uid
        except SocialAccount.DoesNotExist:
            logger.warning(f"Cannot send reset password email for user {user.id}: SocialAccount for Keycloak not found.")
            return {"error": "User's SocialAccount for Keycloak not found."}

        url = f"{self.base_url}/admin/realms/{self.realm}/users/{keycloak_user_id}/execute-actions-email"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        try:
            # HTTP PUT request at Keycloak Admin API  
            response = requests.put(url, headers=headers, json=["UPDATE_PASSWORD"])  # UPDATE_PASSWORD = Keycloak alias
            response.raise_for_status()
            logger.info(f"Successfully sent reset password email to user {user.id}.")
            return {"success": True}
        except requests.exceptions.RequestException as e:
            status = e.response.status_code if e.response is not None else "No response"
            logger.error(f"Error sending reset password email for user {user.id}: {type(e).__name__} (status={status})")
            return {"error": f"Failed to send reset password email: {e}"}
