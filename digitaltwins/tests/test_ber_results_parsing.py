"""The BER .lp parsing behind the results page.

The parser stores samples in compact arrays and merges timestamps without
building their union, so that ~500 MB result files fit in the qcluster worker.
These tests pin that the charts and KPIs are exactly what the original
list-of-tuples implementation (kept below as the reference) produced.
"""

import bisect
import random
from math import ceil
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

from digitaltwins.ber.forms import ReplaceResultForm
from digitaltwins.ber.services import results

TAGS = ('JT_3001', 'JT_3002', 'JT_3003', 'ET_1001', 'IT_1101')
T0 = 1_700_000_000_000_000_000


# ── Reference: the implementation before the memory rework ──────────────────

def _ref_parse(lines):
    series = {tag: [] for tag in TAGS}
    for line in lines:
        parts = results._split_power_line(line)
        if parts is None:
            continue
        point = results._power_point(parts)
        if point is None:
            continue
        tag, ts, value = point
        series[tag].append((ts, value))
    for tag in series:
        series[tag].sort(key=lambda point: point[0])
    return series


def _ref_downsample(points, max_points):
    n = len(points)
    if n <= max_points:
        return list(points)
    stride = ceil(n / max_points)
    sampled = points[::stride]
    if (n - 1) % stride != 0:
        sampled = list(sampled) + [points[-1]]
    return list(sampled)


def _ref_forward_fill(points, timestamps):
    ts_list = [ts for ts, _ in points]
    values = [value for _, value in points]
    out = []
    for t in timestamps:
        i = bisect.bisect_right(ts_list, t) - 1
        out.append(values[i] if i >= 0 else values[0])
    return out


def _ref_aligned(series, tags, max_points):
    merged = _ref_downsample(sorted({ts for tag in tags for ts, _ in series[tag]}), max_points)
    return {
        tag: [[round(ts * 1000), round(v, 3)] for ts, v in zip(merged, _ref_forward_fill(series[tag], merged))]
        for tag in tags
    }


def _ref_chart_points(points, max_points):
    return [[round(ts * 1000), round(v, 3)] for ts, v in _ref_downsample(points, max_points)]


def _ref_kpis(series):
    def values(tag):
        return [v for _, v in series[tag]]
    return {
        'peak_total_power': max(values('JT_3001'), default=0.0),
        'avg_stack_power': (sum(values('JT_3002')) / len(series['JT_3002'])) if series['JT_3002'] else 0.0,
        'avg_aux_power': (sum(values('JT_3003')) / len(series['JT_3003'])) if series['JT_3003'] else 0.0,
        'peak_stack_current': max(values('IT_1101'), default=0.0),
        'peak_stack_voltage': max(values('ET_1001'), default=0.0),
    }


# ── Synthetic files ──────────────────────────────────────────────────────────

def _synthetic_lp(seed, *, samples, shuffle=False):
    """Power lines at a different sample rate per tag, with duplicate timestamps,
    noise lines and, optionally, out-of-order lines."""
    rng = random.Random(seed)
    lines = []
    for index, tag in enumerate(TAGS):
        step_ms = (index + 1) * 7
        for i in range(samples // (index + 1)):
            ts = T0 + (i * step_ms + rng.choice((0, 0, 3))) * 1_000_000
            lines.append(f'power,serialNumber=6 {tag}={rng.uniform(-5, 50):.4f} {ts}'.encode())
    lines += [b'temperature,serialNumber=6 TT_1=55.0 1700000000000000000', b'power,broken line', b'']
    if shuffle:
        rng.shuffle(lines)
    return lines


class ParsingMatchesTheReferenceTests(SimpleTestCase):
    def _assert_same_output(self, lines, max_points):
        series, _ = results._parse_ber_power_signals(lines)
        reference = _ref_parse(lines)

        self.assertEqual(results._compute_ber_kpis(series), _ref_kpis(reference))
        self.assertEqual(
            results._aligned_stacked_series(series, ('JT_3002', 'JT_3003'), max_points),
            _ref_aligned(reference, ('JT_3002', 'JT_3003'), max_points),
        )
        for tag in ('ET_1001', 'IT_1101'):
            signal = series[tag]
            ours = [[round(signal.ts[i] * 1000), round(signal.values[i], 3)]
                    for i in results._sample_indices(len(signal), max_points)]
            self.assertEqual(ours, _ref_chart_points(reference[tag], max_points))

    def test_downsampled_output_is_unchanged(self):
        for seed in range(5):
            with self.subTest(seed=seed):
                self._assert_same_output(_synthetic_lp(seed, samples=4000), max_points=150)

    def test_out_of_order_files_are_sorted_like_before(self):
        for seed in range(5):
            with self.subTest(seed=seed):
                self._assert_same_output(_synthetic_lp(seed, samples=4000, shuffle=True), max_points=150)

    def test_output_below_the_point_limit_is_unchanged(self):
        self._assert_same_output(_synthetic_lp(7, samples=60), max_points=1500)

    def test_a_missing_stacked_tag_counts_as_zero(self):
        lines = [line for line in _synthetic_lp(3, samples=400) if b' JT_3002=' not in line]
        series, _ = results._parse_ber_power_signals(lines)

        stacked = results._aligned_stacked_series(series, ('JT_3002', 'JT_3003'), 150)

        self.assertEqual(len(stacked['JT_3002']), len(stacked['JT_3003']))
        self.assertTrue(stacked['JT_3003'])
        self.assertTrue(all(value == 0.0 for _, value in stacked['JT_3002']))

    def test_sampling_keeps_the_last_point(self):
        for n in (1, 2, 1500, 1501, 2999, 3000, 3001, 10_007):
            with self.subTest(n=n):
                indices = list(results._sample_indices(n, 1500))
                self.assertEqual(indices[-1], n - 1)
                self.assertLessEqual(len(indices), 1501)


class ResultFileSizeLimitTests(TestCase):
    def test_a_file_over_the_limit_is_refused_before_it_is_read(self):
        upload = SimpleUploadedFile('r.lp', b'power,serialNumber=6 JT_3001=1.0 1700000000000000000\n')
        with patch('digitaltwins.ber.forms.RESULT_FILE_MAX_SIZE_BYTES', upload.size - 1), \
                patch('digitaltwins.ber.forms.has_power_signals') as check:
            form = ReplaceResultForm(files={'result_file': upload})
            self.assertFalse(form.is_valid())

        self.assertIn('exceeds the', form.errors['result_file'][0])
        check.assert_not_called()
