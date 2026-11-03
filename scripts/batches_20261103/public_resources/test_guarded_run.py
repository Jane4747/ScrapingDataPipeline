"""Offline response-integrity guards; no browser or HTTP requests."""
import unittest
from unittest.mock import AsyncMock, patch
import guarded_run as g


class GuardTests(unittest.IsolatedAsyncioTestCase):
    def collector(self):
        c = g.GuardedCollector.__new__(g.GuardedCollector)
        c.stop_all_requests = False
        c.state = {'guard_page_hashes': {}}
        return c

    def task(self, page=1):
        return {'start': '2026-01-01', 'end': '2026-01-31', 'page': page, 'word': '医院'}

    async def call_query(self, c, rows, total=1, page=1):
        with patch.object(g.ng.Collector, 'query', new=AsyncMock(return_value={'data': {'records': rows, 'total': total}})):
            return await c.query(None, self.task(page))

    async def test_nonzero_total_with_empty_page_is_not_completion(self):
        with self.assertRaisesRegex(g.ng.StopCollection, 'nonzero'):
            await self.call_query(self.collector(), [])

    async def test_wrong_or_missing_publication_date_is_rejected(self):
        for value in ('2025-12-31', '', 'unknown'):
            with self.subTest(value=value), self.assertRaisesRegex(g.ng.StopCollection, 'outside query window'):
                await self.call_query(self.collector(), [{'publishTime': value}])

    async def test_repeated_page_is_rejected_but_same_page_retry_is_allowed(self):
        c = self.collector()
        rows = [{'id': '1', 'publishTime': '2026-01-12', 'title': '医院服务器采购', 'url': '/notice/1'}]
        await self.call_query(c, rows)
        await self.call_query(c, rows)
        with self.assertRaisesRegex(g.ng.StopCollection, 'repeated search page'):
            await self.call_query(c, rows, page=2)

    async def test_access_challenge_stops_subsequent_lists_and_details(self):
        c = self.collector()
        with patch.object(g.ng.Collector, 'query', new=AsyncMock(side_effect=g.ng.StopCollection('HTTP 403 challenge'))) as upstream:
            with self.assertRaises(g.ng.StopCollection):
                await c.query(None, self.task())
            with self.assertRaises(g.ng.StopCollection):
                await c.query(None, self.task(2))
            self.assertEqual(upstream.await_count, 1)
        with patch.object(g.ng.Collector, 'details', new=AsyncMock()) as upstream:
            await c.details(None, 10)
            upstream.assert_not_awaited()
        self.assertIn('access_stop', c.state)

    async def test_empty_search_with_zero_total_is_valid(self):
        body = await self.call_query(self.collector(), [], total=0)
        self.assertEqual(body['data']['total'], 0)


if __name__ == '__main__':
    unittest.main()
