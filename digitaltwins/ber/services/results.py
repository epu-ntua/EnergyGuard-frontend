"""BER experiment results: parsing the uploaded .lp file into chart data and KPIs.

Used by the requester's results page and by the qcluster task that pre-builds
the same context right after BER uploads a file.
"""

import bisect
import hashlib
from datetime import datetime, timezone
from math import ceil

from django.core.cache import cache

from digitaltwins.common import RESULT_STREAM_CHUNK, format_duration

from .storage import open_result_file

_BER_POWER_TAGS = ('JT_3001', 'JT_3002', 'JT_3003', 'ET_1001', 'IT_1101')
_BER_CHART_MAX_POINTS = 1500
# The parsed/downsampled chart data is cached instead of re-reading the .lp per view.
# The cache key includes the result_key, so replacing the file (which always writes
# a fresh key) makes the next view rebuild from the new file.
_BER_RESULTS_CACHE_TIMEOUT = 7 * 24 * 3600

BER_SIGNAL_INFO = {
    'JT_3001': {'label': 'Total power',        'unit': 'kW', 'description': "The total electrical power drawn by the whole system, including the stack and all auxiliary equipment (pumps, cooling, controls)."},
    'JT_3002': {'label': 'Stack power',         'unit': 'kW', 'description': 'The electrical power consumed by the electrolyzer stack itself, where hydrogen is actually produced.'},
    'JT_3003': {'label': 'Auxiliaries power',   'unit': 'kW', 'description': 'The power used by supporting equipment such as pumps, valves, and cooling, on top of the stack.'},
    'ET_1001': {'label': 'Stack voltage',       'unit': 'V',  'description': 'The electrical voltage across the electrolyzer stack while it operates.'},
    'IT_1101': {'label': 'Stack current',       'unit': 'A',  'description': 'The electrical current flowing through the stack. Together with voltage, it determines the power delivered to the stack.'},
}


class BerResultUnreadable(Exception):
    """The stored result file has no usable power signals."""


def ber_experiment_id(experiment_request):
    return f'BER-{experiment_request.created_at:%Y}-{experiment_request.pk:06d}'


def _split_power_line(line):
    """The three space-separated parts of a `power,...` line, or None for any other line."""
    if isinstance(line, bytes):
        line = line.decode('utf-8', errors='replace')
    if not line.startswith('power,'):
        return None
    parts = line.rstrip('\r\n').split(' ')
    return parts if len(parts) == 3 else None


def _power_point(parts):
    """(tag, ts_seconds, value) from a split power line, or None if it isn't a usable sample."""
    tag, sep, raw_value = parts[1].partition('=')
    if not sep or tag not in _BER_POWER_TAGS:
        return None
    try:
        return tag, int(parts[2]) / 1_000_000_000, float(raw_value)
    except ValueError:
        return None


def _parse_ber_power_signals(lines):
    """Parse the power signals out of a BER .lp (InfluxDB line protocol) file.

    `lines` yields bytes or str lines, e.g. `power,serialNumber=6 JT_3001=1.23 <ns>`.
    Returns (series, serial_number); serial_number is None if no power line has one.
    """
    series = {tag: [] for tag in _BER_POWER_TAGS}
    serial_number = None
    for line in lines:
        parts = _split_power_line(line)
        if parts is None:
            continue
        if serial_number is None:
            for tag_pair in parts[0].split(',')[1:]:
                key, _, tag_value = tag_pair.partition('=')
                if key == 'serialNumber' and tag_value:
                    serial_number = tag_value
        point = _power_point(parts)
        if point is None:
            continue
        tag, ts_seconds, value = point
        series[tag].append((ts_seconds, value))
    for tag in series:
        series[tag].sort(key=lambda point: point[0])
    return series, serial_number


def has_power_signals(lines):
    """True as soon as one line is a sample the results page can chart.

    The upload check: same rules as _parse_ber_power_signals, but it stops at the
    first match and keeps nothing, so a valid file costs a few lines to verify.
    """
    for line in lines:
        parts = _split_power_line(line)
        if parts is not None and _power_point(parts) is not None:
            return True
    return False


def _downsample(points, max_points=_BER_CHART_MAX_POINTS):
    n = len(points)
    if n <= max_points:
        return list(points)
    stride = ceil(n / max_points)
    sampled = points[::stride]
    if (n - 1) % stride != 0:
        sampled = list(sampled) + [points[-1]]
    return list(sampled)


def _forward_fill(points, timestamps):
    """Sample a step-wise (last-known-value) series at the given timestamps."""
    ts_list = [ts for ts, _ in points]
    values = [value for _, value in points]
    result = []
    for t in timestamps:
        i = bisect.bisect_right(ts_list, t) - 1
        result.append(values[i] if i >= 0 else values[0])
    return result


