"""BER experiment results: parsing the uploaded .lp file into chart data and KPIs.

The file is parsed only by the qcluster task (warm_ber_results_cache), queued
when BER uploads a file and again whenever the results page finds nothing
cached. The page itself only reads the cache: see get_ber_results.
"""

import bisect
import hashlib
import heapq
import logging
import time
from array import array
from datetime import datetime, timezone
from math import ceil
from typing import NamedTuple

from django.core.cache import cache
from django_q.tasks import async_task

from core.services.object_storage import MinioUploadError
from digitaltwins.common import RESULT_STREAM_CHUNK, format_duration

from .storage import open_result_file

logger = logging.getLogger(__name__)

_BER_POWER_TAGS = ('JT_3001', 'JT_3002', 'JT_3003', 'ET_1001', 'IT_1101')
_BER_CHART_MAX_POINTS = 1500
# Result files reach ~500 MB, so building the context takes a minute or more and
# runs only in the qcluster (see warm_ber_results_cache), never in a web request.
# The key includes the result_key and replacing the file always writes a fresh
# key, so a cached context is never stale. It still expires, so that contexts of
# replaced files and deleted requests don't pile up in the cache table (where the
# DatabaseCache would cull by key order, live entries included); an expired one
# is rebuilt in the background on the next view.
_BER_RESULTS_CACHE_TIMEOUT = 90 * 24 * 3600
# Each failure is remembered so the page can say what happened, for as long as
# a retry is not worth it:
# - the file has no power signals: retrying won't change that;
_UNREADABLE = 'unreadable'
# - object storage could not be read: likely transient, retried soon;
_STORAGE_FAILED = 'storage-failed'
_STORAGE_FAILURE_TIMEOUT = 5 * 60
# - anything else is a bug: retrying would re-parse the whole file only to fail
#   the same way, so it is retried rarely (a fix gets picked up within hours).
_BUILD_FAILED = 'build-failed'
_BUILD_FAILURE_TIMEOUT = 6 * 3600
_FAILURE_TIMEOUTS = {
    _UNREADABLE: _BER_RESULTS_CACHE_TIMEOUT,
    _STORAGE_FAILED: _STORAGE_FAILURE_TIMEOUT,
    _BUILD_FAILED: _BUILD_FAILURE_TIMEOUT,
}
# Held while a build is queued or running, so repeated views of a page that is
# still being prepared queue one build, not one per view. It outlives the
# qcluster's 30-minute task timeout, after which a stuck build is given up on.
_BUILD_LOCK_TIMEOUT = 35 * 60

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


class Signal(NamedTuple):
    """One power tag's samples as two parallel float arrays, sorted by time.

    array('d') holds 8 bytes per number, against ~110 bytes for a (ts, value)
    tuple in a list: a 500 MB file is ~9 million samples, so this is the
    difference between ~150 MB and over 1 GB in the worker.
    """
    ts: array
    values: array

    def __len__(self):
        return len(self.ts)


def _sorted_by_time(ts, values):
    """The arrays reordered by timestamp, keeping equal timestamps in file order.

    Exports are normally already in time order, which is checked in one pass
    without copying anything.
    """
    if all(ts[i] <= ts[i + 1] for i in range(len(ts) - 1)):
        return Signal(ts, values)
    order = sorted(range(len(ts)), key=ts.__getitem__)
    return Signal(array('d', (ts[i] for i in order)), array('d', (values[i] for i in order)))


def _parse_ber_power_signals(lines):
    """Parse the power signals out of a BER .lp (InfluxDB line protocol) file.

    `lines` yields bytes or str lines, e.g. `power,serialNumber=6 JT_3001=1.23 <ns>`.
    Returns (series, serial_number): a Signal per power tag, and None for the
    serial number if no power line has one.
    """
    raw = {tag: (array('d'), array('d')) for tag in _BER_POWER_TAGS}
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
        ts, values = raw[tag]
        ts.append(ts_seconds)
        values.append(value)
    series = {tag: _sorted_by_time(ts, values) for tag, (ts, values) in raw.items()}
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


def _sample_indices(n, max_points=_BER_CHART_MAX_POINTS):
    """Positions of an every-stride-th downsample of n points, always keeping the last."""
    if n <= max_points:
        return range(n)
    stride = ceil(n / max_points)
    indices = list(range(0, n, stride))
    if (n - 1) % stride != 0:
        indices.append(n - 1)
    return indices


def _forward_fill(signal, timestamps):
    """Sample a step-wise (last-known-value) signal at the given timestamps.

    A tag missing from the file contributes 0 to the stack, so a file without,
    say, auxiliaries power still shows the stack power it does have.
    """
    if not signal:
        return [0.0] * len(timestamps)
    result = []
    for t in timestamps:
        i = bisect.bisect_right(signal.ts, t) - 1
        result.append(signal.values[i] if i >= 0 else signal.values[0])
    return result


def _merged_timestamps(signals):
    """The distinct timestamps of several sorted signals, in order, without
    building the union in memory (a set of every timestamp of a 500 MB file is
    itself hundreds of MB)."""
    previous = None
    for ts in heapq.merge(*(signal.ts for signal in signals)):
        if ts != previous:
            yield ts
            previous = ts


