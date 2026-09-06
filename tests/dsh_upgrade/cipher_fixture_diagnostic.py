"""Bounded synthetic diagnosis of unchanged-byte tamper fixture; not a CI waiver.

Run only in a network-none tested Backend image. No database, model or real key.
The original failing test and application cryptography implementation stay intact.
"""
import json
from unittest.mock import patch

from app.credentials import CredentialCipher, CredentialUnavailable
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def main():
    key, plaintext, aad = bytes(range(32)), b'sk-test-value', b'record-a'
    for counter in range(4096):
        nonce = counter.to_bytes(12, 'big')
        if AESGCM(key).encrypt(nonce, plaintext, aad)[-1] == 0:
            break
    else:
        raise AssertionError('bounded synthetic collision not found')
    cipher = CredentialCipher.for_test({'old': key}, 'old')
    with patch('app.credentials.os.urandom', return_value=nonce):
        original = cipher.encrypt(plaintext.decode(), aad=aad)
    unchanged = dict(original)
    unchanged['ciphertext'] = bytes(original['ciphertext'])[:-1] + b'\x00'
    assert unchanged == original
    assert cipher.decrypt(unchanged, aad=aad) == plaintext.decode()
    changed = dict(original)
    changed['ciphertext'] = bytes(original['ciphertext'])[:-1] + b'\x01'
    try:
        cipher.decrypt(changed, aad=aad)
    except CredentialUnavailable:
        pass
    else:
        raise AssertionError('actual changed ciphertext was not rejected')
    try:
        cipher.decrypt(original, aad=b'record-b')
    except CredentialUnavailable:
        pass
    else:
        raise AssertionError('changed AAD was not rejected')
    print(json.dumps({'result': 'REPRODUCED', 'synthetic_only': True,
                      'counter': counter, 'fixture_no_op': True,
                      'real_tamper_rejected': True, 'changed_aad_rejected': True,
                      'original_test_modified': False, 'ci_failure_waived': False}))


if __name__ == '__main__':
    main()
