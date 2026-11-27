import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from flask import Flask

from accounts import init_accounts
from reviews import register_reviews


class ReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        app = Flask(__name__)
        with patch.dict(os.environ, DATABASE_URL='', CINEWATCH_DB_PATH=str(Path(temp.name) / 'library.db'),
                        FLASK_SECRET_KEY='review-test', RENDER_EXTERNAL_URL='', VERCEL=''):
            init_accounts(app, lambda ids: [])
        register_reviews(app, lambda movie_id: SimpleNamespace(empty=movie_id not in (1, 2)))
        self.app = app
        self.guest = app.test_client()
        self.url = '/api/movies/1/reviews'

    def member(self, name):
        client = self.app.test_client()
        result = client.post('/api/account/register', json={'username': name, 'password': 'library test passphrase'})
        self.assertEqual(result.status_code, 201)
        return client

    def test_create_edit_and_delete_only_own_review(self):
        alice = self.member('Alice')
        bob = self.member('Bob')
        self.assertEqual(self.guest.head(self.url).status_code, 200)
        self.assertEqual(self.guest.get(self.url).json, {'reviews': [], 'mine': None})
        first = {'rating': 9, 'body': 'A beautiful film.'}
        self.assertEqual(alice.put(self.url, json=first).json['mine'], first)
        bob.put(self.url, json={'rating': 7, 'body': 'Enjoyed the ending.'})
        edited = {'rating': 10, 'body': '  Even better the second time.  '}
        result = alice.put(self.url, json=edited).json
        self.assertEqual(result['mine'], {'rating': 10, 'body': edited['body'].strip()})
        self.assertCountEqual([r['author'] for r in result['reviews']], ['Alice', 'Bob'])
        public = self.guest.get(self.url)
        self.assertEqual(public.json['reviews'], result['reviews'])
        self.assertIsNone(public.json['mine'])
        self.assertTrue(public.cache_control.no_store)
        self.assertEqual(alice.get('/api/movies/2/reviews').json['reviews'], [])
        for _ in range(2):
            deleted = alice.delete(self.url, json={}).json
            self.assertIsNone(deleted['mine'])
            self.assertEqual([r['author'] for r in deleted['reviews']], ['Bob'])

    def test_review_requires_valid_film_member_and_input(self):
        self.assertEqual(self.guest.get('/api/movies/3/reviews').status_code, 404)
        self.assertEqual(self.guest.put(self.url, json={}).status_code, 401)
        self.assertEqual(self.guest.delete(self.url, json={}).status_code, 401)
        member = self.member('Writer')
        for review in [{'rating': True, 'body': 'A film'}, {'rating': 11, 'body': 'A film'},
                       {'rating': 7, 'body': ' '}, {'rating': 1, 'body': 'a' * 1201}]:
            with self.subTest(review=review):
                self.assertEqual(member.put(self.url, json=review).status_code, 400)
        self.assertEqual(member.put(self.url, data={'rating': '2'}).status_code, 415)
        self.assertEqual(member.delete(self.url, json={}, headers={'Origin': 'https://other.example'}).status_code, 403)
        body = '🎞' * 1200
        self.assertEqual(member.put(self.url, json={'rating': 8, 'body': body}).json['mine']['body'], body)
