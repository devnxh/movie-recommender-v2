import unittest

from personalization import personalized_ids


class PersonalizedFeedTest(unittest.TestCase):
    # Most popular first; row numbers deliberately differ from catalog IDs.
    catalog = {20: 0, 12: 1, 41: 2, 70: 3, 38: 4, 54: 5, 61: 6}

    def test_two_neighbors_outvote_one_and_hidden_titles_are_excluded(self):
        profiles = {
            1: {12, 20, 999},
            2: {12, 20, 41, 999},
            3: {12, 41, 38},
            4: {20, 70},
            5: {999, 61},
        }
        def no_content_needed(*_):
            self.fail('Collaborative candidates already fill this page')

        movies, basis = personalized_ids(1, profiles, self.catalog, no_content_needed, limit=3)
        self.assertEqual(basis, 'shared_favorites')
        self.assertEqual(movies, [41, 70, 38])

    def test_one_new_member_uses_all_favorites_for_content_then_popularity(self):
        def similar(own, limit):
            self.assertEqual(own, {12, 20})
            return [12, 999, 61, 61]

        movies, basis = personalized_ids(1, {1: {20, 12}, 2: {61}}, self.catalog, similar, limit=4)
        self.assertEqual(basis, 'similar_films')
        self.assertEqual(movies, [61, 41, 70, 38])

    def test_new_and_archived_profiles_use_popularity(self):
        def no_known_seed(*_):
            self.fail('No content query expected')

        for user_id, profiles in ((None, {}), (3, {3: set()}), (2, {2: {999}})):
            with self.subTest(user_id=user_id):
                movies, basis = personalized_ids(user_id, profiles, self.catalog, no_known_seed, limit=2)
                self.assertEqual((movies, basis), ([20, 12], 'popular'))

    def test_favorites_exhaust_the_catalog(self):
        movies, _ = personalized_ids(1, {1: set(self.catalog)}, self.catalog, lambda *_: [])
        self.assertEqual(movies, [])


if __name__ == '__main__':
    unittest.main()
