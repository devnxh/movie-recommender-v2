from functools import lru_cache
from urllib.parse import urlencode
import os
import pandas as pd
import numpy as np
from flask import Flask, render_template, request, jsonify, session
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import pickle
from tqdm import tqdm
import time
import threading
import h5py
from scipy.sparse import save_npz, load_npz
import requests
import json
import re

from accounts import current_user_id, favorite_sets, init_accounts
from discovery_filters import InvalidFilter, filtered_movies
from personalization import personalized_ids
from reviews import register_reviews

app = Flask(__name__, template_folder='app/templates', static_folder='app/static')

# Global variables
movies_df = None
tfidf_matrix = None
indices = None

# Per-movie features used to rank recommendations (built by prepare_ranking_features)
quality_scores = None   # 0..1, vote-weighted rating blended with popularity
genre_sets = None       # frozenset of lowercase genres per row
vote_counts = None
titles_lower = None     # lowercase titles for fast search suggestions
catalog_rows_by_id = {}  # current catalog ID -> matrix row, ordered most-voted first

# Recommendation ranking: text similarity finds candidates, then genre overlap and quality re-rank them
REC_CANDIDATE_POOL = 400
REC_MIN_VOTES = 100       # ignore films almost nobody has rated (falls back if too few remain)
REC_WEIGHTS = {'similarity': 0.50, 'genre': 0.30, 'quality': 0.20}
QUALITY_PRIOR_VOTES = 500  # votes needed before a film's own rating outweighs the average

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()

# TMDB API key - read from the environment, never commit it.
# Without it the app still works, just without extra TMDB details (cast, directors, age rating).
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()
if not TMDB_API_KEY:
    print("TMDB_API_KEY is not set; movie details from TMDB are disabled.")
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Check if we're in production (Vercel) or development
IS_PRODUCTION = os.environ.get('VERCEL', False) or os.environ.get('RENDER', False)

def adult_mask(df):
    """True for rows TMDB flags as adult (pornographic) films.

    These are removed everywhere (search, suggestions, browse, recommendations).
    Mainstream R-rated films are not affected; only TMDB's `adult` flag is used.
    """
    if 'adult' not in df.columns:
        return pd.Series(False, index=df.index)
    return df['adult'].astype(str).str.strip().str.lower().eq('true')

def build_title_index(df):
    """Map each title to its row position. For duplicate titles the first (most popular) row wins.

    Requires a 0..n-1 index so labels match tfidf_matrix row positions.
    """
    title_index = pd.Series(df.index, index=df['title'])
    return title_index[~title_index.index.duplicated(keep='first')]

def prepare_ranking_features():
    """Precompute the per-movie numbers used to rank recommendations and suggestions."""
    global quality_scores, genre_sets, vote_counts, titles_lower, catalog_rows_by_id

    votes = movies_df['vote_count'].fillna(0).to_numpy(dtype=float)
    ratings = movies_df['vote_average'].fillna(0).to_numpy(dtype=float)
    rated = votes > 0
    mean_rating = ratings[rated].mean() if rated.any() else 0.0

    # IMDb-style weighted rating: few votes pull a film toward the average
    weighted_rating = (votes / (votes + QUALITY_PRIOR_VOTES)) * ratings \
        + (QUALITY_PRIOR_VOTES / (votes + QUALITY_PRIOR_VOTES)) * mean_rating
    popularity = np.log1p(votes) / max(np.log1p(votes.max()), 1e-9)

    quality_scores = 0.5 * (weighted_rating / 10.0) + 0.5 * popularity
    vote_counts = votes
    genre_sets = [
        frozenset(g.strip().lower() for g in str(genres).split(',') if g.strip())
        for genres in movies_df['genres'].fillna('')
    ]
    titles_lower = movies_df['title'].fillna('').str.lower()

    catalog_rows_by_id = {}
    if 'id' in movies_df:
        ids = movies_df['id'].to_numpy()
        for row in np.argsort(-votes, kind='stable'):
            movie_id = positive_integer(ids[row])
            if movie_id is not None:
                catalog_rows_by_id.setdefault(movie_id, int(row))

