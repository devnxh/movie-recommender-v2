import unittest

import pandas as pd

from discovery_filters import InvalidFilter, filtered_movies


class DiscoveryFiltersTest(unittest.TestCase):
    def setUp(self):
        self.catalog = pd.DataFrame({
            'title': ['Early', 'First tie', 'Second tie', 'Unknown', 'Other genre'],
            'release_date': ['1990-12-08', '2001-04-15', '2001-01-03', None, '2010-10-01'],
            'genres': ['Drama', 'Action, Drama', 'Drama', None, 'Comedy'],
            'vote_count': [500, 40, 90, 0, 20],
            'popularity': [80, 100, 120, None, 300],
            'vote_average': [6.5, 7.5, 7.5, None, 8.2],
            'runtime': [92, 130, 100, 0, 88],
        }, index=[31, 67, 60, 1, 8])

    def titles(self, **filters):
        return filtered_movies(self.catalog, filters).title.tolist()

    def test_combined_filters_are_inclusive_and_stable(self):
        filters = dict(genre='Drama', year_min='2001', year_max='2001', min_rating='7.5',
                       max_runtime='130', sort='rating')
        self.assertEqual(self.titles(**filters), ['First tie', 'Second tie'])
        self.assertEqual(self.titles(**{**filters, 'max_runtime': '100'}), ['Second tie'])
        self.assertEqual(self.titles(**{**filters, 'min_rating': '9'}), [])

    def test_sort_orders_and_missing_values(self):
        self.assertEqual(self.titles(sort='shortest'), ['Other genre', 'Early', 'Second tie', 'First tie', 'Unknown'])
        self.assertEqual(self.titles(sort='newest'), ['Other genre', 'First tie', 'Second tie', 'Early', 'Unknown'])
        self.assertEqual(self.titles()[:2], ['Early', 'Second tie'])
        self.assertEqual(self.titles(genre='DRAMA')[:2], ['Second tie', 'First tie'])
        self.assertNotIn('Unknown', self.titles(max_runtime='500'))

    def test_invalid_values(self):
        for invalid in [{'min_rating': 'nan'}, {'min_rating': '10.1'}, {'sort': 'invented'},
                        {'max_runtime': '0'}, {'max_runtime': '2.5'}, {'year_min': 'abc'},
                        {'year_min': '2009', 'year_max': '2001'}]:
            with self.subTest(invalid=invalid), self.assertRaises(InvalidFilter):
                self.titles(**invalid)

    def test_older_caches_and_pages(self):
        sparse = self.catalog.drop(columns=['runtime', 'release_date', 'popularity'])
        self.assertTrue(filtered_movies(sparse, {'year_min': '2000'}).empty)
        self.assertTrue(filtered_movies(sparse, {'max_runtime': '140'}).empty)
        self.assertEqual(filtered_movies(sparse, {'genre': 'Drama'}).iloc[0].title, 'Early')
        repeated = pd.concat([self.catalog] * 6, ignore_index=True)
        entire = filtered_movies(repeated, {'sort': 'rating'})
        next_page = filtered_movies(repeated, {'sort': 'rating'}).iloc[12:24]
        self.assertTrue(next_page.index.equals(entire.iloc[12:24].index))
        self.assertTrue(set(entire.iloc[:12].index).isdisjoint(next_page.index))
