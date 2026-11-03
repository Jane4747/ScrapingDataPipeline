"""Regression tests for the system-TLS transport used by 国密/SM2 public sites.

The transport may change how the handshake is performed; it may never weaken
certificate validation or turn an access denial into a successful fetch.
"""
import subprocess
import unittest
from unittest import mock

from pipeline.research.fetch import (Fetcher, _SystemTLSResponse, OPENSSL_INCOMPATIBLE,
                                     _FetchFailure)


class SystemTLSTransportTests(unittest.TestCase):
    def test_unknown_transport_is_rejected(self):
        with self.assertRaises(ValueError):
            Fetcher(transport='insecure')

    def test_openssl_incompatible_signature_is_recognised(self):
        self.assertTrue(OPENSSL_INCOMPATIBLE.search(
            "SSLError(1, '[SSL: BAD_ECPOINT] bad ecpoint (_ssl.c:1016)')"))
        self.assertFalse(OPENSSL_INCOMPATIBLE.search('Connection reset by peer'))

    def test_verification_failure_is_never_content(self):
        """curl exit 60 = OS-store verification failed; must surface as an error."""
        fetcher = Fetcher(timeout=5, retries=0, transport='system_tls')
        completed = subprocess.CompletedProcess(args=[], returncode=60,
                                                stdout=b'', stderr=b'SSL certificate problem')
        with mock.patch('pipeline.research.fetch._curl_binary', return_value='curl'), \
                mock.patch('pipeline.research.fetch.subprocess.run', return_value=completed):
            with self.assertRaises(_FetchFailure) as caught:
                fetcher._request_system_tls('https://example.gov.cn/x')
        self.assertIn('TLS verification failed in system store', str(caught.exception))

    def test_missing_curl_is_reported_not_silently_retried(self):
        fetcher = Fetcher(timeout=5, retries=0, transport='system_tls')
        with mock.patch('pipeline.research.fetch._curl_binary', return_value=None):
            with self.assertRaises(_FetchFailure) as caught:
                fetcher._request_system_tls('https://example.gov.cn/x')
        self.assertIn('requires curl', str(caught.exception))

    def test_response_shim_streams_and_closes(self):
        response = _SystemTLSResponse(200, {'Content-Type': 'text/html'}, b'x' * 10)
        self.assertEqual(b''.join(response.iter_content(chunk_size=4)), b'x' * 10)
        response.close()
        self.assertEqual(list(response.iter_content()), [])


if __name__ == '__main__':
    unittest.main()
