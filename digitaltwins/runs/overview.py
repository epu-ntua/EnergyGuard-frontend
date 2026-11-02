"""Every run of a user across the twins, for the "My runs" tab of the twins list.

Runs are kept in three models with their own lifecycles: DtRun (CIEMAT, Engreen),
RdnSimulationJob and BerExperimentRequest. They are read here as one union of the
same columns, so the list is ordered and paged by the database; each row of the
page is then given its links and a label. Deleting, cancelling or hiding a run
means something different in each model, so those stay on each twin's own list.
"""

from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import BooleanField, CharField, Count, ExpressionWrapper, F, IntegerField, Q, TextField, Value
from django.db.models.functions import Coalesce
from django.urls import reverse

from ..catalog import DIGITAL_TWINS, DT_BY_SLUG
from ..common import RUNS_PAGE_SIZE
from ..models import BerExperimentRequest, DtRun, RdnSimulationJob
from ..rdn.validation import RDN_USE_CASES

RDN_SLUG = 'rdn-grid'
BER_SLUG = 'ber-hydrogen'

# The twins that keep runs, in catalog order.
RUN_TWINS = [dt for dt in DIGITAL_TWINS if 'runs' in dt or dt['slug'] in (RDN_SLUG, BER_SLUG)]
RUN_TWINS_BY_SLUG = {dt['slug']: dt for dt in RUN_TWINS}
DT_RUN_SLUGS = [dt['slug'] for dt in DIGITAL_TWINS if 'runs' in dt]

_Dt, _Rdn, _Ber = DtRun.Status, RdnSimulationJob.Status, BerExperimentRequest.Status

# The statuses of all three models, grouped for the filter and the badge colour.
# Every status must have a group (tests check it): a new one fails loudly instead
# of being shown under the wrong one.
STATUS_GROUPS = {
    'in_progress': {'label': 'In progress', 'statuses': (_Rdn.PENDING, _Rdn.RUNNING, _Ber.PENDING)},
    'completed': {'label': 'Completed', 'statuses': (_Dt.COMPLETED, _Rdn.COMPLETED, _Ber.COMPLETED)},
    'failed': {'label': 'Failed', 'statuses': (_Dt.FAILED, _Dt.NOT_KEPT, _Rdn.FAILED, _Ber.REJECTED)},
    'cancelled': {'label': 'Cancelled', 'statuses': (_Ber.CANCELLED,)},
}
GROUP_OF_STATUS = {str(status): group for group, spec in STATUS_GROUPS.items() for status in spec['statuses']}
STATUS_LABELS = {str(status): status.label for model in (DtRun, RdnSimulationJob, BerExperimentRequest) for status in model.Status}

# Every source annotates these, in this order, so the union lines its columns up.
_COLUMNS = ('source', 'ref', 'slug', 'kind', 'row_status', 'created', 'downloadable', 'error')


def _columns(queryset, *, source, ref, slug, kind, error, downloadable):
    return queryset.annotate(
        source=Value(source, output_field=CharField()),
        ref=ExpressionWrapper(ref, output_field=IntegerField()),
        slug=slug,
        kind=kind,
        row_status=F('status'),
        created=F('created_at'),
        downloadable=ExpressionWrapper(downloadable, output_field=BooleanField()),
        error=error,
    ).values(*_COLUMNS)


def _dt_runs(user):
    # Only twins still in the catalog with runs: any other has no list to link to.
    return _columns(
        DtRun.objects.filter(user=user, twin_slug__in=DT_RUN_SLUGS),
        source='dt', ref=F('pk'), slug=F('twin_slug'), kind=F('operation'),
        error=F('error_message'), downloadable=~Q(result_key=''),
    )


def _rdn_jobs(user):
    # rdn_request_id is empty only for the moment between creating a job and saving it.
    return _columns(
        RdnSimulationJob.objects.filter(user=user, rdn_request_id__isnull=False),
        source='rdn', ref=F('rdn_request_id'), slug=Value(RDN_SLUG, output_field=CharField()),
        kind=F('use_case'), error=Coalesce('error_message', Value(''), output_field=TextField()),
        # As rdn_grid_result_data: a result is served only once the job completed.
        downloadable=Q(status=_Rdn.COMPLETED) & (~Q(result_key='') | Q(result__isnull=False)),
    )


def _ber_requests(user):
    return _columns(
        BerExperimentRequest.objects.filter(user=user, hidden_by_user_at__isnull=True),
        source='ber', ref=F('pk'), slug=Value(BER_SLUG, output_field=CharField()),
        kind=Value('experiment', output_field=CharField()), error=F('rejection_reason'),
        downloadable=Q(status=_Ber.COMPLETED) & ~Q(result_key=''),
    )


