from importlib import import_module
import os
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests


class MovieMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, RENDER='1', KEEP_ALIVE='0', FLASK_SECRET_KEY='metadata-test'):
            cls.movies = import_module('app')

    def setUp(self):
        self.client = self.movies.app.test_client()
        self.rows = pd.DataFrame([{'id': 42, 'title': 'Film & Friends', 'release_date': '2000-01-01',
                                   'runtime': 99, 'vote_average': 7.2, 'overview': 'Catalog synopsis.'}])
        for name, value in [('find_catalog_movie', Mock(return_value=self.rows)),
                            ('TMDB_API_KEY', 'test'), ('YOUTUBE_API_KEY', '')]:
            patcher = patch.object(self.movies, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.movies.fetch_tmdb_details.cache_clear()
        self.addCleanup(self.movies.fetch_tmdb_details.cache_clear)

    def test_selected_film_refresh_cache_trailer_and_review_sources(self):
        def trailer(key, official, date):
            return {'site': 'YouTube', 'type': 'Trailer', 'key': key, 'official': official, 'published_at': date}

        api = Mock()
        api.json.return_value = {
            'vote_average': 8.1, 'vote_count': 4200, 'runtime': 105, 'overview': 'Updated synopsis.',
            'genres': [{'name': 'Drama'}],
            'credits': {'cast': [{'name': 'Lead'}], 'crew': [{'name': 'Filmmaker', 'job': 'Director'}]},
            'videos': {'results': [trailer('aaaaaaaaaaa', False, '2025'), trailer('bbbbbbbbbbb', True, '2024'),
                                   trailer('not-a-valid-key', True, '2026')]},
            'reviews': {'results': [{'author': 'Critic', 'content': 'R' * 500, 'id': 'abc123'}]},
        }
        with patch.object(self.movies.requests, 'get', return_value=api) as send:
            with patch.object(self.movies.time, 'monotonic', return_value=900):
                details = self.client.get('/movie_details?id=42').json
                self.assertEqual(details['tmdb_status'], 'updated')
                self.assertEqual((details['vote_average'], details['vote_count'], details['runtime']), (8.1, 4200, 105))
                self.assertEqual((details['cast'], details['directors'], details['genres']), (['Lead'], ['Filmmaker'], 'Drama'))
                self.assertEqual(details['overview'], 'Updated synopsis.')
                self.assertEqual(details['tmdb_reviews'][0]['url'], 'https://www.themoviedb.org/review/abc123')
                self.assertLess(len(details['tmdb_reviews'][0]['excerpt']), 500)
                video = self.client.post('/get_trailer', data={'id': '42', 'title': 'Film & Friends'}).json
                self.assertEqual(video['video_id'], 'bbbbbbbbbbb')
                self.assertEqual(send.call_count, 1)
                self.assertTrue(send.call_args.args[0].endswith('/movie/42'))
            with patch.object(self.movies.time, 'monotonic', return_value=1800):
                self.client.get('/movie_details?id=42')
            self.assertEqual(send.call_count, 2)

    def test_outage_and_unconfigured_keys_keep_local_details_and_search(self):
        with patch.object(self.movies.requests, 'get', side_effect=requests.Timeout) as send:
            details = self.client.get('/movie_details?id=42').json
            self.assertEqual((details['tmdb_status'], details['runtime'], details['overview']),
                             ('catalog', 99, 'Catalog synopsis.'))
            self.client.get('/movie_details?id=42')
            self.assertEqual(send.call_count, 2)
            with patch.object(self.movies, 'TMDB_API_KEY', ''):
                fallback = self.client.post('/get_trailer', data={'id': '42', 'title': 'Film & Friends'}).json
                self.assertIsNone(fallback['video_id'])
                self.assertIn('Film+%26+Friends+official+trailer', fallback['search_url'])
                self.assertEqual(send.call_count, 2)

    def test_youtube_fallback_accepts_only_valid_video_id(self):
        result = Mock()
        with patch.object(self.movies, 'TMDB_API_KEY', ''), patch.object(self.movies, 'YOUTUBE_API_KEY', 'test'), \
                patch.object(self.movies.requests, 'get', return_value=result):
            for video_id in ['abcdefghijk', 'invalid']:
                result.json.return_value = {'items': [{'id': {'videoId': video_id}}]}
                video = self.client.post('/get_trailer', data={'id': '42', 'title': 'Film'}).json
                if video_id == 'abcdefghijk':
                    self.assertEqual(video['embed_url'], 'https://www.youtube.com/embed/abcdefghijk')
                else:
                    self.assertIsNone(video['video_id'])
