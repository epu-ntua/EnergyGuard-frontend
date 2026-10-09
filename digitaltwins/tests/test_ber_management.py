"""BER experiment management (BER staff side), through the URLs."""

import json

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from digitaltwins.models import BerExperimentRequest

from .ber_factories import make_completed_request, make_request, make_user
from .fakes import SAMPLE_LP, fake_object_storage, queued_task_funcs

Status = BerExperimentRequest.Status
XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
BUCKET = settings.OBJECT_STORAGE_BUCKET_SIMULATIONS


def result_upload(name='result.lp', data=SAMPLE_LP):
    return SimpleUploadedFile(name, data, content_type='application/octet-stream')


class BerManagementPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.requester = make_user('perm-requester@example.com')
        cls.experiment_request = make_request(cls.requester, status=Status.COMPLETED, result_key='x/y.lp')

    def test_users_without_the_permission_get_403_everywhere(self):
        self.client.force_login(self.requester)
        pk = self.experiment_request.pk

        for name, args, method in [
            ('ber-management-list', [], 'get'),
            ('ber-management-panel', [pk], 'get'),
            ('ber-management-detail', [pk], 'get'),
            ('ber-management-detail', [pk], 'post'),
            ('ber-management-replace-result', [pk], 'post'),
            ('ber-management-archive', [pk], 'post'),
            ('ber-management-restore', [pk], 'post'),
            ('ber-management-experiment-download', [pk], 'get'),
            ('ber-management-download', [pk], 'get'),
            ('ber-management-upload-progress', [], 'get'),
        ]:
            with self.subTest(name=name, method=method):
                response = getattr(self.client, method)(reverse(name, args=args))
                self.assertEqual(response.status_code, 403)

        self.experiment_request.refresh_from_db()
        self.assertIsNone(self.experiment_request.archived_at)

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(reverse('ber-management-list'))
        self.assertEqual(response.status_code, 302)


class BerManagementListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = make_user('list-staff@example.com', ber_staff=True)
        requester = make_user('list-requester@example.com')
        cls.pending = make_request(requester)
        cls.completed = make_request(requester, status=Status.COMPLETED)
        cls.archived = make_request(requester, status=Status.REJECTED)
        BerExperimentRequest.objects.filter(pk=cls.archived.pk).update(archived_at=cls.archived.created_at)

    def setUp(self):
        self.client.force_login(self.staff)

    def _listed(self, **params):
        response = self.client.get(reverse('ber-management-list'), params)
        self.assertEqual(response.status_code, 200)
        return response, [r.pk for r in response.context['page_obj']]

    def test_all_tab_excludes_archived(self):
        response, listed = self._listed()

        self.assertCountEqual(listed, [self.pending.pk, self.completed.pk])
        counts = {tab['value']: tab['count'] for tab in response.context['status_tabs']}
        self.assertEqual(counts, {
            '': 2, 'pending': 1, 'completed': 1, 'rejected': 0, 'cancelled': 0, 'archived': 1,
        })

    def test_status_tab_filters(self):
        self.assertEqual(self._listed(status='pending')[1], [self.pending.pk])

    def test_archived_tab(self):
        self.assertEqual(self._listed(status='archived')[1], [self.archived.pk])

    def test_unknown_status_falls_back_to_all(self):
        response, listed = self._listed(status='<script>')
        self.assertEqual(response.context['status_filter'], '')
        self.assertEqual(len(listed), 2)

    def test_selected_request_opens_its_panel(self):
        response, _ = self._listed(request=self.pending.pk)

        self.assertEqual(response.context['selected'], self.pending)
        self.assertContains(response, f'Request #{self.pending.pk}')

    def test_panel_fragment(self):
        response = self.client.get(reverse('ber-management-panel', args=[self.completed.pk]), {'status': 'completed'})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'digitaltwins/partials/ber-management-panel.html')
        self.assertEqual(response.context['status_filter'], 'completed')

    def test_detail_get_redirects_to_the_list_with_the_panel_open(self):
        response = self.client.get(reverse('ber-management-detail', args=[self.pending.pk]))
        self.assertRedirects(
            response, f"{reverse('ber-management-list')}?request={self.pending.pk}", fetch_redirect_response=False,
        )

    def test_experiment_json_download(self):
        response = self.client.get(reverse('ber-management-experiment-download', args=[self.pending.pk]))

        self.assertEqual(json.loads(response.content), self.pending.experiment_json)
        self.assertEqual(
            response['Content-Disposition'], f'attachment; filename="experiment_{self.pending.pk}.json"',
        )


class BerDecisionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = make_user('decide-staff@example.com', ber_staff=True)
        cls.requester = make_user('decide-requester@example.com')

    def setUp(self):
        self.client.force_login(self.staff)

    def _complete(self, experiment_request, *, upload=None, start='2026-01-01T09:00', end='2026-01-01T10:00', **extra):
        data = {'action': 'complete', 'actual_start': start, 'actual_end': end, 'status': 'pending', 'page': '1'}
        if upload is not None:
            data['result_file'] = upload
        return self.client.post(reverse('ber-management-detail', args=[experiment_request.pk]), data, **extra)

    def test_completing_stores_the_file_and_notifies_the_requester(self):
        experiment_request = make_request(self.requester)

        with fake_object_storage() as storage:
            response = self._complete(experiment_request, upload=result_upload(), **XHR)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {'redirect': f"{reverse('ber-management-list')}?status=pending&page=1&request={experiment_request.pk}"},
        )
        experiment_request.refresh_from_db()
        self.assertEqual(experiment_request.status, Status.COMPLETED)
        self.assertEqual(experiment_request.actual_start.isoformat(), '2026-01-01T09:00:00+00:00')
        self.assertEqual(experiment_request.actual_end.isoformat(), '2026-01-01T10:00:00+00:00')
        self.assertTrue(experiment_request.result_key.startswith(f'ber-hydrogen/{experiment_request.pk}/result-'))
        self.assertTrue(experiment_request.result_key.endswith('.lp'))
        self.assertEqual(storage.objects[(BUCKET, experiment_request.result_key)], SAMPLE_LP)
        self.assertEqual(queued_task_funcs(), [
            'digitaltwins.tasks.warm_ber_results_cache',
            'digitaltwins.tasks.notify_ber_request_decision',
        ])

    def test_completing_without_js_redirects(self):
        experiment_request = make_request(self.requester)

        with fake_object_storage():
            response = self._complete(experiment_request, upload=result_upload())

        self.assertEqual(response.status_code, 302)

    def test_invalid_completion_input_changes_nothing(self):
        cases = {
            'missing times': {'start': '', 'end': ''},
            'end before start': {'start': '2026-01-01T10:00', 'end': '2026-01-01T09:00'},
            'missing file': {'upload': None},
        }
        for label, overrides in cases.items():
            with self.subTest(label), fake_object_storage() as storage:
                experiment_request = make_request(self.requester)
                kwargs = {'upload': result_upload(), **overrides}
                response = self._complete(experiment_request, **kwargs, **XHR)

                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json())
                experiment_request.refresh_from_db()
                self.assertEqual(experiment_request.status, Status.PENDING)
                self.assertEqual(storage.keys(), [])

    def test_invalid_input_without_js_rerenders_the_page_with_the_error(self):
        experiment_request = make_request(self.requester)

        response = self._complete(experiment_request, upload=result_upload(), start='')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Provide a valid start and end time.')

    def test_storage_failure_keeps_the_request_pending(self):
        experiment_request = make_request(self.requester)

        with fake_object_storage() as storage:
            storage.fail_uploads = True
            response = self._complete(experiment_request, upload=result_upload(), **XHR)

        self.assertEqual(response.status_code, 400)
        experiment_request.refresh_from_db()
        self.assertEqual(experiment_request.status, Status.PENDING)
        self.assertEqual(queued_task_funcs(), [])

    def test_a_cancelled_request_cannot_be_completed(self):
        experiment_request = make_request(self.requester, status=Status.CANCELLED)

        with fake_object_storage() as storage:
            response = self._complete(experiment_request, upload=result_upload(), **XHR)

        self.assertEqual(response.json(), {'error': 'The requester cancelled this request.'})
        self.assertEqual(storage.keys(), [])
        self.assertEqual(queued_task_funcs(), [])

    def test_rejecting_requires_a_reason(self):
        experiment_request = make_request(self.requester)

        response = self.client.post(
            reverse('ber-management-detail', args=[experiment_request.pk]),
            {'action': 'reject', 'rejection_reason': '   '}, **XHR,
        )

        self.assertEqual(response.status_code, 400)
        experiment_request.refresh_from_db()
        self.assertEqual(experiment_request.status, Status.PENDING)

    def test_rejecting_notifies_the_requester(self):
        experiment_request = make_request(self.requester)

        response = self.client.post(
            reverse('ber-management-detail', args=[experiment_request.pk]),
            {'action': 'reject', 'rejection_reason': 'Setpoints too aggressive'},
        )

        self.assertEqual(response.status_code, 302)
        experiment_request.refresh_from_db()
        self.assertEqual(experiment_request.status, Status.REJECTED)
        self.assertEqual(experiment_request.rejection_reason, 'Setpoints too aggressive')
        self.assertEqual(queued_task_funcs(), ['digitaltwins.tasks.notify_ber_request_decision'])

    def test_a_decided_request_cannot_be_decided_again(self):
        experiment_request = make_request(self.requester, status=Status.REJECTED)

        response = self.client.post(
            reverse('ber-management-detail', args=[experiment_request.pk]),
            {'action': 'reject', 'rejection_reason': 'again'}, **XHR,
        )

        self.assertEqual(response.json(), {'error': 'This request has already been decided.'})
        self.assertEqual(queued_task_funcs(), [])

    def test_unknown_action_is_rejected(self):
        experiment_request = make_request(self.requester)

        response = self.client.post(reverse('ber-management-detail', args=[experiment_request.pk]), {'action': 'x'})

        self.assertEqual(response.status_code, 400)


class BerReplaceResultTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = make_user('replace-staff@example.com', ber_staff=True)
        cls.requester = make_user('replace-requester@example.com')

    def setUp(self):
        self.client.force_login(self.staff)

    def _replace(self, experiment_request, upload):
        return self.client.post(
            reverse('ber-management-replace-result', args=[experiment_request.pk]),
            {'result_file': upload}, **XHR,
        )

    def test_replacing_swaps_the_file_and_deletes_the_old_one(self):
        new_data = SAMPLE_LP.replace(b'JT_3001=6.5', b'JT_3001=7.5')
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.requester, storage, data=SAMPLE_LP)
            old_key = experiment_request.result_key
            response = self._replace(experiment_request, result_upload(data=new_data))

        self.assertEqual(response.status_code, 200)
        experiment_request.refresh_from_db()
        self.assertNotEqual(experiment_request.result_key, old_key)
        self.assertEqual(storage.keys(), [experiment_request.result_key])
        self.assertEqual(storage.objects[(BUCKET, experiment_request.result_key)], new_data)
        self.assertEqual(queued_task_funcs(), [
            'digitaltwins.tasks.warm_ber_results_cache',
            'digitaltwins.tasks.notify_ber_results_updated',
        ])

    def test_requester_sees_the_new_results_after_a_replace(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.requester, storage, data=SAMPLE_LP)
            detail_url = reverse('ber-hydrogen-request-detail', args=[experiment_request.pk])

            self.client.force_login(self.requester)
            self.assertEqual(self.client.get(detail_url).context['kpis']['peak_total_power'], 6.5)

            self.client.force_login(self.staff)
            self._replace(experiment_request, result_upload(data=SAMPLE_LP.replace(b'JT_3001=6.5', b'JT_3001=7.5')))

            self.client.force_login(self.requester)
            self.assertEqual(self.client.get(detail_url).context['kpis']['peak_total_power'], 7.5)

    def test_only_completed_requests_can_be_replaced(self):
        experiment_request = make_request(self.requester)

        with fake_object_storage() as storage:
            response = self._replace(experiment_request, result_upload())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(storage.keys(), [])

    def test_staff_download_of_the_result_file(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.requester, storage, data=SAMPLE_LP)
            response = self.client.get(reverse('ber-management-download', args=[experiment_request.pk]))
            content = b''.join(response.streaming_content)

        self.assertEqual(content, SAMPLE_LP)

    def test_download_without_a_file_is_404(self):
        experiment_request = make_request(self.requester, status=Status.COMPLETED)
        response = self.client.get(reverse('ber-management-download', args=[experiment_request.pk]))
        self.assertEqual(response.status_code, 404)


class BerUploadProgressTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = make_user('progress-staff@example.com', ber_staff=True)
        cls.other_staff = make_user('progress-other@example.com', ber_staff=True)
        cls.requester = make_user('progress-requester@example.com')

    def test_progress_is_reported_to_the_uploader_only(self):
        experiment_request = make_request(self.requester)
        upload_id = 'abcdef12-3456'
        self.client.force_login(self.staff)

        with fake_object_storage():
            self.client.post(reverse('ber-management-detail', args=[experiment_request.pk]), {
                'action': 'complete', 'actual_start': '2026-01-01T09:00', 'actual_end': '2026-01-01T10:00',
                'result_file': result_upload(), 'upload_id': upload_id,
            }, **XHR)

        progress_url = reverse('ber-management-upload-progress')
        self.assertEqual(
            self.client.get(progress_url, {'id': upload_id}).json(),
            {'sent': len(SAMPLE_LP), 'total': len(SAMPLE_LP)},
        )

        self.client.force_login(self.other_staff)
        self.assertEqual(self.client.get(progress_url, {'id': upload_id}).json(), {'sent': 0, 'total': 0})

    def test_malformed_upload_id_is_rejected(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('ber-management-upload-progress'), {'id': '../x'})
        self.assertEqual(response.status_code, 400)


class BerArchiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = make_user('archive-staff@example.com', ber_staff=True)
        cls.requester = make_user('archive-requester@example.com')

    def setUp(self):
        self.client.force_login(self.staff)

    def test_archiving_a_finished_request_records_who(self):
        experiment_request = make_request(self.requester, status=Status.COMPLETED)

        response = self.client.post(reverse('ber-management-archive', args=[experiment_request.pk]), {'page': '1'})

        self.assertRedirects(response, f"{reverse('ber-management-list')}?page=1", fetch_redirect_response=False)
        experiment_request.refresh_from_db()
        self.assertIsNotNone(experiment_request.archived_at)
        self.assertEqual(experiment_request.archived_by, self.staff)

    def test_a_pending_request_cannot_be_archived(self):
        experiment_request = make_request(self.requester)

        response = self.client.post(reverse('ber-management-archive', args=[experiment_request.pk]))

        self.assertContains(response, 'Pending requests cannot be archived')
        experiment_request.refresh_from_db()
        self.assertIsNone(experiment_request.archived_at)

    def test_restoring(self):
        experiment_request = make_request(self.requester, status=Status.REJECTED)
        self.client.post(reverse('ber-management-archive', args=[experiment_request.pk]))

        response = self.client.post(
            reverse('ber-management-restore', args=[experiment_request.pk]), {'status': 'archived'},
        )

        self.assertRedirects(
            response, f"{reverse('ber-management-list')}?status=archived", fetch_redirect_response=False,
        )
        experiment_request.refresh_from_db()
        self.assertIsNone(experiment_request.archived_at)
        self.assertIsNone(experiment_request.archived_by)

    def test_archive_requires_post(self):
        experiment_request = make_request(self.requester, status=Status.COMPLETED)
        response = self.client.get(reverse('ber-management-archive', args=[experiment_request.pk]))
        self.assertEqual(response.status_code, 405)