def _sources(user, status_group):
    """{twin slug or 'dt': queryset} of the user's runs, narrowed to `status_group`."""
    sources = {'dt': _dt_runs(user), RDN_SLUG: _rdn_jobs(user), BER_SLUG: _ber_requests(user)}
    if status_group in STATUS_GROUPS:
        statuses = STATUS_GROUPS[status_group]['statuses']
        sources = {key: qs.filter(row_status__in=statuses) for key, qs in sources.items()}
    return sources


def twin_counts(user, status_group=None):
    """{twin slug: number of the user's runs}, for the twin filter."""
    sources = _sources(user, status_group)
    counts = dict.fromkeys((dt['slug'] for dt in RUN_TWINS), 0)
    for row in sources.pop('dt').order_by().values('slug').annotate(n=Count('pk')):
        counts[row['slug']] = row['n']
    for slug, queryset in sources.items():
        counts[slug] = queryset.count()
    return counts


def user_runs(user, *, twin=None, status_group=None):
    """The user's runs of every twin, or of `twin`, newest first, as rows of _COLUMNS."""
    sources = _sources(user, status_group)
    if twin in (RDN_SLUG, BER_SLUG):
        selected = [sources[twin]]
    elif twin:
        selected = [sources['dt'].filter(twin_slug=twin)]
    else:
        selected = list(sources.values())
    first, *rest = selected
    runs = first.union(*rest, all=True) if rest else first
    # ref alone does not break ties: each source numbers its rows on its own.
    return runs.order_by('-created', 'source', '-ref')


def describe(row):
    """Add to a row of user_runs what the list shows: its twin, labels and links."""
    slug, ref, downloadable = row['slug'], row['ref'], row['downloadable']
    row['twin'] = DT_BY_SLUG[slug]
    row['status_label'] = STATUS_LABELS[row['row_status']]
    row['status_group'] = GROUP_OF_STATUS[row['row_status']]

    if row['source'] == 'rdn':
        row['type_label'] = RDN_USE_CASES.get(row['kind'], row['kind'])
        row['open_url'] = reverse('rdn-grid-results', args=[ref])
        row['download_url'] = reverse('rdn-grid-result-data', args=[ref]) + '?download=1' if downloadable else ''
        row['list_url'] = reverse('rdn-grid-runs')
    elif row['source'] == 'ber':
        row['type_label'] = 'Experiment request'
        row['open_url'] = reverse('ber-hydrogen-request-detail', args=[ref])
        row['download_url'] = reverse('ber-hydrogen-request-result-download', args=[ref]) if downloadable else ''
        row['list_url'] = reverse('ber-hydrogen-runs')
    else:
        config = row['twin'].get('runs', {})
        row['type_label'] = config.get('operations', {}).get(row['kind'], row['kind'])
        run_url_name = config.get('run_url_name')
        # As render_run_page: only a completed run has a page; the JSON is served whenever kept.
        opens = downloadable and run_url_name and row['row_status'] == _Dt.COMPLETED
        row['open_url'] = reverse(run_url_name, args=[ref]) if opens else ''
        row['download_url'] = reverse('dt-run-result-data', args=[ref]) + '?download=1' if downloadable else ''
        row['list_url'] = reverse('dt-runs', args=[slug])
    return row


def _query(twin, status):
    """The query string of the tab with these filters; page links append &page=."""
    return urlencode({'tab': 'runs', **({'twin': twin} if twin else {}), **({'status': status} if status else {})})


def runs_tab_context(user, params):
    """Template context of the "My runs" tab for the request's GET `params`.

    Unknown filter values are ignored rather than refused: they come from links,
    and a stale one should still open the tab.
    """
    twin = params.get('twin', '') if params.get('twin') in RUN_TWINS_BY_SLUG else ''
    status = params.get('status', '') if params.get('status') in STATUS_GROUPS else ''

    paginator = Paginator(user_runs(user, twin=twin or None, status_group=status or None), RUNS_PAGE_SIZE)
    page_obj = paginator.get_page(params.get('page'))
    for row in page_obj:
        describe(row)

    counts = twin_counts(user, status or None)
    twin_filters = [{'label': 'All', 'count': sum(counts.values()), 'query': _query('', status), 'active': not twin}]
    twin_filters += [
        {'label': dt['short_name'], 'count': counts[dt['slug']], 'query': _query(dt['slug'], status), 'active': twin == dt['slug']}
        for dt in RUN_TWINS
    ]
    status_filters = [{'label': 'All statuses', 'query': _query(twin, ''), 'active': not status}]
    status_filters += [
        {'label': group['label'], 'query': _query(twin, key), 'active': status == key}
        for key, group in STATUS_GROUPS.items()
    ]

    return {
        'page_obj': page_obj,
        'page_range': paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1),
        'page_ellipsis': Paginator.ELLIPSIS,
        'runs_query': _query(twin, status),
        'twin_filters': twin_filters,
        'status_filters': status_filters,
        'status_label': STATUS_GROUPS[status]['label'] if status else 'All statuses',
        'filtered': bool(twin or status),
    }
