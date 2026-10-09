from datetime import datetime, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from digitaltwins.models import BerExperimentRequest

User = get_user_model()

VALID_EXPERIMENT = [
    {'time': 0, 'command': 'set_control_mode', 'value': 'amp'},
    {'time': 1, 'command': 'set_regen_mode', 'value': 'instant'},
    {'time': 60, 'command': 'change_setpoint', 'value': '20'},
]


def make_user(email, *, ber_staff=False):
    user = User.objects.create_user(email=email, password='pw')
    if ber_staff:
        user.user_permissions.add(Permission.objects.get(codename='manage_ber_requests'))
    return user


def make_request(user, *, status=BerExperimentRequest.Status.PENDING, **extra):
    return BerExperimentRequest.objects.create(
        user=user, experiment_json=VALID_EXPERIMENT, status=status, **extra,
    )


def make_completed_request(user, storage, *, data, key=None, **extra):
    """A completed request whose result file is already in the fake storage."""
    experiment_request = make_request(user, status=BerExperimentRequest.Status.COMPLETED, **extra)
    key = key or f'ber-hydrogen/{experiment_request.pk}/result-existing.lp'
    storage.objects[(settings.OBJECT_STORAGE_BUCKET_SIMULATIONS, key)] = data
    BerExperimentRequest.objects.filter(pk=experiment_request.pk).update(
        result_key=key,
        actual_start=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        actual_end=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
    )
    experiment_request.refresh_from_db()
    return experiment_request
