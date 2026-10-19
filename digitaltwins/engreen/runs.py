"""How Engreen runs read in the "My runs" list."""

from ..runs.descriptions import inputs_describer
from .views import TWIN_SLUG


@inputs_describer(TWIN_SLUG)
def describe_engreen_run(run):
    inputs = run.inputs or {}
    if inputs.get('mode') == 'existing':
        label = f"Station {inputs.get('station', '')}"
    else:
        label = f"New plant · {inputs.get('n_panels')} × {inputs.get('wp_panel')} Wp"
    if inputs.get('days'):
        label += f" · {inputs['days']} days"
    return label
