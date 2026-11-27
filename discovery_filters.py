"""Shared catalog selection for browsing and choosing a movie."""

import math

import pandas as pd


class InvalidFilter(ValueError):
    """A filter supplied by the visitor is invalid."""


def _number(args, key, cast, minimum, maximum=None):
    raw = args.get(key)
    if raw is None or raw == '':
        return None
    try:
        value = cast(raw)
    except (ValueError, TypeError, OverflowError):
        raise InvalidFilter(f'Invalid {key}') from None
    if isinstance(value, float) and not math.isfinite(value):
        raise InvalidFilter(f'Invalid {key}')
    if value < minimum or (maximum is not None and value > maximum):
        raise InvalidFilter(f'Invalid {key}')
    return value


def filtered_movies(catalog, args):
    """Return matching rows in display order, before pagination. Never mutate the catalog."""
    year_min = _number(args, 'year_min', int, 1000, 9999)
    year_max = _number(args, 'year_max', int, 1000, 9999)
    min_rating = _number(args, 'min_rating', float, 0, 10)
    max_runtime = _number(args, 'max_runtime', int, 1)
    if year_min is not None and year_max is not None and year_min > year_max:
        raise InvalidFilter('The earliest year must not exceed the latest year.')

    sort = args.get('sort') or 'popular'
    if sort not in ('popular', 'rating', 'newest', 'shortest'):
        raise InvalidFilter('Unknown sort order.')

    genre = (args.get('genre') or '').strip()
    mask = pd.Series(True, index=catalog.index)
    if genre:
        mask &= catalog['genres'].str.contains(genre, case=False, regex=False, na=False)

    def numeric(column):
        # Some older caches do not have runtime, rating, or release-date metadata.
        if column not in catalog:
            return pd.Series(index=catalog.index, dtype=float)
        return pd.to_numeric(catalog[column], errors='coerce')

    if year_min is not None or year_max is not None or sort == 'newest':
        dates = (pd.to_datetime(catalog['release_date'], errors='coerce') if 'release_date' in catalog
                 else pd.Series(pd.NaT, index=catalog.index))
        if year_min is not None:
            mask &= dates.dt.year.ge(year_min)
        if year_max is not None:
            mask &= dates.dt.year.le(year_max)
    if min_rating is not None or sort == 'rating':
        ratings = numeric('vote_average')
        if min_rating is not None:
            mask &= ratings.ge(min_rating)
    if max_runtime is not None or sort == 'shortest':
        runtimes = numeric('runtime')
        runtimes = runtimes.where(runtimes.gt(0))
        if max_runtime is not None:
            mask &= runtimes.le(max_runtime)

    if sort == 'newest':
        key = dates
    elif sort == 'rating':
        key = ratings
    elif sort == 'shortest':
        key = runtimes
    else:
        # Match the original ordering (vote count overall, popularity within a genre).
        column = 'popularity' if genre and 'popularity' in catalog else 'vote_count'
        key = numeric(column)
    order = key.loc[mask].sort_values(ascending=sort == 'shortest', kind='stable', na_position='last')
    return catalog.loc[order.index]
