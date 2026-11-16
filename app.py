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

app = Flask(__name__, template_folder='app/templates', static_folder='app/static')
app.secret_key = 'cinewatch_secret_key'  # For session management

# Global variables
movies_df = None
tfidf_matrix = None
indices = None

# Per-movie features used to rank recommendations (built by prepare_ranking_features)
quality_scores = None   # 0..1, vote-weighted rating blended with popularity
genre_sets = None       # frozenset of lowercase genres per row
vote_counts = None
titles_lower = None     # lowercase titles for fast search suggestions
hero_poster_urls = []   # small posters of the most-voted films, for the hero film strips

# Recommendation ranking: text similarity finds candidates, then genre overlap and quality re-rank them
REC_CANDIDATE_POOL = 400
REC_MIN_VOTES = 100       # ignore films almost nobody has rated (falls back if too few remain)
REC_WEIGHTS = {'similarity': 0.50, 'genre': 0.30, 'quality': 0.20}
QUALITY_PRIOR_VOTES = 500  # votes needed before a film's own rating outweighs the average

# YouTube API key - in a real app, this would be stored securely
YOUTUBE_API_KEY = "YOUR_YOUTUBE_API_KEY"  # Replace with your actual API key if available

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
    global quality_scores, genre_sets, vote_counts, titles_lower

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

def prepare_hero_posters(limit=24):
    """Poster URLs (small TMDB size) of the most-voted films, shown on the hero film strips."""
    global hero_poster_urls

    with_posters = movies_df[movies_df['poster_path'].notna()]
    top = with_posters.sort_values('vote_count', ascending=False).head(limit)
    urls = []
    for path in top['poster_path'].astype(str):
        if path.startswith(('http://', 'https://')):
            urls.append(path)
        elif path.startswith('/'):
            urls.append(f"https://image.tmdb.org/t/p/w185{path}")
    hero_poster_urls = urls

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
    prepare_hero_posters()

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

    rated_enough = vote_counts >= REC_MIN_VOTES
    if rated_enough.sum() > n * 3:
        sim = np.where(rated_enough, sim, -1.0)

    pool = min(REC_CANDIDATE_POOL, len(sim) - 1)
    candidates = np.argpartition(-sim, pool)[:pool]
    candidates = candidates[sim[candidates] > 0]
    if len(candidates) == 0:
        return []

    source_genres = genre_sets[idx]
    genre_overlap = np.array([
        len(source_genres & genre_sets[c]) / max(1, len(source_genres | genre_sets[c]))
        for c in candidates
    ])
    similarity = sim[candidates] / sim[candidates].max()

    score = (REC_WEIGHTS['similarity'] * similarity
             + REC_WEIGHTS['genre'] * genre_overlap
             + REC_WEIGHTS['quality'] * quality_scores[candidates])
    return candidates[np.argsort(-score)[:n]]

def get_recommendations(title, n=10):
    """Get movie recommendations based on similarity"""
    global tfidf_matrix, movies_df, indices
    
    # Check if data is loaded
    if tfidf_matrix is None or movies_df is None or indices is None:
        return []
    
    # Handle exact match first
    if title in indices:
        idx = indices[title]
    else:
        # Try to find a close match if exact title not found
        close_matches = movies_df[movies_df['title'].str.contains(title, case=False, regex=False)]
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
        
        # Return the top n most similar movies
        result = movies_df.iloc[sim_indices][['title', 'vote_average', 'genres', 'poster_path', 'overview']].to_dict(orient='records')
        
        # Enhance movies with TMDB details
        enhanced_result = []
        for movie in result:
            # Fix poster path if it's just a relative path
            if movie['poster_path'] and isinstance(movie['poster_path'], str) and not movie['poster_path'].startswith(('http://', 'https://')):
                movie['poster_path'] = f"{TMDB_IMAGE_BASE_URL}{movie['poster_path']}"
            
            # Try to get additional details from TMDB
            tmdb_details = get_movie_details_from_tmdb(movie['title'])
            if tmdb_details:
                if not movie['poster_path']:
                    movie['poster_path'] = tmdb_details['poster_path'] or "https://fakeimg.pl/300x450/333333/ffffff?text=No+Poster"
                movie['cast'] = tmdb_details['cast']
                movie['directors'] = tmdb_details['directors']
                movie['age_rating'] = tmdb_details['age_rating']
            else:
                if not movie['poster_path']:
                    movie['poster_path'] = "https://fakeimg.pl/300x450/333333/ffffff?text=No+Poster"
                movie['cast'] = []
                movie['directors'] = []
                movie['age_rating'] = "Not Rated"
            
            enhanced_result.append(movie)
            
        # If no results, return empty list
        if len(enhanced_result) == 0:
            print(f"No recommendations found for '{title}'")
            return []
            
        return enhanced_result
    except Exception as e:
        print(f"Error getting recommendations for '{title}': {e}")
        return []