# Load data at startup
def load_data():
    """Load the dataset and preprocess it"""
    global movies_df, tfidf_matrix, indices
    
    # In production, use the sample dataset
    dataset_path = 'sample_data/sample_movies.csv' if IS_PRODUCTION else 'TMDB_movie_dataset_v11.csv'
    models_dir = 'sample_data' if IS_PRODUCTION else 'app/models'
    
    # Check if processed data exists
    if os.path.exists(f'{models_dir}/tfidf_matrix.npz') and os.path.exists(f'{models_dir}/movies_df.pkl'):
        try:
            print("Loading preprocessed data...")
            # Load the tfidf matrix as a sparse matrix
            tfidf_matrix = load_npz(f'{models_dir}/tfidf_matrix.npz')
            
            # Load the movies dataframe
            movies_df = pd.read_pickle(f'{models_dir}/movies_df.pkl')

            if tfidf_matrix.shape[0] != len(movies_df):
                raise ValueError("preprocessed movies and TF-IDF matrix have different row counts")

            # Row labels must equal matrix row positions for recommendations to pick the right movie
            movies_df = movies_df.reset_index(drop=True)

            # Older preprocessed files were built before adult films were filtered out
            adult = adult_mask(movies_df)
            if adult.any():
                print(f"Removing {int(adult.sum())} adult titles from preprocessed data...")
                keep = np.flatnonzero(~adult.to_numpy())
                tfidf_matrix = tfidf_matrix[keep]
                movies_df = movies_df.iloc[keep].reset_index(drop=True)
                try:
                    save_npz(f'{models_dir}/tfidf_matrix.npz', tfidf_matrix)
                    movies_df.to_pickle(f'{models_dir}/movies_df.pkl')
                except Exception as save_error:
                    print(f"Could not save filtered data (will filter again next start): {save_error}")

            indices = build_title_index(movies_df)

            print("Data loaded successfully!")
        except Exception as e:
            print(f"Error loading preprocessed data: {e}")
            print("Processing data from scratch...")
            process_data(dataset_path, models_dir)
    else:
        print("Preprocessed data not found. Processing data for the first time...")
        # Process the data
        process_data(dataset_path, models_dir)

    prepare_ranking_features()

def process_data(dataset_path, models_dir):
    """Process the raw data and save it for future use"""
    global movies_df, tfidf_matrix, indices
    
    # Load the dataset
    print(f"Loading dataset from {dataset_path}...")
    movies_df = pd.read_csv(dataset_path)
    
    # Display a loading bar
    total_steps = 5
    pbar = tqdm(total=total_steps, desc="Processing Data")
    
    # Clean the data
    print("Cleaning data...")
    movies_df = movies_df.dropna(subset=['genres', 'keywords', 'overview'])
    adult = adult_mask(movies_df)
    print(f"Removing {int(adult.sum())} adult titles...")
    # reset_index so row labels match TF-IDF matrix row positions
    movies_df = movies_df[~adult].reset_index(drop=True)
    pbar.update(1)
    
    # Create a new feature by combining relevant columns
    print("Creating features...")
    movies_df['combined_features'] = movies_df['genres'] + ' ' + movies_df['keywords'] + ' ' + movies_df['overview']
    pbar.update(1)
    
    # Convert text to TF-IDF features
    print("Creating TF-IDF matrix...")
    tfidf = TfidfVectorizer(stop_words='english', max_features=5000)  # Limit features to reduce memory usage
    tfidf_matrix = tfidf.fit_transform(movies_df['combined_features'])
    pbar.update(1)
    
    # Map titles to row positions
    indices = build_title_index(movies_df)
    pbar.update(1)
    
    # Save the processed data
    print(f"Saving processed data to {models_dir}...")
    if not os.path.exists(models_dir):
        os.makedirs(models_dir)
    
    # Save the tfidf matrix as a sparse matrix
    save_npz(f'{models_dir}/tfidf_matrix.npz', tfidf_matrix)
    
    # Save the movies dataframe
    movies_df.to_pickle(f'{models_dir}/movies_df.pkl')
    
    pbar.update(1)
    pbar.close()
    print("Data processing completed!")

