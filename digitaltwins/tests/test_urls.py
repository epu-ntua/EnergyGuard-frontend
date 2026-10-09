"""URL contract and page smoke tests for the digitaltwins app.

The URL names are reversed by templates across the platform and the paths are
baked into emails and notifications already sent to users, so both must stay
fixed while the app's code is reorganised.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

BER = '/digitaltwins/ber-hydrogen/ber-hydrogen-dt'

URL_CONTRACT = [
    ('riga-map', [], '/digitaltwins/riga/rea-riga-dt/'),
    ('rea-riga-buildings-api', [], '/digitaltwins/riga/rea-riga-dt/buildings/'),
    ('digitaltwins-list', [], '/digitaltwins/list/'),
    ('cea-ai-scenario-generation', [], '/digitaltwins/cea-hydrogen/ai-scenario-generation/'),
    ('cea-dt-simulation', [], '/digitaltwins/cea-hydrogen/dt-simulation/'),
    ('cea-dt-simulation-documentation', [], '/digitaltwins/cea-hydrogen/dt-simulation/documentation/'),
    ('ber-hydrogen-dt', [], f'{BER}/'),
    ('ber-hydrogen-documentation', [], f'{BER}/documentation/'),
    ('ber-hydrogen-submit', [], f'{BER}/submit/'),
    ('ber-hydrogen-runs', [], f'{BER}/requests/'),
    ('ber-hydrogen-request-detail', [7], f'{BER}/requests/7/'),
    ('ber-hydrogen-request-cancel', [7], f'{BER}/requests/7/cancel/'),
    ('ber-hydrogen-request-hide', [7], f'{BER}/requests/7/hide/'),
    ('ber-hydrogen-request-result-download', [7], f'{BER}/requests/7/result/'),
    ('ber-hydrogen-request-status', [7], f'{BER}/requests/7/status/'),
    ('ber-management-list', [], f'{BER}/management/'),
    ('ber-management-detail', [7], f'{BER}/management/7/'),
    ('ber-management-upload-progress', [], f'{BER}/management/upload-progress/'),
    ('ber-management-replace-result', [7], f'{BER}/management/7/replace-result/'),
    ('ber-management-archive', [7], f'{BER}/management/7/archive/'),
    ('ber-management-restore', [7], f'{BER}/management/7/restore/'),
    ('ber-management-panel', [7], f'{BER}/management/7/panel/'),
    ('ber-management-experiment-download', [7], f'{BER}/management/7/experiment.json'),
    ('ber-management-download', [7], f'{BER}/management/7/download/'),
    ('cartif-hydrogen-dt', [], '/digitaltwins/cartif-hydrogen/cartif-hydrogen-dt/'),
    ('engreen-antrodoco-dt', [], '/digitaltwins/antrodoco/engreen-antrodoco-dt/'),
    ('engreen-pv-simulate', [], '/digitaltwins/antrodoco/engreen-antrodoco-dt/simulate/'),
    ('engreen-stations-api', [], '/digitaltwins/antrodoco/engreen-antrodoco-dt/stations/'),
    ('ciemat-forecasting-dt', [], '/digitaltwins/ciemat/ciemat-forecasting-dt/'),
    ('ciemat-forecast', [], '/digitaltwins/ciemat/ciemat-forecasting-dt/forecast/'),
    ('ciemat-calculate', [], '/digitaltwins/ciemat/ciemat-forecasting-dt/calculate/'),
    ('ciemat-compare', [], '/digitaltwins/ciemat/ciemat-forecasting-dt/compare/'),
    ('rdn-grid-dt', [], '/digitaltwins/rdn-grid/rdn-grid-dt/'),
    ('rdn-grid-runs', [], '/digitaltwins/rdn-grid/rdn-grid-dt/runs/'),
    ('rdn-grid-results', [7], '/digitaltwins/rdn-grid/rdn-grid-dt/runs/7/'),
    ('rdn-grid-result-data', [7], '/digitaltwins/rdn-grid/rdn-grid-dt/runs/7/result.json'),
    ('rdn-grid-simulate', [], '/digitaltwins/rdn-grid/rdn-grid-dt/simulate/'),
    ('rdn-grid-job-status', [], '/digitaltwins/rdn-grid/rdn-grid-dt/status/'),
    ('rdn-grid-follow', [], '/digitaltwins/rdn-grid/rdn-grid-dt/follow/'),
    ('dt-save-result', [], '/digitaltwins/results/save/'),
    ('digitaltwins-detail', ['ber-hydrogen'], '/digitaltwins/ber-hydrogen/'),
]

DETAIL_SLUGS = [
    'rdn-grid', 'ciemat-microgrid', 'cea-hydrogen', 'ber-hydrogen',
    'cartif-hydrogen', 'rea-riga', 'engreen-antrodoco',
]

# Pages that render from templates alone, with no call to an external service.
PAGES = [
    'riga-map', 'digitaltwins-list', 'cea-ai-scenario-generation', 'cea-dt-simulation',
    'cea-dt-simulation-documentation', 'ber-hydrogen-dt', 'ber-hydrogen-documentation',
    'ber-hydrogen-runs', 'cartif-hydrogen-dt', 'engreen-antrodoco-dt', 'ciemat-forecasting-dt',
    'rdn-grid-dt', 'rdn-grid-runs',
]


class UrlContractTests(TestCase):
    def test_every_url_name_keeps_its_path(self):
        for name, args, path in URL_CONTRACT:
            with self.subTest(name=name):
                self.assertEqual(reverse(name, args=args), path)

    def test_twin_slugs_do_not_shadow_the_fixed_routes(self):
        """The catch-all <slug> route must stay last, after every fixed route."""
        self.assertEqual(reverse('digitaltwins-list'), '/digitaltwins/list/')
        response = self.client.get('/digitaltwins/list/')
        self.assertNotEqual(response.status_code, 404)


class PageSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email='smoke@example.com', password='pw')
        cls.ber_staff = User.objects.create_user(email='smoke-staff@example.com', password='pw')
        cls.ber_staff.user_permissions.add(Permission.objects.get(codename='manage_ber_requests'))

    def test_pages_require_login(self):
        for name in PAGES:
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)

    def test_pages_render(self):
        self.client.force_login(self.user)
        for name in PAGES:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_twin_detail_pages_render(self):
        self.client.force_login(self.user)
        for slug in DETAIL_SLUGS:
            with self.subTest(slug=slug):
                response = self.client.get(reverse('digitaltwins-detail', args=[slug]))
                self.assertEqual(response.status_code, 200)

    def test_unknown_twin_slug_is_404(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('digitaltwins-detail', args=['no-such-twin']))
        self.assertEqual(response.status_code, 404)

    def test_ber_management_navbar_link_only_for_ber_staff(self):
        url = reverse('ber-management-list')

        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse('digitaltwins-list')), url)

        self.client.force_login(self.ber_staff)
        self.assertContains(self.client.get(reverse('digitaltwins-list')), url)
