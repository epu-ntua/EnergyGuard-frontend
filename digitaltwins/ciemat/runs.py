"""How CIEMAT runs read in the "My runs" list."""

from ..runs.descriptions import inputs_describer
from .views import TWIN_SLUG


def _forecast_label(cfg):
    return f"{str(cfg.get('generation_type', '')).title()} · {cfg.get('lat')}, {cfg.get('lon')}"


@inputs_describer(TWIN_SLUG)
def describe_ciemat_run(run):
    inputs = run.inputs or {}
    if run.operation == 'compare-forecasts':
        return f"{_forecast_label(inputs.get('a', {}))} vs {_forecast_label(inputs.get('b', {}))}"
    if run.operation == 'forecast':
        return _forecast_label(inputs)
    if run.operation == 'calculate':
        return f"{inputs.get('resolution')} model · device {inputs.get('device_id')}"
    return f"device {inputs.get('device_id')}"