def get_movie_trailer(title):
    """Get a movie trailer from YouTube"""
    try:
        # Clean the title for search
        search_query = f"{title} official trailer"
        
        # If YouTube API key is not available, return a dummy URL
        if YOUTUBE_API_KEY == "YOUR_YOUTUBE_API_KEY":
            # Return a fallback method using a search URL
            return {
                "title": f"{title} - Official Trailer",
                "video_id": None,
                "search_url": f"https://www.youtube.com/results?search_query={search_query.replace(' ', '+')}"
            }
        
        # Make a request to the YouTube API
        url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={search_query}&type=video&key={YOUTUBE_API_KEY}&maxResults=1"
        response = requests.get(url)
        data = response.json()
        
        if 'items' in data and len(data['items']) > 0:
            video_id = data['items'][0]['id']['videoId']
            video_title = data['items'][0]['snippet']['title']
            return {
                "title": video_title,
                "video_id": video_id,
                "embed_url": f"https://www.youtube.com/embed/{video_id}"
            }
        else:
            # Fallback to a search URL
            return {
                "title": f"{title} - Official Trailer",
                "video_id": None,
                "search_url": f"https://www.youtube.com/results?search_query={search_query.replace(' ', '+')}"
            }
    except Exception as e:
        print(f"Error getting trailer for '{title}': {e}")
        # Return a fallback URL in case of error
        search_query = f"{title} official trailer"
        return {
            "title": f"{title} - Official Trailer",
            "video_id": None,
            "search_url": f"https://www.youtube.com/results?search_query={search_query.replace(' ', '+')}"
        }

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
    # Two film strips for the hero, each from a different half of the top posters
    half = len(hero_poster_urls) // 2
    film_strips = [s for s in (hero_poster_urls[:half], hero_poster_urls[half:]) if s]
    return render_template('index.html', genres=genres, film_strips=film_strips)

@app.route('/search', methods=['POST'])
def search():
    """Search for movies by title"""
    data = request.get_json()
    query = data.get('query', '')
    page = data.get('page', 1)
    
    if not query:
        return jsonify([])
    
    # Find movies that match the query
    matches = movies_df[movies_df['title'].str.contains(query, case=False, regex=False)]
    
    if len(matches) == 0:
        return jsonify([])
    
    # Get the top matches, paginated
    items_per_page = 12
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    
    # Sort by vote count and get the slice for the current page
    top_matches = matches.sort_values('vote_count', ascending=False).iloc[start_idx:end_idx]
    
    # Convert to list of dictionaries
    results = top_matches[['title', 'vote_average', 'genres', 'poster_path', 'overview']].to_dict(orient='records')
    
    # Enhance with TMDB details
    enhanced_results = []
    for movie in results:
        # Fix poster path if it's just a relative path
        if movie['poster_path'] and isinstance(movie['poster_path'], str) and not movie['poster_path'].startswith(('http://', 'https://')):
            movie['poster_path'] = f"{TMDB_IMAGE_BASE_URL}{movie['poster_path']}"
        
        # Try to get additional details from TMDB
        tmdb_details = get_movie_details_from_tmdb(movie['title'])
        if tmdb_details:
            if not movie['poster_path']:
                movie['poster_path'] = tmdb_details['poster_path'] or "https://fakeimg.pl/300x450/333333/ffffff?text=No+Poster"
            movie['cast'] = tmdb_details['cast']
            movie['directors'] = tmdb_details['directors']
            movie['age_rating'] = tmdb_details['age_rating']
        else:
            if not movie['poster_path']:
                movie['poster_path'] = "https://fakeimg.pl/300x450/333333/ffffff?text=No+Poster"
            movie['cast'] = []
            movie['directors'] = []
            movie['age_rating'] = "Not Rated"
        
        enhanced_results.append(movie)
    
    return jsonify(enhanced_results)

@app.route('/search_suggestions', methods=['POST'])
def search_suggestions():
    """Get search suggestions as user types"""
    global movies_df
    
    # Make sure data is loaded
    if movies_df is None:
        load_data()
        
    query = request.form.get('query', '')
    
    if not query or len(query) < 2:
        return jsonify([])
    
    # Titles containing the search term: ones that start with it first, then the most-voted
    q = query.strip().lower()
    contains = titles_lower.str.contains(q, regex=False).to_numpy()
    matches = np.flatnonzero(contains)
    if len(matches) == 0:
        return jsonify([])
    starts = titles_lower.iloc[matches].str.startswith(q).to_numpy()
    order = np.lexsort((-vote_counts[matches], ~starts))
    suggestions = movies_df['title'].iloc[matches[order]].drop_duplicates().head(5).tolist()
    return jsonify(suggestions)

