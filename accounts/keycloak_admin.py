import requests
from django.conf import settings
from allauth.socialaccount.models import SocialAccount
import logging

logger = logging.getLogger(__name__)

class KeycloakAdminClient:
    def __init__(self):
        try:
            config = settings.KEYCLOAK_ADMIN_CONFIG
            self.base_url = config['SERVER_URL']
            self.realm = config['REALM']
            self.client_id = config['CLIENT_ID']
            self.client_secret = config['CLIENT_SECRET']
            self.token = self._get_admin_token()
        except (AttributeError, KeyError) as e:
            logger.error(f"Keycloak admin client is not configured properly in settings.py: {e}")
            self.token = None


    def _get_admin_token(self):
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
            logger.error(f"Error getting Keycloak admin token: {e}")
            return None

    def update_user(self, user, user_data):
        if not self.token:
            logger.error("Cannot update Keycloak user: Admin client is not authenticated.")
            return {"error": "Authentication failed. Cannot get admin token."}

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
            logger.error(f"Error updating user {user.id} in Keycloak: {e}. Response: {e.response.text if e.response else 'No response'}")
            return {"error": f"Failed to update user in Keycloak: {e}"}
