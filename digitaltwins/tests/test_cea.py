"""The CEA scenario's variable list and the example scenario built from it."""

import json

from django.test import SimpleTestCase

from digitaltwins.pages import CEA_SAMPLE_JSON, CEA_VARIABLES


class CeaVariablesTests(SimpleTestCase):
    """The scenario builder's table, its Load example button and the documentation
    all read CEA_VARIABLES, while the example is written out by hand; the two must
    describe the same file."""

    def setUp(self):
        self.sample = json.loads(CEA_SAMPLE_JSON)

    def test_the_example_has_every_variable_in_order(self):
        self.assertEqual(list(self.sample), [v['name'] for v in CEA_VARIABLES])

    def test_signals_are_as_long_as_timestamp_and_scalars_are_single_values(self):
        length = len(self.sample['timeStamp'])
        for variable in CEA_VARIABLES:
            value = self.sample[variable['name']]
            with self.subTest(variable['name']):
                if variable['kind'] == 'signal':
                    self.assertEqual(len(value), length)
                else:
                    self.assertIsInstance(value, (int, float))

    def test_the_example_is_within_the_valid_ranges(self):
        for variable in CEA_VARIABLES:
            value = self.sample[variable['name']]
            for number in value if isinstance(value, list) else [value]:
                with self.subTest(variable['name'], value=number):
                    self.assertGreaterEqual(number, variable['min'])
                    if variable['max'] is not None:
                        self.assertLessEqual(number, variable['max'])