def rank_similar_movies(idx, n):
    """Return row positions of the n best recommendations for the movie at row idx.

    Plain TF-IDF similarity over 200k+ films surfaces obscure titles that merely share a
    word (e.g. "dream" for Inception). So: take the most text-similar candidates among films
    people have actually rated, then re-rank by similarity, genre overlap and quality.
    """
    # Similarity of this movie to every movie (one sparse row vs the matrix: cheap)
    sim = cosine_similarity(tfidf_matrix[idx], tfidf_matrix).ravel()

    # Never recommend the movie itself (or another copy with the same title)
    sim[idx] = -1.0
    sim[(titles_lower == titles_lower.iat[idx]).to_numpy()] = -1.0

    return rank_candidates(sim, genre_sets[idx], n)


def rank_candidates(sim, source_genres, n):
    """Re-rank text matches using the same genre and quality rules across feeds."""
    rated_enough = vote_counts >= REC_MIN_VOTES
    if rated_enough.sum() > n * 3:
        sim = np.where(rated_enough, sim, -1.0)

    pool = min(REC_CANDIDATE_POOL, len(sim) - 1)
    candidates = np.argpartition(-sim, pool)[:pool]
    candidates = candidates[sim[candidates] > 0]
    if len(candidates) == 0:
        return []

    genre_overlap = np.array([
        len(source_genres & genre_sets[c]) / max(1, len(source_genres | genre_sets[c]))
        for c in candidates
    ])
    similarity = sim[candidates] / sim[candidates].max()

    score = (REC_WEIGHTS['similarity'] * similarity
             + REC_WEIGHTS['genre'] * genre_overlap
             + REC_WEIGHTS['quality'] * quality_scores[candidates])
    return candidates[np.argsort(-score)[:n]]

def positive_integer(value):
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


def find_catalog_movie(movie_id=None, title=None):
    """Look up a specific edition by TMDB ID, or an older saved item by title."""
    movie_id = positive_integer(movie_id)
    if movie_id in catalog_rows_by_id:
        return movies_df.iloc[[catalog_rows_by_id[movie_id]]]
    if isinstance(title, str) and title in indices:
        return movies_df.iloc[[indices[title]]]
    return movies_df.iloc[:0]


def catalog_movies(rows, enrich=False):
    """Serialize just the displayed rows, including null-safe local card metadata."""
    fields = ['id', 'title', 'release_date', 'runtime', 'vote_average', 'genres', 'poster_path', 'overview']
    # Older caches may lack optional columns. Flask's JSON must contain null, never NaN.
    data = rows.reindex(columns=fields).replace([np.inf, -np.inf], np.nan)
    records = data.astype(object).where(data.notna(), None).to_dict(orient='records')
    for movie in records:
        movie['id'] = positive_integer(movie['id'])
        movie['year'] = positive_integer(str(movie.pop('release_date') or '')[:4])
        movie['runtime'] = positive_integer(movie['runtime'])
        poster = movie['poster_path']
        if poster and not poster.startswith(('http://', 'https://')):
            poster = f"{TMDB_IMAGE_BASE_URL}/{poster.lstrip('/')}"
        details = get_movie_details_from_tmdb(movie['title'], movie['id']) if enrich else {}
        movie['poster_path'] = poster or details.get('poster_path')
        if enrich and not movie['poster_path']:
            movie['poster_path'] = "https://fakeimg.pl/300x450/333333/ffffff?text=No+Poster"
        movie['cast'] = details.get('cast', [])
        movie['directors'] = details.get('directors', [])
        movie['age_rating'] = details.get('age_rating', 'Not Rated')
    return records