@app.route('/recommend', methods=['POST'])
def recommend():
    """Get movie recommendations"""
    global movies_df, tfidf_matrix, indices
    
    # Make sure data is loaded
    if movies_df is None or tfidf_matrix is None or indices is None:
        load_data()
        
    title = request.form.get('title', '')
    
    # Get recommendations
    recommendations = get_recommendations(title)
    
    return jsonify(recommendations)

@app.route('/movies')
def movies():
    """Get a list of movies, optionally filtered by genre"""
    try:
        genre = request.args.get('genre', None)
        page = int(request.args.get('page', 1))
        items_per_page = 12
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        
        if genre:
            # Filter by genre
            filtered_movies = movies_df[movies_df['genres'].str.contains(genre, case=False, regex=False)]
            # Sort by popularity or vote count
            if 'popularity' in filtered_movies.columns:
                filtered_movies = filtered_movies.sort_values('popularity', ascending=False)
            else:
                filtered_movies = filtered_movies.sort_values('vote_count', ascending=False)
            # Get paginated movies
            paginated_movies = filtered_movies.iloc[start_idx:end_idx]
        else:
            # Get top movies by vote count, paginated
            paginated_movies = movies_df.sort_values('vote_count', ascending=False).iloc[start_idx:end_idx]
        
        # Convert to list of dictionaries
        results = paginated_movies[['title', 'vote_average', 'genres', 'poster_path', 'overview']].to_dict(orient='records')
        
        # Enhance with TMDB details
        enhanced_results = []
        for movie in results:
            # Fix poster path if it's just a relative path
            if movie['poster_path'] and isinstance(movie['poster_path'], str) and not movie['poster_path'].startswith(('http://', 'https://')):
                movie['poster_path'] = f"{TMDB_IMAGE_BASE_URL}{movie['poster_path']}"
            
            # Try to get additional details from TMDB
            tmdb_details = get_movie_details_from_tmdb(movie['title'])
            if tmdb_details:
                if not movie['poster_path']:
                    movie['poster_path'] = tmdb_details['poster_path'] or "https://fakeimg.pl/300x450/333333/ffffff?text=No+Poster"
                movie['cast'] = tmdb_details['cast']
                movie['directors'] = tmdb_details['directors']
                movie['age_rating'] = tmdb_details['age_rating']
            else:
                if not movie['poster_path']:
                    movie['poster_path'] = "https://fakeimg.pl/300x450/333333/ffffff?text=No+Poster"
                movie['cast'] = []
                movie['directors'] = []
                movie['age_rating'] = "Not Rated"
            
            enhanced_results.append(movie)
        
        return jsonify(enhanced_results)
    except Exception as e:
        print(f"Error getting movies: {e}")
        return jsonify([])

@app.route('/default_movies')
def default_movies():
    """Get a list of default movies to display"""
    try:
        # Get top movies by vote count
        top_movies = movies_df.sort_values('vote_count', ascending=False).head(12)
        
        # Convert to list of dictionaries
        results = top_movies[['title', 'vote_average', 'genres', 'poster_path', 'overview']].to_dict(orient='records')
        
        # Enhance with TMDB details
        enhanced_results = []
        for movie in results:
            # Fix poster path if it's just a relative path
            if movie['poster_path'] and isinstance(movie['poster_path'], str) and not movie['poster_path'].startswith(('http://', 'https://')):
                movie['poster_path'] = f"{TMDB_IMAGE_BASE_URL}{movie['poster_path']}"
            
            # Try to get additional details from TMDB
            tmdb_details = get_movie_details_from_tmdb(movie['title'])
            if tmdb_details:
                if not movie['poster_path']:
                    movie['poster_path'] = tmdb_details['poster_path'] or "https://fakeimg.pl/300x450/333333/ffffff?text=No+Poster"
                movie['cast'] = tmdb_details['cast']
                movie['directors'] = tmdb_details['directors']
                movie['age_rating'] = tmdb_details['age_rating']
            else:
                if not movie['poster_path']:
                    movie['poster_path'] = "https://fakeimg.pl/300x450/333333/ffffff?text=No+Poster"
                movie['cast'] = []
                movie['directors'] = []
                movie['age_rating'] = "Not Rated"
            
            enhanced_results.append(movie)
        
        return jsonify(enhanced_results)
    except Exception as e:
        print(f"Error getting default movies: {e}")
        return jsonify([])

