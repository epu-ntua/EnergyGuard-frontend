"""The "My runs" tab of the twins list: the user's runs of every twin in one list
(digitaltwins.runs.overview)."""

import gzip

from django.conf import settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from digitaltwins.common import RUNS_PAGE_SIZE
from digitaltwins.models import BerExperimentRequest, DtRun, RdnSimulationJob
from digitaltwins.runs.overview import GROUP_OF_STATUS
from digitaltwins.runs.services import record_run

from .test_runs import RunsTestCase


class StatusGroupsTests(RunsTestCase):
    def test_every_status_of_every_model_has_a_group(self):
        for model in (DtRun, RdnSimulationJob, BerExperimentRequest):
            for status in model.Status.values:
                with self.subTest(model=model.__name__, status=status):
                    self.assertIn(status, GROUP_OF_STATUS)


class AllRunsTabTests(RunsTestCase):
    """The "My runs" tab of the twins list: the user's runs of every twin in one list."""

    def make_rdn_job(self, user=None, **extra):
        extra.setdefault('status', 'completed')
        job = RdnSimulationJob.objects.create(user=user or self.user, use_case='VoltageControl', grid_section='A', **extra)
        RdnSimulationJob.objects.filter(pk=job.pk).update(rdn_request_id=job.pk + 1000)
        job.refresh_from_db()
        return job

    def make_ber_request(self, user=None, **extra):
        return BerExperimentRequest.objects.create(user=user or self.user, experiment_json=[], **extra)

    def list_runs(self, **params):
        response = self.client.get(reverse('digitaltwins-list'), {'tab': 'runs', **params})
        self.assertEqual(response.status_code, 200)
        return response, [(row['source'], row['ref']) for row in response.context['page_obj']]

    def test_runs_of_every_twin_are_listed_newest_first(self):
        dt_run = self.make_run()
        job = self.make_rdn_job(result_key='rdn/result.json')
        ber = self.make_ber_request()
        self.make_run(user=self.other)
        self.make_rdn_job(user=self.other)
        self.make_ber_request(user=self.other)

        response, rows = self.list_runs()

        self.assertEqual(rows, [('ber', ber.pk), ('rdn', job.rdn_request_id), ('dt', dt_run.pk)])
        self.assertEqual(response.context['active_tab'], 'runs')
        self.assertContains(response, reverse('engreen-antrodoco-run', args=[dt_run.pk]))
        self.assertContains(response, reverse('rdn-grid-results', args=[job.rdn_request_id]))
        self.assertContains(response, reverse('rdn-grid-result-data', args=[job.rdn_request_id]) + '?download=1')
        self.assertContains(response, reverse('ber-hydrogen-request-detail', args=[ber.pk]))
        self.assertNotContains(response, '{{')

    def test_a_failed_rdn_job_shows_a_generic_error_not_the_raw_one(self):
        self.make_rdn_job(status='failed', error_message='Component [Sim_gate] not found !')
        self.make_rdn_job(status='running')

        response, _ = self.list_runs()

        self.assertEqual([row['error'] for row in response.context['page_obj']], ['', RdnSimulationJob.FAILED_MESSAGE])
        self.assertNotContains(response, 'Sim_gate')

    def test_requests_the_user_removed_are_left_out(self):
        self.make_ber_request(status='cancelled', hidden_by_user_at=timezone.now())
        _, rows = self.list_runs()
        self.assertEqual(rows, [])

    def test_runs_are_filtered_by_twin_and_status(self):
        engreen = self.make_run()
        ciemat = record_run(user=self.user, twin_slug='ciemat-microgrid', operation='forecast', inputs={}, result={})
        failed = record_run(user=self.user, twin_slug='ciemat-microgrid', operation='forecast', inputs={}, error='boom')
        self.make_rdn_job()
        rejected = self.make_ber_request(status='rejected', rejection_reason='No slot')

        self.assertEqual(self.list_runs(twin='ciemat-microgrid')[1], [('dt', failed.pk), ('dt', ciemat.pk)])
        self.assertEqual(self.list_runs(status='failed')[1], [('ber', rejected.pk), ('dt', failed.pk)])
        self.assertEqual(self.list_runs(twin='engreen-antrodoco', status='completed')[1], [('dt', engreen.pk)])

        response, _ = self.list_runs(status='failed')
        counts = {item['label']: item['count'] for item in response.context['twin_filters']}
        self.assertEqual(counts, {'All': 2, 'Transmission Grid': 0, 'CIEMAT Microgrid': 1, 'PEM Electrolyzer': 1, 'Antrodoco REC': 0})

    def test_an_unknown_filter_is_ignored(self):
        run = self.make_run()
        _, rows = self.list_runs(twin='cea-hydrogen', status='bogus')
        self.assertEqual(rows, [('dt', run.pk)])

    def test_the_list_opens_on_the_twins_without_reading_any_run(self):
        self.make_run()
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('digitaltwins-list'))
        self.assertEqual(response.context['active_tab'], 'twins')
        run_tables = ('"dt_run"', '"rdn_simulation_job"', '"ber_experiment_request"')
        self.assertFalse([q['sql'] for q in queries if any(table in q['sql'] for table in run_tables)])
        self.assertNotIn('page_obj', response.context)

    def test_an_rdn_result_is_offered_only_once_the_job_completed(self):
        job = self.make_rdn_job(status='running', result_key='rdn/partial.json')
        response, _ = self.list_runs()
        self.assertNotContains(response, reverse('rdn-grid-result-data', args=[job.rdn_request_id]))

    def test_runs_of_a_twin_no_longer_in_the_catalog_are_left_out(self):
        DtRun.objects.create(user=self.user, twin_slug='retired-twin', operation='x', status='completed')
        response, rows = self.list_runs()
        self.assertEqual(rows, [])
        self.assertEqual(response.context['page_obj'].paginator.count, 0)

    def test_runs_created_at_the_same_moment_keep_one_order(self):
        run = self.make_run()
        ber = self.make_ber_request()
        DtRun.objects.filter(pk=run.pk).update(created_at=ber.created_at)
        _, rows = self.list_runs()
        self.assertEqual(rows, [('ber', ber.pk), ('dt', run.pk)])

    def test_page_links_keep_the_filters(self):
        for _ in range(RUNS_PAGE_SIZE + 1):
            self.make_run()
        response, _ = self.list_runs(twin='engreen-antrodoco')
        self.assertContains(response, f'Showing 1–{RUNS_PAGE_SIZE} of {RUNS_PAGE_SIZE + 1}')
        self.assertContains(response, 'href="?tab=runs&amp;twin=engreen-antrodoco&page=2"')