def _aligned_stacked_series(series, tags, max_points=_BER_CHART_MAX_POINTS):
    """Resample several tags onto one shared timestamp grid so their values can be
    stacked (summed) correctly in a stacked area chart, even though each tag was
    originally logged at its own, differing sample rate."""
    merged_ts = sorted({ts for tag in tags for ts, _ in series[tag]})
    merged_ts = _downsample(merged_ts, max_points)
    return {
        tag: [[round(ts * 1000), round(value, 3)]
              for ts, value in zip(merged_ts, _forward_fill(series[tag], merged_ts))]
        for tag in tags
    }


def _compute_ber_kpis(series):
    def values(tag):
        return [value for _, value in series[tag]]

    return {
        'peak_total_power':   max(values('JT_3001'), default=0.0),
        'avg_stack_power':    (sum(values('JT_3002')) / len(series['JT_3002'])) if series['JT_3002'] else 0.0,
        'avg_aux_power':      (sum(values('JT_3003')) / len(series['JT_3003'])) if series['JT_3003'] else 0.0,
        'peak_stack_current': max(values('IT_1101'), default=0.0),
        'peak_stack_voltage': max(values('ET_1001'), default=0.0),
    }


def _build_ber_kpi_cards(kpis):
    return [
        {'label': 'Peak Total Power',   'value': kpis['peak_total_power'],   'unit': 'kW', 'value_class': 'text-body-emphasis'},
        {'label': 'Avg. Stack Power',   'value': kpis['avg_stack_power'],    'unit': 'kW', 'value_class': 'text-primary'},
        {'label': 'Avg. Aux Power',     'value': kpis['avg_aux_power'],      'unit': 'kW', 'value_class': 'text-turquoise'},
        {'label': 'Peak Stack Current', 'value': kpis['peak_stack_current'], 'unit': 'A',  'value_class': 'text-body-emphasis'},
        {'label': 'Peak Stack Voltage', 'value': kpis['peak_stack_voltage'], 'unit': 'V',  'value_class': 'text-body-emphasis'},
    ]


def _power_chart_axis_range(peak_total_power, step=2):
    """Round up to the next multiple of `step` above the peak so the power chart's
    Y axis renders a consistent 0, step, 2*step, ... grid (instead of amCharts'
    auto-rounded one), with one step of headroom if the peak lands exactly on max."""
    axis_max = ceil(peak_total_power / step) * step
    if axis_max <= peak_total_power:
        axis_max += step
    return {'min': 0, 'max': axis_max}


def build_ber_results_context(experiment_request):
    """Chart/KPI context for a completed request, parsed from its uploaded .lp file.

    Raises MinioUploadError if the file can't be read from object storage, and
    BerResultUnreadable if it contains no power signals.
    """
    result_key = experiment_request.result_key
    cache_key = f'ber_results_ctx_{experiment_request.pk}_{hashlib.sha256(result_key.encode()).hexdigest()[:16]}'
    context = cache.get(cache_key)
    if context is not None:
        return context

    body, _ = open_result_file(result_key)
    try:
        series, serial_number = _parse_ber_power_signals(body.iter_lines(chunk_size=RESULT_STREAM_CHUNK))
    finally:
        body.close()

    all_timestamps = [ts for points in series.values() for ts, _ in points]
    if not all_timestamps:
        raise BerResultUnreadable(f'No power signals in {result_key}')

    run_start = min(all_timestamps)
    run_end = max(all_timestamps)

    kpis = _compute_ber_kpis(series)

    def _chart_points(tag):
        return [[round(ts * 1000), round(value, 3)] for ts, value in _downsample(series[tag])]

    experiment_id = ber_experiment_id(experiment_request)
    serial_number = serial_number or '—'
    run_timestamp = datetime.fromtimestamp(run_start, tz=timezone.utc)
    duration_label = format_duration(run_end - run_start)

    context = {
        'experiment_id': experiment_id,
        'serial_number': serial_number,
        'run_timestamp': run_timestamp,
        'duration_label': duration_label,
        'kpis': kpis,
        'kpi_cards': _build_ber_kpi_cards(kpis),
        'result_meta': {
            'experiment_id': experiment_id,
            'serial_number': serial_number,
            'run_timestamp': run_timestamp.isoformat(),
            'duration_label': duration_label,
        },
        'chart_power': _aligned_stacked_series(series, ('JT_3002', 'JT_3003')),
        'chart_power_axis': _power_chart_axis_range(kpis['peak_total_power']),
        'chart_electrical': {tag: _chart_points(tag) for tag in ('ET_1001', 'IT_1101')},
    }
    cache.set(cache_key, context, timeout=_BER_RESULTS_CACHE_TIMEOUT)
    return context