def get_recommendations(title, n=10, enrich=True, movie_id=None):
    """Get movie recommendations based on similarity"""
    global tfidf_matrix, movies_df, indices
    
    # Check if data is loaded
    if tfidf_matrix is None or movies_df is None or indices is None:
        return []
    
    if movie_id:
        selected = find_catalog_movie(movie_id)
        if selected.empty:
            return []
        idx = selected.index[0]
    elif not title:
        return []
    elif title in indices:
        idx = indices[title]
    else:
        # Try to find a close match if exact title not found
        close_matches = movies_df[movies_df['title'].str.contains(title, case=False, regex=False, na=False)]
        if len(close_matches) > 0:
            # Use the most-voted close match
            close_matches = close_matches.sort_values('vote_count', ascending=False)
            match_title = close_matches.iloc[0]['title']
            print(f"Using '{match_title}' instead of '{title}'")
            idx = indices[match_title]
        else:
            print(f"No match found for '{title}'")
            return []
    
    try:
        # Convert idx to integer if it's not already
        if not isinstance(idx, (int, np.integer)):
            idx = int(idx)
            
        sim_indices = rank_similar_movies(idx, n)

        # Check if we have valid indices
        if len(sim_indices) == 0:
            return []
        
        return catalog_movies(movies_df.iloc[sim_indices], enrich=enrich)
    except Exception as e:
        print(f"Error getting recommendations for '{title}': {e}")
        return []

def get_movie_trailer(title, movie_id=None):
    """Prefer the distributor's trailer for this edition, then fall back to search."""
    query = f"{title} official trailer"
    trailer = {
        'title': query, 'video_id': None,
        'search_url': 'https://www.youtube.com/results?' + urlencode({'search_query': query}),
    }
    details = get_movie_details_from_tmdb(title, movie_id)
    video = details.get('trailer')
    if not video and YOUTUBE_API_KEY:
        try:
            response = requests.get(
                'https://www.googleapis.com/youtube/v3/search',
                params={'part': 'snippet', 'q': query, 'type': 'video', 'key': YOUTUBE_API_KEY, 'maxResults': 1},
                timeout=2.5,
            )
            response.raise_for_status()
            items = response.json().get('items', [])
            if items:
                video_id = items[0].get('id', {}).get('videoId', '')
                if re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
                    video = {'video_id': video_id, 'title': items[0].get('snippet', {}).get('title') or query}
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            pass
    if video:
        trailer.update(video)
        trailer['embed_url'] = 'https://www.youtube.com/embed/' + video['video_id']
    return trailer


def extract_genres_from_movies():
    """Extract all unique genres from the movies dataframe"""
    global movies_df
    
    if movies_df is None:
        return []
    
    # Get all genres from the dataframe
    all_genres = set()
    for genres_str in movies_df['genres'].dropna():
        # Split by common separators and clean up
        genres = re.split(r'[,|]', str(genres_str))
        for genre in genres:
            cleaned = genre.strip()
            if cleaned:
                all_genres.add(cleaned)

    # Icons used by the genre filter in index.html (genre.name / genre.icon)
    genre_icons = {
        'Action': 'fa-explosion',
        'Adventure': 'fa-compass',
        'Animation': 'fa-child',
        'Comedy': 'fa-face-laugh',
        'Crime': 'fa-handcuffs',
        'Documentary': 'fa-video',
        'Drama': 'fa-masks-theater',
        'Family': 'fa-users',
        'Fantasy': 'fa-wand-magic',
        'History': 'fa-landmark',
        'Horror': 'fa-ghost',
        'Music': 'fa-music',
        'Mystery': 'fa-magnifying-glass',
        'Romance': 'fa-heart',
        'Science Fiction': 'fa-rocket',
        'TV Movie': 'fa-tv',
        'Thriller': 'fa-skull',
        'War': 'fa-gun',
        'Western': 'fa-hat-cowboy'
    }

    return [
        {'name': genre, 'icon': genre_icons.get(genre, 'fa-film')}
        for genre in sorted(all_genres)
    ]

