import unittest

from tests.dsh_upgrade.live_model_probe import g2_object_context, g2_summary_read_count


class G2EvidenceTests(unittest.TestCase):
    def test_only_visible_completed_synthetic_object_can_be_context(self):
        identity = "backtest_" + "a" * 32
        class Client:
            rows = [{"job_id": identity, "name": "U5 TEST completed small backtest", "status": "completed"}]
            def call(self, method, path):
                self.request = (method, path)
                return {"backtests": self.rows}
        client = Client()
        self.assertEqual(g2_object_context(client, identity)["backtest_job_id"], identity)
        self.assertEqual(client.request, ("GET", "/api/product/backtests?limit=100&offset=0"))
        for value in (None, "../production", "backtest_" + "b" * 32):
            with self.assertRaises(AssertionError):
                g2_object_context(client, value)
        for key, value in (("status", "running"), ("name", "real business object")):
            original = client.rows[0][key]
            client.rows[0][key] = value
            with self.assertRaises(AssertionError):
                g2_object_context(client, identity)
            client.rows[0][key] = original

    def test_summary_proof_requires_correct_object_and_http_success(self):
        identity = "backtest_" + "a" * 32
        line = f'INFO: 172.20.0.4:45678 - "GET /v1/research/backtests/{identity}/summary HTTP/1.1" 200 OK\n'
        self.assertEqual(g2_summary_read_count(line, identity), 1)
        self.assertEqual(g2_summary_read_count(line.replace("200 OK", "404 Not Found"), identity), 0)
        self.assertEqual(g2_summary_read_count(line, "backtest_" + "b" * 32), 0)
        self.assertEqual(g2_summary_read_count(line.replace("/summary", "/run").replace("GET ", "POST "), identity), 0)
        with self.assertRaises(AssertionError):
            g2_summary_read_count(line, ".*")


if __name__ == "__main__":
    unittest.main()
