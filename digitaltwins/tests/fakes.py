"""Test doubles shared by the digitaltwins tests.

Object storage is faked at the `boto3.client` boundary rather than by patching
names inside digitaltwins modules, so the tests keep working when the code that
calls it moves between modules.
"""

import io
from contextlib import contextmanager
from unittest.mock import patch

from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from django.test import override_settings


class FakeS3Client:
    """In-memory stand-in for the boto3 S3 client calls object_storage makes."""

    def __init__(self):
        self.objects = {}  # (bucket, key) -> bytes
        self.fail_uploads = False
        self.fail_reads = False

    def _missing(self, operation):
        return ClientError({'Error': {'Code': 'NoSuchKey', 'Message': 'Not found'}}, operation)

    def upload_fileobj(self, Fileobj, Bucket, Key, ExtraArgs=None, Config=None, Callback=None):
        if self.fail_uploads:
            raise ClientError({'Error': {'Code': 'InternalError', 'Message': 'boom'}}, 'PutObject')
        data = Fileobj.read()
        self.objects[(Bucket, Key)] = data
        if Callback is not None:
            Callback(len(data))

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        if self.fail_reads or (Bucket, Key) not in self.objects:
            raise self._missing('GetObject')
        data = self.objects[(Bucket, Key)]
        return {'Body': StreamingBody(io.BytesIO(data), len(data)), 'ContentLength': len(data)}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def keys(self):
        return sorted(key for _, key in self.objects)


@contextmanager
def fake_object_storage():
    client = FakeS3Client()
    with override_settings(OBJECT_STORAGE_ACCESS_KEY='test', OBJECT_STORAGE_SECRET_KEY='test'), \
            patch('boto3.client', return_value=client):
        yield client


def queued_task_funcs():
    """Dotted paths of the tasks enqueued into the django_q ORM broker so far."""
    from django_q.models import OrmQ

    return [queued.task.get('func') for queued in OrmQ.objects.order_by('pk')]


# A minimal BER result file in InfluxDB line protocol: two samples per power tag,
# one second apart, plus a non-power line the parser must skip.
SAMPLE_LP = b'\n'.join([
    b'power,serialNumber=6 JT_3001=4.0 1700000000000000000',
    b'power,serialNumber=6 JT_3002=3.0 1700000000000000000',
    b'power,serialNumber=6 JT_3003=1.0 1700000000000000000',
    b'power,serialNumber=6 ET_1001=40.0 1700000000000000000',
    b'power,serialNumber=6 IT_1101=75.0 1700000000000000000',
    b'temperature,serialNumber=6 TT_1=55.0 1700000000000000000',
    b'power,serialNumber=6 JT_3001=6.5 1700000001000000000',
    b'power,serialNumber=6 JT_3002=5.0 1700000001000000000',
    b'power,serialNumber=6 JT_3003=1.5 1700000001000000000',
    b'power,serialNumber=6 ET_1001=42.0 1700000001000000000',
    b'power,serialNumber=6 IT_1101=120.0 1700000001000000000',
]) + b'\n'