@app.route('/')
def index():
    """Render the main page"""
    # Get all unique genres for the filter
    genres = extract_genres_from_movies()
    return render_template('index.html', genres=genres)

def ranked_title_matches(query):
    """Use the same title ranking for the search box and the selected results."""
    q = query.strip().lower()
    positions = np.flatnonzero(titles_lower.str.contains(q, regex=False).to_numpy())
    matched = titles_lower.iloc[positions]
    exact = matched.eq(q).to_numpy()
    prefix = matched.str.startswith(q).to_numpy()
    order = np.lexsort((-vote_counts[positions], ~prefix, ~exact))
    return positions[order]


@app.route('/search', methods=['POST'])
def search():
    """Search for movies by title"""
    data = request.get_json()
    query = data.get('query', '')
    if not isinstance(query, str) or not query.strip():
        return jsonify([])
    page = positive_integer(data.get('page', 1))
    if page is None:
        return jsonify({'error': 'Page must be a positive integer'}), 400
    start = (page - 1) * 12
    positions = ranked_title_matches(query)[start:start + 12]
    return jsonify(catalog_movies(movies_df.iloc[positions], enrich=request.args.get('view') != 'card'))

@app.route('/search_suggestions', methods=['POST'])
def search_suggestions():
    """Get search suggestions as user types"""
    global movies_df
    
    # Make sure data is loaded
    if movies_df is None:
        load_data()
        
    query = request.form.get('query', '').strip()
    if len(query) < 2:
        return jsonify([])
    suggestions = movies_df['title'].iloc[ranked_title_matches(query)].drop_duplicates().head(5).tolist()
    return jsonify(suggestions)

def similar_favorite_ids(favorites, limit):
    rows = [catalog_rows_by_id[movie_id] for movie_id in sorted(favorites)]
    profile = np.asarray(tfidf_matrix[rows].sum(axis=0))
    similarity = cosine_similarity(profile, tfidf_matrix).ravel()
    similarity[rows] = -1
    genres = set().union(*(genre_sets[row] for row in rows))
    candidates = rank_candidates(similarity, genres, limit)
    return movies_df['id'].iloc[candidates].tolist()


@app.get('/api/for-you')
def for_you():
    member_id = current_user_id()
    favorites = favorite_sets(member_id) if member_id is not None else {}
    movie_ids, basis = personalized_ids(member_id, favorites, catalog_rows_by_id, similar_favorite_ids)
    rows = movies_df.iloc[[catalog_rows_by_id[movie_id] for movie_id in movie_ids]]
    if not catalog_rows_by_id:
        # Old preprocessed catalogs may not have TMDB IDs.
        rows = movies_df.nlargest(12, 'vote_count')
    response = jsonify(movies=catalog_movies(rows), basis=basis)
    response.cache_control.no_store = True
    response.vary.add('Cookie')
    return response


@app.route('/recommend', methods=['POST'])
def recommend():
    """Get movie recommendations"""
    global movies_df, tfidf_matrix, indices
    
    # Make sure data is loaded
    if movies_df is None or tfidf_matrix is None or indices is None:
        load_data()
        
    title = request.form.get('title', '')
    
    # Get recommendations
    recommendations = get_recommendations(title, enrich=request.args.get('view') != 'card', movie_id=request.form.get('id'))
    
    return jsonify(recommendations)

@app.route('/movies')
def movies():
    """Browse a filtered catalog page, using the same sort order on every page."""
    page = positive_integer(request.args.get('page', 1))
    if page is None:
        return jsonify({'error': 'Page must be a positive integer'}), 400
    try:
        matches = filtered_movies(movies_df, request.args)
        start = (page - 1) * 12
        return jsonify(catalog_movies(matches.iloc[start:start + 12], enrich=request.args.get('view') != 'card'))
    except InvalidFilter as error:
        return jsonify({'error': str(error)}), 400
    except Exception:
        app.logger.exception("Could not load catalog page")
        return jsonify({'error': 'Catalog temporarily unavailable'}), 503

