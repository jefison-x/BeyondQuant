"""Synthetic execution probe, run inside an isolated signal-sandbox container."""
import json
import urllib.request


def main():
    source = "class CustomStrategy:\n    def generate_signals(self, data, parameters):\n        return {symbol: pd.Series([1], index=['2026-09-01']) for symbol in ['000001.SZ', '600000.SH']}\n"
    payload = {'schema_version': 'byq-signal-sandbox-request-v1', 'profile': 'byq-signal-python-v1',
               'strategy': {'script': source}, 'parameters': {}, 'declared': {}, 'timeout_seconds': 2,
               'bars': [{'symbol': symbol, 'trade_date': '2026-09-01', 'open': 10, 'high': 10,
                         'low': 10, 'close': 10, 'volume': 100} for symbol in ['000001.SZ', '600000.SH']]}
    def execute(value):
        request = urllib.request.Request('http://127.0.0.1:8500/v1/execute',
            data=json.dumps(value).encode(), headers={'content-type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)
    result = execute(payload)
    assert result == {'ok': True, 'schema_version': 'byq-signal-sandbox-response-v1', 'signals': [
        {'symbol': '000001.SZ', 'trade_date': '2026-09-01', 'signal': 1},
        {'symbol': '600000.SH', 'trade_date': '2026-09-01', 'signal': 1},
    ]}, result
    rejected = execute({**payload, 'strategy': {'script': 'import os\n' + source}})
    assert rejected.get('ok') is False and rejected.get('error_code') == 'source_rejected', rejected
    print(json.dumps({'synthetic': True, 'signal_count': 2, 'forbidden_import': 'rejected',
                      'scope': 'signal component only, not H5 research completion'}))


if __name__ == '__main__':
    main()