def _aligned_stacked_series(series, tags, max_points=_BER_CHART_MAX_POINTS):
    """Resample several tags onto one shared timestamp grid so their values can be
    stacked (summed) correctly in a stacked area chart, even though each tag was
    originally logged at its own, differing sample rate."""
    signals = [series[tag] for tag in tags]
    # Two passes over the merge: one to count, one to pick the sampled positions.
    count = sum(1 for _ in _merged_timestamps(signals))
    wanted = iter(_sample_indices(count, max_points))
    next_wanted = next(wanted, None)
    merged_ts = []
    for position, ts in enumerate(_merged_timestamps(signals)):
        if position == next_wanted:
            merged_ts.append(ts)
            next_wanted = next(wanted, None)
            if next_wanted is None:
                break
    return {
        tag: [[round(ts * 1000), round(value, 3)]
              for ts, value in zip(merged_ts, _forward_fill(series[tag], merged_ts))]
        for tag in tags
    }


def _compute_ber_kpis(series):
    def average(tag):
        values = series[tag].values
        return sum(values) / len(values) if values else 0.0

    return {
        'peak_total_power':   max(series['JT_3001'].values, default=0.0),
        'avg_stack_power':    average('JT_3002'),
        'avg_aux_power':      average('JT_3003'),
        'peak_stack_current': max(series['IT_1101'].values, default=0.0),
        'peak_stack_voltage': max(series['ET_1001'].values, default=0.0),
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


def _cache_keys(request_id, result_key):
    suffix = f'{request_id}_{hashlib.sha256(result_key.encode()).hexdigest()[:16]}'
    return f'ber_results_ctx_{suffix}', f'ber_results_failed_{suffix}', f'ber_results_building_{suffix}'


def queue_results_build(request_id, result_key):
    """Queue the qcluster build of this file's results, unless one already is.

    The claim is what keeps two builds of the same 500 MB file from ever running
    side by side, however often the page is viewed meanwhile. It is held until
    the build ends, or for _BUILD_LOCK_TIMEOUT if the worker dies mid-build.

    Called inside the transaction that stores a new file too: the cache is the
    DatabaseCache on the default database, so there the claim commits or rolls
    back together with the queued task row (see services.requests).
    """
    building_key = _cache_keys(request_id, result_key)[2]
    if not cache.add(building_key, 1, timeout=_BUILD_LOCK_TIMEOUT):
        return False
    try:
        async_task('digitaltwins.ber.tasks.warm_ber_results_cache', request_id)
    except Exception:
        cache.delete(building_key)  # nothing was queued: the next view must retry
        raise
    return True


class ResultsState(NamedTuple):
    """What the results page can show right now: `context` once built; otherwise
    the recorded `failure`, or neither, meaning it is being built."""
    context: dict | None = None
    failure: str | None = None

    @property
    def unreadable(self):
        return self.failure == _UNREADABLE

    @property
    def storage_failed(self):
        return self.failure == _STORAGE_FAILED

    @property
    def build_failed(self):
        return self.failure == _BUILD_FAILED


def get_ber_results(experiment_request):
    """The results page's view of a completed request, without ever parsing the file.

    If nothing is cached, no failure is recorded and no build is in flight, it
    queues one.
    """
    request_id, result_key = experiment_request.pk, experiment_request.result_key
    context_key, failed_key, _ = _cache_keys(request_id, result_key)
    found = cache.get_many([context_key, failed_key])
    if context_key in found:
        return ResultsState(context=found[context_key])
    if found.get(failed_key) in _FAILURE_TIMEOUTS:
        return ResultsState(failure=found[failed_key])
    queue_results_build(request_id, result_key)
    return ResultsState()


def build_ber_results_context(experiment_request):
    """Parse the request's .lp file and cache the chart/KPI context. qcluster only:
    a 500 MB file takes a minute or more and ~150 MB of memory.

    Records the outcome for get_ber_results either way, and re-raises any
    failure so the task logs it.
    """
    context_key, failed_key, building_key = _cache_keys(experiment_request.pk, experiment_request.result_key)
    failure = None
    try:
        if cache.get(context_key) is None:
            context = _build_context(experiment_request)
            cache.set(context_key, context, timeout=_BER_RESULTS_CACHE_TIMEOUT)
            cache.delete(failed_key)
    except BerResultUnreadable:
        failure = _UNREADABLE
        raise
    except MinioUploadError:
        failure = _STORAGE_FAILED
        raise
    except Exception:
        failure = _BUILD_FAILED
        raise
    finally:
        # Recording the outcome must not replace the exception being raised.
        try:
            if failure is not None:
                cache.set(failed_key, failure, timeout=_FAILURE_TIMEOUTS[failure])
            cache.delete(building_key)
        except Exception:
            logger.exception('Could not record the BER results build outcome for request %s', experiment_request.pk)


def _build_context(experiment_request):
    result_key = experiment_request.result_key
    started = time.monotonic()
    body, content_length = open_result_file(result_key)
    try:
        series, serial_number = _parse_ber_power_signals(body.iter_lines(chunk_size=RESULT_STREAM_CHUNK))
    finally:
        body.close()

    non_empty = [signal for signal in series.values() if signal]
    if not non_empty:
        raise BerResultUnreadable(f'No power signals in {result_key}')

    # Each signal is sorted, so its first and last samples bound the run.
    run_start = min(signal.ts[0] for signal in non_empty)
    run_end = max(signal.ts[-1] for signal in non_empty)

    kpis = _compute_ber_kpis(series)

    def _chart_points(tag):
        signal = series[tag]
        return [[round(signal.ts[i] * 1000), round(signal.values[i], 3)] for i in _sample_indices(len(signal))]

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
    logger.info(
        'Built BER results for request %s: %s bytes, %s samples in %.1fs',
        experiment_request.pk, content_length, sum(len(signal) for signal in non_empty), time.monotonic() - started,
    )
    return context
