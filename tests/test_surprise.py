import os
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd


class SurpriseRouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import using the small hosted catalog. Each test supplies its own movie rows.
        with patch.dict(os.environ, {
            'RENDER': '1', 'KEEP_ALIVE': '0', 'DATABASE_URL': '',
            'CINEWATCH_DB_PATH': '', 'FLASK_SECRET_KEY': 'fixture-key',
        }):
            import app
        cls.service = app

    def setUp(self):
        self.catalog = pd.DataFrame({
            'id': list(range(1, 17)),
            'title': [f'Film {i}' for i in range(1, 17)],
            'genres': ['Drama'] * 14 + ['Comedy', 'Comedy'],
            'release_date': ['2004-01-01'] * 15 + ['2020-01-01'],
            'vote_average': [8] * 16,
            'runtime': [100] * 15 + [120],
            'vote_count': list(range(16, 0, -1)),
        })
        state = patch.multiple(self.service, movies_df=self.catalog,
                               vote_counts=self.catalog.vote_count.to_numpy(), quality_scores=np.ones(16))
        state.start()
        self.addCleanup(state.stop)
        self.client = self.service.app.test_client()

    def test_draw_uses_entire_filtered_set_and_skips_recent(self):
        criteria = dict(genre='Drama', year_min='2004', year_max='2004', min_rating='8',
                        max_runtime='100', sort='rating')
        first_page = self.client.get('/movies', query_string={**criteria, 'view': 'card'}).get_json()
        second_page = self.client.get('/movies', query_string={**criteria, 'view': 'card', 'page': 2}).get_json()
        self.assertEqual(len(first_page), 12)
        seen = ','.join(str(movie['id']) for movie in first_page)
        picked = self.client.get('/api/surprise', query_string={**criteria, 'recent': seen})
        self.assertEqual(picked.status_code, 200)
        self.assertTrue(picked.cache_control.no_store)
        self.assertIn(picked.json['movie'], second_page)
        self.assertTrue(picked.json['has_alternative'])
        self.assertFalse(picked.json['restarted'])

    def test_exhaustion_skips_last_film_after_reset(self):
        # Older caches can store numeric identifiers as text.
        self.catalog['id'] = self.catalog['id'].astype(str)
        picked = self.client.get('/api/surprise?genre=Comedy&recent=99,invalid,15,16').get_json()
        self.assertEqual(picked['movie']['id'], 15)
        self.assertTrue(picked['restarted'])
        self.assertTrue(picked['has_alternative'])

    def test_singleton_empty_and_invalid_filters(self):
        single = self.client.get('/api/surprise?year_min=2020&recent=16').get_json()
        self.assertEqual(single['movie']['id'], 16)
        self.assertFalse(single['has_alternative'])
        self.assertEqual(self.client.get('/api/surprise?max_runtime=70').get_json(),
                         {'movie': None, 'restarted': False, 'has_alternative': False})
        bad = self.client.get('/api/surprise?year_min=2010&year_max=2000')
        self.assertEqual(bad.status_code, 400)
        self.assertIn('error', bad.json)

    def test_legacy_titles_without_ids_can_be_picked(self):
        self.catalog.drop(columns='id', inplace=True)
        picked = self.client.get('/api/surprise?year_min=2020&recent=1,2').get_json()
        self.assertEqual(picked['movie']['title'], 'Film 16')
        self.assertIsNone(picked['movie']['id'])
        self.assertFalse(picked['has_alternative'])
