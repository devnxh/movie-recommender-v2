# 🎬 CineWatch - Your Personal Movie Genie!

<div align="center">

[![Live Demo](https://img.shields.io/badge/LIVE%20DEMO-Visit%20Site-blue?style=for-the-badge)](https://movie-recommender-v2-htgt.onrender.com/)
[![GitHub](https://img.shields.io/badge/GitHub-Repository-black?style=for-the-badge&logo=github)](https://github.com/devnxh/movie-recommender-v2)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)](LICENSE)

![CineWatch Preview](Cinewatch.png)

Discover your next favorite movie with CineWatch - an intelligent movie recommendation system powered by advanced content-based filtering and machine learning!

[View Demo](https://movie-recommender-v2-htgt.onrender.com/) • [Report Bug](https://github.com/devnxh/movie-recommender-v2/issues) • [Request Feature](https://github.com/devnxh/movie-recommender-v2/issues)

</div>

## ✨ Features

- **Browse and search.** Find a title as you type or browse by genre. Use **Filters & sort** to set a release-year range, minimum rating or maximum runtime, then sort by popularity, rating, release date or runtime.
- **Pick for me.** Draw a film that fits your applied filters. Select **Pick another film** in its details to draw again. Recent picks stay out of the draw while other matches are available.
- **Watchlist and favorites.** Save films to a watchlist in this browser as a guest. Sign in to keep favorites across devices and open your **For you** recommendations from the account menu.
- **Film details and trailers.** See the synopsis, rating and runtime, or find similar films. With TMDB configured, details can include current metadata, credits, age certification, trailers and review excerpts. When a trailer cannot be embedded, open the film’s trailer search on YouTube.
- **Community reviews.** Open **Reviews** on a film to read recent CineWatch reviews. Sign in to publish a rating from 1 to 10 and a review of up to 1,200 characters. You can edit or delete your review later.

## 🛠️ Technologies Used

- **Backend Stack**
  - Python 3.10+
  - Flask 3.1.0
  - Pandas 2.2.3
  - Scikit-learn 1.6.0
  - NumPy
  - SQLite or PostgreSQL for accounts, favorites and reviews

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
  - Cached sparse matrix and movie metadata

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

3. Run the application from the repository root. The first local run processes the dataset and caches it in `app/models/`.

   ```bash
   python app.py
   ```

4. Open `http://localhost:5000` in your browser. Local accounts, favorites and reviews are stored in `var/cinewatch.sqlite3`. To check the installation, run `python -m unittest discover -s tests -v`.

### Optional services

| Setting | Purpose |
| --- | --- |
| `TMDB_API_KEY` | Refresh selected film details from TMDB, including credits, trailers and review excerpts when available. Requests for the same film reuse successful results within a 15-minute window. [Get a TMDB API key](https://www.themoviedb.org/settings/api) |
| `YOUTUBE_API_KEY` | Look up a trailer through the YouTube Data API when TMDB has no matching trailer. Without either key, the app provides a YouTube search link. |
| `DATABASE_URL` | PostgreSQL connection URL for shared accounts, favorites and reviews. The application creates its tables on first use. |
| `CINEWATCH_DB_PATH` | Override the SQLite database path when `DATABASE_URL` is unset. On a host, use a path on a persistent disk for a single service instance. |
| `FLASK_SECRET_KEY` | Stable secret for signing guest watchlist cookies across restarts and instances. Local development generates and reuses a key automatically. |

### Deploying on Render

The Blueprint defines a Gunicorn web service and a free PostgreSQL database named `cinewatch-accounts`. Create or sync the Blueprint to connect the database through `DATABASE_URL` and generate a stable `FLASK_SECRET_KEY`. Review the free database’s expiry and retention terms before storing user data. [Render Blueprint](render.yaml) · [Render free services](https://render.com/docs/free)

For a manually managed web service, set its build command to `pip install -r requirements.txt` and start command to `gunicorn app:app`. Set `DATABASE_URL` to your database’s internal connection URL and set a persistent `FLASK_SECRET_KEY` in **Environment**, then redeploy. Enter optional API keys there as needed. Until a persistent store is configured, hosted users can browse films and use their guest watchlist.

Render and Vercel load the smaller catalog in `sample_data/`. After deployment, `GET /health` reports the loaded movie count and `GET /api/account` reports whether accounts are available. On Render the app pings its own health endpoint every 600 seconds by default. Set `KEEP_ALIVE=0` to disable the ping or `KEEP_ALIVE_INTERVAL` to change the interval in seconds (minimum 60).

### Content filtering

Films that TMDB flags as adult (pornographic) are removed from the dataset at load time, so they never appear in search, suggestions, browsing or recommendations.

## 💡 How It Works

**Find similar movies** compares each film’s genres, keywords and overview using TF-IDF and cosine similarity. It ranks the closest candidates using genre overlap and a quality score that accounts for both rating and number of votes.

**For you** starts with popular films. After you save favorites, it recommends other films liked by members with overlapping favorites, giving more weight to closer matches. Similar films from the catalog and popular titles fill any remaining spots. The feed excludes films already in your favorites.

## Dataset

The system uses the TMDB movie dataset (v11) which includes the following movie information.

- Title, overview, and release date
- Genres and keywords
- Vote average and vote count
- Production companies and countries
- Poster and backdrop images

## Motion artwork

The hero uses original AI-generated film-reel artwork delivered locally in two WebP sizes. Pointer and scroll effects run while the artwork is in view. Both motion controls honor the visitor’s reduced-motion preference.

The featured genre posters use a locally rendered Action sculpture, a CSS wireframe globe, and a Comedy animation adapted from Utkarsh Verma’s “3 dots bounce” (SVG Spinners, MIT). [Original animation](https://github.com/n3r4zzurr0/svg-spinners/blob/abfa05c49acf005b8b1e0ef8eb25a67a7057eb20/svg-css/3-dots-bounce.svg) · [License](app/static/media/svg-spinners-LICENSE.txt)
