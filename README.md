# 🎬 CineWatch - Your Personal Movie Genie!

<div align="center">

[![Live Demo](https://img.shields.io/badge/LIVE%20DEMO-Visit%20Site-blue?style=for-the-badge)](https://movie-recommender-v2.vercel.app/)
[![GitHub](https://img.shields.io/badge/GitHub-Repository-black?style=for-the-badge&logo=github)](https://github.com/devnxh/movie-recommender-v2)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)](LICENSE)

![CineWatch Preview](Cinewatch.png)

Discover your next favorite movie with CineWatch - an intelligent movie recommendation system powered by advanced content-based filtering and machine learning!

[View Demo](https://movie-recommender-v2.vercel.app/) • [Report Bug](https://github.com/devnxh/movie-recommender-v2/issues) • [Request Feature](https://github.com/devnxh/movie-recommender-v2/issues)

</div>

## ✨ Features

- 🔍 **Smart Search** - Find movies instantly with intelligent search suggestions
- 🎯 **Personalized Recommendations** - Get movie suggestions based on your preferences
- 🏷️ **Genre Filtering** - Browse movies by your favorite genres
- 📋 **Watchlist** - Save movies to watch later
- 🎦 **Movie Details** - View comprehensive movie information, including:
  - Cast and directors
  - Age ratings
  - Movie trailers
  - Plot overview
- 📱 **Responsive Design** - Perfect experience on all devices
- ⚡ **Fast Loading** - Optimized performance with progress indicators

## 🛠️ Technologies Used

- **Backend Stack**
  - Python 3.10
  - Flask 3.1.0
  - Pandas 2.2.3
  - Scikit-learn 1.6.1
  - NumPy 1.26.4

- **Frontend Stack**
  - HTML5 & CSS3
  - JavaScript (ES6+)
  - jQuery
  - Bootstrap 5
  - Font Awesome

- **Data Processing**
  - TF-IDF Vectorization
  - Cosine Similarity
  - TMDB Dataset
  - HDF5 Storage

- **API Integration**
  - TMDB API
  - YouTube API (optional)

## 🚀 Getting Started

### Prerequisites

- Python 3.10 or higher
- Git LFS (for dataset handling)
- pip (Python package manager)

### Installation

1. Clone the repository with Git LFS:
   ```bash
   git lfs clone https://github.com/devnxh/movie-recommender-v2.git
   cd movie-recommender-v2
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the application:
   ```bash
   python app.py
   ```

4. Open [http://localhost:5000](http://localhost:5000) in your browser

## 💡 How It Works

### Content-Based Recommendation Engine

1. **Data Processing**
   - Extracts features from movie metadata (genres, keywords, overview)
   - Applies TF-IDF vectorization for text analysis
   - Creates a rich feature matrix for similarity calculations

2. **Recommendation Algorithm**
   ```python
   def get_recommendations(title, n=10):
       # Get movie feature vector
       movie_vector = tfidf_matrix[indices[title]]
       
       # Calculate similarity with all movies
       sim_scores = cosine_similarity(movie_vector, tfidf_matrix)
       
       # Return top N similar movies
       return get_top_movies(sim_scores, n)
   ```

3. **Performance Optimization**
   - Efficient sparse matrix operations
   - HDF5 caching for fast data loading
   - Chunked processing for large datasets

2. **Recommendation Engine**:
   - Content-based filtering using cosine similarity
   - Movies are recommended based on similarity in genres, keywords, and plot

3. **User Interface**:
   - Clean and intuitive interface built with Bootstrap
   - Real-time search functionality
   - Detailed movie information with posters
   - Loading indicators with progress bars for better user experience

## Dataset

The system uses the TMDB movie dataset (v11) which includes information about movies such as:
- Title, overview, and release date
- Genres and keywords
- Vote average and vote count
- Production companies and countries
- Poster and backdrop images

## Future Improvements

- Implement collaborative filtering for more personalized recommendations
- Add user authentication and favorite movie tracking
- Integrate with external APIs for real-time movie data
- Implement advanced filtering options (by genre, year, etc.)
- Add movie trailers and reviews

##check out live demo
https://movie-recommender-v2-htgt.onrender.com/