class AllRunsTabAgreesWithTwinViewsTests(RunsTestCase):
    """The tab decides on its own when a run can be opened or downloaded
    (digitaltwins.runs.overview); each twin's views decide again when asked.
    For every status of every model, with a result stored, a link the tab shows
    must answer 200 and a link it leaves out must not, so the two cannot drift."""

    def test_links_shown_are_the_links_the_twin_views_serve(self):
        bucket = settings.OBJECT_STORAGE_BUCKET_SIMULATIONS
        cases = []
        for status in DtRun.Status.values:
            run = DtRun.objects.create(user=self.user, twin_slug='engreen-antrodoco', operation='historical',
                                       status=status, result_key=f'dt-runs/{status}/result.json.gz')
            self.storage.objects[(bucket, run.result_key)] = gzip.compress(b'{}')
            cases.append(('dt', run.pk, status, reverse('engreen-antrodoco-run', args=[run.pk]),
                          reverse('dt-run-result-data', args=[run.pk]) + '?download=1'))
        for status in RdnSimulationJob.Status.values:
            job = RdnSimulationJob.objects.create(user=self.user, use_case='VoltageControl', grid_section='A',
                                                  status=status, result={'grid': {}})
            RdnSimulationJob.objects.filter(pk=job.pk).update(rdn_request_id=job.pk + 1000)
            ref = job.pk + 1000
            cases.append(('rdn', ref, status, reverse('rdn-grid-results', args=[ref]),
                          reverse('rdn-grid-result-data', args=[ref]) + '?download=1'))
        for status in BerExperimentRequest.Status.values:
            request = BerExperimentRequest.objects.create(user=self.user, experiment_json=[], status=status,
                                                          result_key=f'ber-hydrogen/{status}/result.lp')
            self.storage.objects[(bucket, request.result_key)] = b'result'
            cases.append(('ber', request.pk, status, reverse('ber-hydrogen-request-detail', args=[request.pk]),
                          reverse('ber-hydrogen-request-result-download', args=[request.pk])))

        response = self.client.get(reverse('digitaltwins-list'), {'tab': 'runs'})
        rows = {(row['source'], row['ref']): row for row in response.context['page_obj']}
        self.assertEqual(len(rows), len(cases))

        for source, ref, status, open_url, download_url in cases:
            row = rows[(source, ref)]
            for link, url in (('open', open_url), ('download', download_url)):
                with self.subTest(source=source, status=status, link=link):
                    served = self.client.get(url).status_code == 200
                    shown = row[f'{link}_url'] == url
                    self.assertEqual(shown, served, f'tab shows the link: {shown}; the view serves it: {served}')
