import os
import pandas as pd
import numpy as np
from flask import Flask, render_template, request, jsonify, session
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import pickle
from tqdm import tqdm
import time
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

# YouTube API key - in a real app, this would be stored securely
YOUTUBE_API_KEY = "YOUR_YOUTUBE_API_KEY"  # Replace with your actual API key if available

# TMDB API key
TMDB_API_KEY = "f3ca028bc7f9a25f5613839a01f600df"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Check if we're in production (Vercel) or development
IS_PRODUCTION = os.environ.get('VERCEL', False)

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
            
            # Create a Series with movie titles as indices and movie indices as values
            indices = pd.Series(movies_df.index, index=movies_df['title']).drop_duplicates()
            
            print("Data loaded successfully!")
        except Exception as e:
            print(f"Error loading preprocessed data: {e}")
            print("Processing data from scratch...")
            process_data(dataset_path, models_dir)
    else:
        print("Preprocessed data not found. Processing data for the first time...")
        # Process the data
        process_data(dataset_path, models_dir)

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
    
    # Create a Series with movie titles as indices and movie indices as values
    indices = pd.Series(movies_df.index, index=movies_df['title']).drop_duplicates()
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
            # Use the first close match
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
            
        # Compute similarity for the specific movie
        # This is more memory efficient than computing the entire similarity matrix
        movie_vector = tfidf_matrix[idx].reshape(1, -1)
        
        # Calculate similarity scores for this movie with all others
        sim_scores = cosine_similarity(movie_vector, tfidf_matrix).flatten()
        
        # Get the indices of the top n similar movies (excluding the movie itself)
        sim_indices = sim_scores.argsort()[::-1][1:n+1]
        
        # Check if we have valid indices
        if len(sim_indices) == 0:
            return []
        
        # Return the top n most similar movies
        result = movies_df.iloc[sim_indices][['title', 'vote_average', 'genres', 'poster_path', 'overview']].to_dict(orient='records')
        
        # Enhance movies with TMDB details
        enhanced_result = []
        for movie in result:
            # Fix poster path if it's just a relative path
            if movie['poster_path'] and not movie['poster_path'].startswith(('http://', 'https://')):
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
        return None

def extract_genres_from_movies():
    """Extract unique genres from the movies dataset"""
    global movies_df
    
    if movies_df is None:
        return []
    
    # Get all genres
    all_genres = []
    for genres_str in movies_df['genres'].dropna():
        # Extract genres using regex
        genres = re.findall(r'([A-Za-z\s]+)(?:,|$)', genres_str)
        all_genres.extend([g.strip() for g in genres])
    
    # Get unique genres and sort them
    unique_genres = sorted(list(set(all_genres)))
    
    # Create genre objects with icons
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
    
    genres_with_icons = []
    for genre in unique_genres:
        icon = genre_icons.get(genre, 'fa-film')  # Default icon if not found
        genres_with_icons.append({
            'name': genre,
            'icon': icon
        })
    
    return genres_with_icons

@app.route('/')
def index():
    """Render the home page"""
    # Get all unique genres for the filter
    genres = extract_genres_from_movies()
    return render_template('index.html', genres=genres)

@app.route('/search', methods=['POST'])
def search():
    """Search for movies by title"""
    data = request.get_json()
    query = data.get('query', '')
    
    if not query:
        return jsonify([])
    
    # Find movies that match the query
    matches = movies_df[movies_df['title'].str.contains(query, case=False, regex=False)]
    
    if len(matches) == 0:
        return jsonify([])
    
    # Get the top 5 matches
    top_matches = matches.sort_values('vote_count', ascending=False).head(5)
    
    # Convert to list of dictionaries
    results = top_matches[['title', 'vote_average', 'genres', 'poster_path', 'overview']].to_dict(orient='records')
    
    # Enhance with TMDB details
    enhanced_results = []
    for movie in results:
        # Fix poster path if it's just a relative path
        if movie['poster_path'] and not movie['poster_path'].startswith(('http://', 'https://')):
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
    
    # Filter movies that contain the search term
    results = movies_df[movies_df['title'].str.contains(query, case=False)]
    
    # Return the top 5 suggestions
    suggestions = results.head(5)['title'].tolist()
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
        
        if genre:
            # Filter by genre
            filtered_movies = movies_df[movies_df['genres'].str.contains(genre, case=False, regex=False)]
            # Sort by popularity or vote count
            if 'popularity' in filtered_movies.columns:
                filtered_movies = filtered_movies.sort_values('popularity', ascending=False)
            else:
                filtered_movies = filtered_movies.sort_values('vote_count', ascending=False)
            # Get top 12 movies
            top_movies = filtered_movies.head(12)
        else:
            # Get top movies by vote count
            top_movies = movies_df.sort_values('vote_count', ascending=False).head(12)
        
        # Convert to list of dictionaries
        results = top_movies[['title', 'vote_average', 'genres', 'poster_path', 'overview']].to_dict(orient='records')
        
        # Enhance with TMDB details
        enhanced_results = []
        for movie in results:
            # Fix poster path if it's just a relative path
            if movie['poster_path'] and not movie['poster_path'].startswith(('http://', 'https://')):
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
            if movie['poster_path'] and not movie['poster_path'].startswith(('http://', 'https://')):
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

def get_movie_details_from_tmdb(movie_title):
    """Fetch detailed movie information from TMDB API"""
    try:
        # Search for the movie
        search_url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={movie_title}"
        response = requests.get(search_url)
        data = response.json()
        
        if 'results' in data and len(data['results']) > 0:
            movie_id = data['results'][0]['id']
            
            # Get detailed movie information
            details_url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&append_to_response=credits,release_dates"
            details_response = requests.get(details_url)
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

# For local development
if __name__ == '__main__':
    # Run the app
    app.run(debug=True) 