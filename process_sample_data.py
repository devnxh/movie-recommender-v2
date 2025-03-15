import os
import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from scipy.sparse import save_npz
from tqdm import tqdm

print("Processing sample data for Vercel deployment...")

# Create sample_data directory if it doesn't exist
if not os.path.exists('sample_data'):
    os.makedirs('sample_data')
    print("Created sample_data directory")

# Check if sample data exists
if not os.path.exists('sample_data/sample_movies.csv'):
    # Load the original dataset
    print("Loading original dataset...")
    df = pd.read_csv('TMDB_movie_dataset_v11.csv')
    
    # Get the top 1000 movies by vote count (most popular)
    print("Creating sample dataset...")
    sample_df = df.sort_values('vote_count', ascending=False).head(1000)
    
    # Save the sample dataset
    print("Saving sample dataset...")
    sample_df.to_csv('sample_data/sample_movies.csv', index=False)
    
    print(f"Sample dataset created with {len(sample_df)} movies.")
    print("Original dataset size:", df.shape)
    print("Sample dataset size:", sample_df.shape)
else:
    print("Sample dataset already exists, loading it...")
    sample_df = pd.read_csv('sample_data/sample_movies.csv')
    print(f"Loaded sample dataset with {len(sample_df)} movies.")

# Process the sample data
print("Processing sample data...")

# Display a loading bar
total_steps = 4
pbar = tqdm(total=total_steps, desc="Processing Data")

# Clean the data
print("Cleaning data...")
sample_df = sample_df.dropna(subset=['genres', 'keywords', 'overview'])
pbar.update(1)

# Create a new feature by combining relevant columns
print("Creating features...")
sample_df['combined_features'] = sample_df['genres'] + ' ' + sample_df['keywords'] + ' ' + sample_df['overview']
pbar.update(1)

# Convert text to TF-IDF features
print("Creating TF-IDF matrix...")
tfidf = TfidfVectorizer(stop_words='english', max_features=5000)  # Limit features to reduce memory usage
tfidf_matrix = tfidf.fit_transform(sample_df['combined_features'])
pbar.update(1)

# Save the processed data
print("Saving processed data...")

# Save the tfidf matrix as a sparse matrix
save_npz('sample_data/tfidf_matrix.npz', tfidf_matrix)

# Save the movies dataframe
sample_df.to_pickle('sample_data/movies_df.pkl')

pbar.update(1)
pbar.close()

print("Sample data processing completed!")
print("Files ready for Vercel deployment:")
print("- sample_data/sample_movies.csv")
print("- sample_data/tfidf_matrix.npz")
print("- sample_data/movies_df.pkl")

print("\nYou can now deploy your application to Vercel!") 