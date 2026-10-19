"""One-line summaries of what a run was asked, for the "My runs" list.

Each twin registers its own with @inputs_describer in its `runs` module (loaded
by DigitaltwinsConfig.ready); a twin without one shows an empty cell.
"""

_DESCRIBERS = {}


def inputs_describer(twin_slug):
    """Register `describe(run) -> str` for the runs of `twin_slug`."""
    def register(describe):
        _DESCRIBERS[twin_slug] = describe
        return describe
    return register


def describe_inputs(run):
    describe = _DESCRIBERS.get(run.twin_slug)
    return describe(run) if describe else ''
