"""Exercise the actual Compose probes without network or production credentials."""
import os
from pathlib import Path
import re
import sys
import textwrap
import types
import unittest
from unittest.mock import MagicMock, patch

COMPOSE = (Path(__file__).resolve().parents[2] / 'compose.yml').read_text()


def block(service):
    return re.search(rf'(?ms)^  {service}:\n(.*?)(?=^  [\w-]+:|\Z)', COMPOSE)[1]


def probe(service):
    value = re.search(r'(?ms)^        - \|-\n(.*?)(?=^      interval:)', block(service))[1]
    return compile(textwrap.dedent(value), service + '-healthcheck', 'exec')


class RebootReadinessTests(unittest.TestCase):
    def test_all_persistent_services_restart(self):
        for service in ('postgres', 'backend', 'mcp', 'runtime-adapter', 'gateway',
                        'frontend', 'data-worker', 'ml-worker', 'signal-worker',
                        'signal-sandbox', 'feedback-hub-relay', 'feedback-publisher'):
            with self.subTest(service=service):
                self.assertIn('    restart: unless-stopped\n', block(service))

    def test_gateway_requires_every_dependency_and_redacts_failures(self):
        urls = ('http://127.0.0.1:8100/readyz', 'http://backend:8000/readyz',
                'http://mcp:8300/healthz', 'http://runtime-adapter:8400/readyz')
        for broken in (None, *urls, 'invalid-json', 'not-ready'):
            with self.subTest(broken=broken):
                seen = []
                def request(url, timeout):
                    self.assertEqual(timeout, 1)
                    seen.append(url)
                    if url == broken:
                        raise OSError('private connection detail')
                    response = MagicMock()
                    response.__enter__.return_value = response
                    response.status = 200
                    response.read.return_value = (b'invalid' if broken == 'invalid-json'
                        else b'{"runtime_adapter":"unavailable"}' if broken == 'not-ready'
                        else b'{"runtime_adapter":"ready"}')
                    return response
                with patch('urllib.request.urlopen', request):
                    if broken is None:
                        exec(probe('gateway'), {})
                        self.assertEqual(seen, list(urls))
                    else:
                        with self.assertRaises(SystemExit) as failure:
                            exec(probe('gateway'), {})
                        self.assertEqual(failure.exception.code, 1)

    def test_backend_requires_live_database(self):
        for db_ok in (True, False):
            with self.subTest(db_ok=db_ok):
                engine = MagicMock()
                connection = engine.connect.return_value.__enter__.return_value
                connection.execute.return_value.scalar.return_value = 1
                if not db_ok:
                    engine.connect.side_effect = OSError('private database detail')
                create = MagicMock(return_value=engine)
                module = types.SimpleNamespace(create_engine=create, text=lambda value: value)
                response = MagicMock()
                response.__enter__.return_value.status = 200
                with patch.dict(sys.modules, sqlalchemy=module), patch.dict(os.environ, BYQ_DATABASE_URL='synthetic'), patch('urllib.request.urlopen', return_value=response):
                    if db_ok:
                        exec(probe('backend'), {})
                        connection.execute.assert_called_once_with('SELECT 1')
                        engine.dispose.assert_called_once()
                    else:
                        with self.assertRaises(SystemExit) as failure:
                            exec(probe('backend'), {})
                        self.assertEqual(failure.exception.code, 1)
                    self.assertEqual(create.call_args.kwargs['connect_args']['connect_timeout'], 2)


if __name__ == '__main__':
    unittest.main()
