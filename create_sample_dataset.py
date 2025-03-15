import pandas as pd
import os

# Create a directory for the sample data
if not os.path.exists('sample_data'):
    os.makedirs('sample_data')

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