@app.route('/get_trailer', methods=['POST'])
def get_trailer():
    """Get a movie trailer"""
    title = request.form.get('title', '')
    
    if not title:
        return jsonify({"error": "No title provided"}), 400
    
    trailer_info = get_movie_trailer(title)
    
    if trailer_info:
        return jsonify(trailer_info)
    else:
        return jsonify({"error": "Trailer not found"}), 404

@app.route('/watchlist', methods=['GET', 'POST', 'DELETE'])
def watchlist():
    """Handle watchlist operations"""
    # Initialize watchlist in session if it doesn't exist
    if 'watchlist' not in session:
        session['watchlist'] = []
    
    if request.method == 'GET':
        # Return the watchlist
        return jsonify(session['watchlist'])
    
    elif request.method == 'POST':
        # Add a movie to the watchlist
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        # Extract movie from the request
        movie = data.get('movie', {})
        
        if not movie or 'title' not in movie:
            return jsonify({"error": "Invalid movie data"}), 400
        
        # Check if movie is already in watchlist
        for existing_movie in session['watchlist']:
            if existing_movie.get('title') == movie.get('title'):
                return jsonify({"message": "Movie already in watchlist"}), 200
        
        # Add movie to watchlist with enhanced details
        watchlist_movie = {
            'title': movie.get('title'),
            'vote_average': movie.get('vote_average'),
            'genres': movie.get('genres'),
            'poster_path': movie.get('poster_path'),
            'overview': movie.get('overview'),
            'cast': movie.get('cast', []),
            'directors': movie.get('directors', []),
            'age_rating': movie.get('age_rating', 'Not Rated')
        }
        
        session['watchlist'].append(watchlist_movie)
        session.modified = True
        
        return jsonify({"message": "Movie added to watchlist"}), 201
    
    elif request.method == 'DELETE':
        # Remove a movie from the watchlist
        data = request.get_json()
        
        if not data or 'title' not in data:
            return jsonify({"error": "No title provided"}), 400
        
        title = data['title']
        
        # Find and remove the movie
        for i, movie in enumerate(session['watchlist']):
            if movie.get('title') == title:
                session['watchlist'].pop(i)
                session.modified = True
                return jsonify({"message": "Movie removed from watchlist"}), 200
        
        return jsonify({"error": "Movie not found in watchlist"}), 404

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

def get_movie_details_from_tmdb(movie_title):
    """Fetch detailed movie information from TMDB API"""
    if not TMDB_API_KEY:
        return None

    try:
        # Search for the movie
        search_url = "https://api.themoviedb.org/3/search/movie"
        response = requests.get(search_url, params={"api_key": TMDB_API_KEY, "query": movie_title}, timeout=10)
        data = response.json()
        
        if 'results' in data and len(data['results']) > 0:
            movie_id = data['results'][0]['id']
            
            # Get detailed movie information
            details_url = f"https://api.themoviedb.org/3/movie/{movie_id}"
            details_response = requests.get(
                details_url,
                params={"api_key": TMDB_API_KEY, "append_to_response": "credits,release_dates"},
                timeout=10,
            )
            details_data = details_response.json()
            
            # Extract cast (top 5)
            cast = []
            if 'credits' in details_data and 'cast' in details_data['credits']:
                cast = [actor['name'] for actor in details_data['credits']['cast'][:5]]
            
            # Extract directors
            directors = []
            if 'credits' in details_data and 'crew' in details_data['credits']:
                directors = [crew['name'] for crew in details_data['credits']['crew'] if crew['job'] == 'Director']
            
            # Extract age rating (US certification)
            age_rating = "Not Rated"
            if 'release_dates' in details_data and 'results' in details_data['release_dates']:
                for country in details_data['release_dates']['results']:
                    if country['iso_3166_1'] == 'US':
                        for release in country['release_dates']:
                            if release['certification']:
                                age_rating = release['certification']
                                break
                        break
            
            # Get poster path
            poster_path = None
            if 'poster_path' in details_data and details_data['poster_path']:
                poster_path = f"{TMDB_IMAGE_BASE_URL}{details_data['poster_path']}"
            
            return {
                'cast': cast,
                'directors': directors,
                'age_rating': age_rating,
                'poster_path': poster_path,
                'tmdb_id': movie_id
            }
        
        return None
    except Exception as e:
        print(f"Error fetching TMDB details for '{movie_title}': {e}")
        return None

# Load data at startup for faster first request
load_data()
start_keep_alive()

# For local development
if __name__ == '__main__':
    # Run the app
    app.run(debug=True)