@app.get('/api/surprise')
def surprise_movie():
    """Draw a matching film, favoring well-reviewed titles over barely rated entries."""
    try:
        matches = filtered_movies(movies_df, request.args)
    except InvalidFilter as exc:
        return jsonify({'error': str(exc)}), 400
    recent = request.args.get('recent', '').split(',')[-24:]
    recent_ids = [int(value) for value in recent if value.isascii() and value.isdigit() and len(value) < 13]
    # With old caches lacking IDs a pick is still possible, without recent-pick tracking.
    ids = pd.to_numeric(matches['id'], errors='coerce') if 'id' in matches else None
    eligible = matches.loc[~ids.isin(recent_ids)] if ids is not None else matches
    restarted = eligible.empty and not matches.empty
    if restarted:
        eligible = matches
        if len(matches) > 1 and recent_ids and ids is not None:
            other = matches.loc[ids != recent_ids[-1]]
            if not other.empty:
                eligible = other
    movie = None
    has_alternative = False
    if not eligible.empty:
        votes = vote_counts[eligible.index]
        quality = quality_scores[eligible.index]
        weights = 0.05 + np.log1p(np.maximum(0, votes)) ** 2 * np.maximum(0, quality)
        pick = eligible.sample(n=1, weights=weights)
        movie = catalog_movies(pick)[0]
        same_film = ids.eq(movie['id']) if movie['id'] else matches['title'].eq(movie['title'])
        has_alternative = not bool(same_film.all())
    response = jsonify(movie=movie, restarted=restarted, has_alternative=has_alternative)
    response.cache_control.no_store = True
    return response


@app.route('/default_movies')
def default_movies():
    """Get a list of default movies to display"""
    try:
        # Get top movies by vote count
        top_movies = movies_df.sort_values('vote_count', ascending=False).head(12)
        
        return jsonify(catalog_movies(top_movies, enrich=request.args.get('view') != 'card'))
    except Exception:
        app.logger.exception("Could not load popular films")
        return jsonify({'error': 'Catalog temporarily unavailable'}), 503

@app.get('/movie_details')
def movie_details():
    rows = find_catalog_movie(request.args.get('id'), request.args.get('title'))
    if rows.empty:
        return jsonify({'error': 'Movie not found'}), 404
    movie = catalog_movies(rows)[0]
    details = get_movie_details_from_tmdb(movie['title'], movie['id'])
    movie.update({key: value for key, value in details.items() if value is not None})
    movie['tmdb_status'] = 'updated' if details else 'catalog'
    return jsonify(movie)

@app.route('/get_trailer', methods=['POST'])
def get_trailer():
    """Get a movie trailer"""
    title = request.form.get('title', '')
    
    if not title:
        return jsonify({"error": "No title provided"}), 400
    
    trailer_info = get_movie_trailer(title, positive_integer(request.form.get('id')))
    
    if trailer_info:
        return jsonify(trailer_info)
    else:
        return jsonify({"error": "Trailer not found"}), 404

def compact_saved_movie(movie):
    """Keep catalog references in the cookie, retaining metadata unavailable locally."""
    rows = find_catalog_movie(movie.get('id'), None if movie.get('id') else movie['title'])
    if rows.empty:
        return {key: movie.get(key) for key in (
            'id', 'title', 'year', 'runtime', 'vote_average', 'genres', 'poster_path', 'overview',
        )} | {
            'cast': movie.get('cast', []), 'directors': movie.get('directors', []),
            'age_rating': movie.get('age_rating', 'Not Rated'),
        }
    local = catalog_movies(rows)[0]
    saved = {'id': local['id'], 'title': local['title']}
    for field in ('cast', 'directors', 'age_rating'):
        if movie.get(field) and movie[field] != local[field]:
            saved[field] = movie[field]
    return saved


