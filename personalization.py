"""Rank a private feed using only movie IDs from the current catalog."""

from collections import Counter
from math import sqrt


def personalized_ids(member_id, favorites, catalog_rows, similar_ids, limit=12):
    """Return IDs and their strongest source: shared_favorites, similar_films, or popular.

    catalog_rows maps current movie IDs to matrix rows in descending popularity order.
    similar_ids receives all visible favorites together, so content ranking requires
    one sparse similarity query regardless of the number of favorites.
    """
    own = favorites.get(member_id, set()).intersection(catalog_rows)
    scores = Counter()
    if own:
        for neighbor_id, saved in favorites.items():
            if neighbor_id == member_id:
                continue
            visible = saved.intersection(catalog_rows)
            overlap = len(own.intersection(visible))
            if overlap:
                # Cosine similarity of the two binary favorite vectors, computed on sets.
                weight = overlap / sqrt(len(own) * len(visible))
                for movie_id in visible.difference(own):
                    scores[movie_id] += weight

    ranked = sorted(scores, key=lambda movie_id: (-scores[movie_id], movie_id))[:limit]
    basis = 'shared_favorites' if ranked else 'popular'
    seen = own.union(ranked)
    if own and len(ranked) < limit:
        for movie_id in similar_ids(own, limit):
            if movie_id in catalog_rows and movie_id not in seen:
                seen.add(movie_id)
                ranked.append(movie_id)
                if basis == 'popular':
                    basis = 'similar_films'
                if len(ranked) == limit:
                    break
    if len(ranked) < limit:
        for movie_id in catalog_rows:
            if movie_id not in seen:
                ranked.append(movie_id)
                if len(ranked) == limit:
                    break
    return ranked, basis
