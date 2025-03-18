# CineWatch - Your personal movie genie!

A web-based movie recommendation system built with Flask that suggests movies based on content similarity. CineWatch uses the TMDB movie dataset and implements a content-based filtering approach to help you discover your next favorite movie.

## Features

- Search for movies by title
- View detailed information about movies
- Get personalized movie recommendations based on your preferences
- Browse top-rated movies
- Responsive UI for all devices
- Loading indicators with progress bars

## Technologies Used

- **Backend**: Python, Flask
- **Frontend**: HTML, CSS, JavaScript, jQuery, Bootstrap 5
- **Data Processing**: Pandas, Scikit-learn
- **Data Storage**: HDF5 (h5py)

## Installation

1. Clone the repository:
   ```
   git clone <repository-url>
   cd movie-recommender
   ```

2. Install the required packages:
   ```
   pip install pandas scikit-learn flask tqdm h5py
   ```

3. Run the application:
   ```
   python app.py
   ```

4. Open your browser and navigate to:
   ```
   http://localhost:5000
   ```

## How It Works

1. **Data Processing**:
   - The system loads the TMDB movie dataset
   - It extracts features from movie genres, keywords, and overview
   - TF-IDF vectorization is applied to convert text data into numerical features
   - The processed data is saved in HDF5 format for faster loading in future runs

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