def read_saved_movie(saved):
    # Older cookies contain a full movie. Old or removed titles can still be opened.
    rows = find_catalog_movie(saved.get('id'), None if saved.get('id') else saved.get('title'))
    if rows.empty:
        return saved
    return {**catalog_movies(rows)[0], **saved}


def same_saved_movie(saved, target):
    if saved.get('id') and target.get('id'):
        return saved['id'] == target['id']
    return saved.get('title') == target.get('title')


@app.route('/watchlist', methods=['GET', 'POST', 'DELETE'])
def watchlist():
    saved = session.get('watchlist', [])
    if request.method == 'GET':
        return jsonify([read_saved_movie(movie) for movie in saved])

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Movie data is required'}), 400

    if request.method == 'DELETE' and data.get('clear') is True:
        session.pop('watchlist', None)
        return jsonify({'message': 'Watchlist cleared'})

    movie = data.get('movie') if request.method == 'POST' else data
    if not isinstance(movie, dict) or not isinstance(movie.get('title'), str) or not movie['title'].strip():
        return jsonify({'error': 'Movie title is required'}), 400
    if request.method == 'DELETE':
        for index, entry in enumerate(saved):
            if same_saved_movie(entry, movie):
                session['watchlist'] = saved[:index] + saved[index + 1:]
                return jsonify({'message': 'Movie removed from watchlist'})
        return jsonify({'error': 'Movie not found in watchlist'}), 404

    if any(same_saved_movie(entry, movie) for entry in saved):
        return jsonify({'message': 'Movie already in watchlist'})
    # Compact full records from older sessions on the next addition.
    updated = [compact_saved_movie(entry) if 'overview' in entry else entry for entry in saved]
    updated.append(compact_saved_movie(movie))
    # Flask stores the list in a signed browser cookie. Reject an oversize update
    # before the browser can silently discard it and lose the existing list.
    serializer = app.session_interface.get_signing_serializer(app)
    payload = serializer.dumps({**session, 'watchlist': updated})
    cookie_bytes = len(app.config['SESSION_COOKIE_NAME']) + len(payload) + len('=; HttpOnly; Path=/')
    if cookie_bytes > app.config['MAX_COOKIE_SIZE']:
        return jsonify({'error': 'Your watchlist is full. Remove a film before adding another.'}), 409

    session['watchlist'] = updated
    return jsonify({'message': 'Movie added to watchlist'}), 201


@app.route('/genres')
def genres():
    """Get all unique genres for filtering"""
    genres = extract_genres_from_movies()
    return jsonify(genres)

@app.route('/health')
def health():
    """Lightweight endpoint for uptime checks and the keep-alive ping."""
    return jsonify({"status": "ok", "movies": 0 if movies_df is None else len(movies_df)})

def start_keep_alive():
    """Keep a Render free instance awake by pinging its own public URL.

    Render stops free web services after 15 minutes without inbound traffic.
    RENDER_EXTERNAL_URL is set by Render automatically, so this only runs there.
    Set KEEP_ALIVE=0 to turn it off, or KEEP_ALIVE_INTERVAL (seconds) to change the interval.
    """
    base_url = os.environ.get('RENDER_EXTERNAL_URL', '').rstrip('/')
    if not base_url or os.environ.get('KEEP_ALIVE', '1') == '0':
        return

    try:
        interval = max(60, int(os.environ.get('KEEP_ALIVE_INTERVAL', '600')))  # default 10 minutes
    except ValueError:
        interval = 600

    def ping_forever():
        while True:
            time.sleep(interval)
            try:
                requests.get(f"{base_url}/health", timeout=30)
            except Exception as e:
                print(f"Keep-alive ping failed: {e}")

    threading.Thread(target=ping_forever, name='keep-alive', daemon=True).start()
    print(f"Keep-alive: pinging {base_url}/health every {interval}s")

def get_movie_details_from_tmdb(movie_title, movie_id=None):
    if not TMDB_API_KEY:
        return {}
    try:
        if movie_id is None:
            # Compatibility with old caches that only contain the title.
            response = requests.get(
                "https://api.themoviedb.org/3/search/movie",
                params={"api_key": TMDB_API_KEY, "query": movie_title},
                timeout=2.5,
            )
            response.raise_for_status()
            matches = response.json().get('results', [])
            if not matches:
                return {}
            movie_id = matches[0]['id']
        return fetch_tmdb_details(movie_id, int(time.monotonic() // 900))
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        # The local catalog remains usable when TMDB is unavailable.
        return {}


@lru_cache(maxsize=512)
def fetch_tmdb_details(movie_id, cache_window):
    """Refresh selected-film data each 15-minute window. Failures remain retryable."""
    response = requests.get(
        f"https://api.themoviedb.org/3/movie/{movie_id}",
        params={"api_key": TMDB_API_KEY, "append_to_response": "credits,release_dates,videos,reviews"},
        timeout=2.5,
    )
    response.raise_for_status()
    data = response.json()
    credits = data.get('credits') or {}
    countries = data.get('release_dates', {}).get('results', [])
    us_releases = next((country['release_dates'] for country in countries if country['iso_3166_1'] == 'US'), [])
    trailers = [
        video for video in data.get('videos', {}).get('results', [])
        if video.get('site') == 'YouTube' and video.get('type') == 'Trailer'
        and re.fullmatch(r'[A-Za-z0-9_-]{11}', video.get('key') or '')
    ]
    trailer = max(trailers, key=lambda video: (bool(video.get('official')), video.get('published_at') or ''), default=None)
    reviews = []
    for item in data.get('reviews', {}).get('results', []):
        content = (item.get('content') or '').strip()
        if not content:
            continue
        review_id = item.get('id') or ''
        reviews.append({
            'author': item.get('author') or 'TMDB member',
            'excerpt': content[:360].rstrip() + ('…' if len(content) > 360 else ''),
            'url': 'https://www.themoviedb.org/review/' + review_id if re.fullmatch(r'[a-zA-Z0-9]+', review_id)
                   else f'https://www.themoviedb.org/movie/{movie_id}/reviews',
        })
        if len(reviews) == 3:
            break
    genres = ', '.join(genre['name'] for genre in data.get('genres', []) if genre.get('name'))
    votes = data.get('vote_count')
    return {
        'vote_average': data.get('vote_average') if votes else None,
        'vote_count': votes,
        'year': positive_integer((data.get('release_date') or '')[:4]),
        'runtime': positive_integer(data.get('runtime')),
        'genres': genres or None,
        'overview': data.get('overview') or None,
        'trailer': {'title': trailer.get('name') or 'Trailer', 'video_id': trailer['key']} if trailer else None,
        'tmdb_reviews': reviews,
        'cast': [actor['name'] for actor in credits.get('cast', [])[:5]],
        'directors': [person['name'] for person in credits.get('crew', []) if person['job'] == 'Director'],
        'age_rating': next((release['certification'] for release in us_releases if release.get('certification')), 'Not Rated'),
        'poster_path': f"{TMDB_IMAGE_BASE_URL}{data['poster_path']}" if data.get('poster_path') else None,
    }


def favorite_cards(movie_ids):
    positions = [catalog_rows_by_id[movie_id] for movie_id in movie_ids if movie_id in catalog_rows_by_id]
    return catalog_movies(movies_df.iloc[positions]) if positions else []


init_accounts(app, favorite_cards)
register_reviews(app, find_catalog_movie)

# Load data at startup for faster first request
load_data()
start_keep_alive()

# For local development
if __name__ == '__main__':
    # Run the app
    app.run(debug=True)
