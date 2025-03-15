$(document).ready(function() {
    // Variables
    let currentMovie = null;
    const progressBar = $('.progress-bar');
    const loadingText = $('#loading-text');
    const tmdbImageBaseUrl = 'https://image.tmdb.org/t/p/w500';
    let typingTimer;
    const doneTypingInterval = 300; // Time in ms after user stops typing
    let watchlist = [];
    
    // Pagination variables
    let currentPage = 1;
    let currentSearchTerm = '';
    let currentGenre = '';
    let isSearchActive = false;
    let isGenreFilterActive = false;
    
    // Event Listeners
    $('#search-button').on('click', searchMovies);
    $('#search-input').on('keypress', function(e) {
        if (e.which === 13) {
            searchMovies();
        }
    });
    
    // Hero section buttons
    $('#browse-all-movies').on('click', function() {
        browseMovies();
        
        // Scroll to browse section
        $('html, body').animate({
            scrollTop: $('#browse-section').offset().top - 100
        }, 800);
    });
    
    $('#show-genres').on('click', function() {
        // Scroll to genre section with animation
        $('html, body').animate({
            scrollTop: $('.genre-filter-section').offset().top - 100
        }, 800);
        
        // Add attention animation to genre section
        $('.genre-filter-section .card').addClass('animate__animated animate__pulse');
        
        // Remove animation class after animation completes
        setTimeout(function() {
            $('.genre-filter-section .card').removeClass('animate__animated animate__pulse');
        }, 1000);
    });
    
    // Add event listeners for search suggestions
    $('#search-input').on('input', function() {
        clearTimeout(typingTimer);
        const query = $(this).val().trim();
        
        if (query.length < 2) {
            $('#search-suggestions').empty().addClass('d-none');
            return;
        }
        
        typingTimer = setTimeout(function() {
            getSearchSuggestions(query);
        }, doneTypingInterval);
    });
    
    // Hide suggestions when clicking outside
    $(document).on('click', function(e) {
        if (!$(e.target).closest('#search-input, #search-suggestions').length) {
            $('#search-suggestions').addClass('d-none');
        }
    });
    
    // Genre filter click event
    $('.genre-icon').on('click', function() {
        const genre = $(this).data('genre');
        
        // Toggle active class
        $(this).toggleClass('active');
        
        // If active, filter by this genre
        if ($(this).hasClass('active')) {
            // Deactivate other genres
            $('.genre-icon').not(this).removeClass('active');
            
            // Reset pagination
            currentPage = 1;
            currentSearchTerm = '';
            isSearchActive = false;
            isGenreFilterActive = true;
            currentGenre = genre;
            
            // Show loading
            showLoading(`Loading ${genre} movies...`);
            updateProgress(20);
            
            // Hide default movies section
            $('#default-movies-section').addClass('d-none');
            
            // Get movies by genre
            $.ajax({
                url: `/movies?genre=${genre}&page=${currentPage}`,
                method: 'GET',
                success: function(data) {
                    updateProgress(100);
                    hideLoading();
                    
                    // Display filtered movies
                    displayBrowseMovies(data);
                    
                    // Update section title with animation
                    $('#browse-section h2').text(`Top ${genre} Movies`).addClass('animate__animated animate__fadeIn');
                    
                    // Scroll to browse section with smooth animation
                    $('html, body').animate({
                        scrollTop: $('#browse-section').offset().top - 100
                    }, 800);
                },
                error: function(xhr, status, error) {
                    hideLoading();
                    console.error("Genre filter error:", error);
                    alert('An error occurred while loading movies. Please try again later.');
                }
            });
        } else {
            // If no genre is selected, show all movies
            browseMovies();
        }
    });
    
    // Watchlist button events
    $('#show-watchlist').on('click', showWatchlist);
    $('#clear-watchlist').on('click', clearWatchlist);
    
    // Movie modal events
    $('#watchTrailerBtn').on('click', watchTrailer);
    $('#addToWatchlistBtn').on('click', addToWatchlist);
    
    $('#browse-movies').on('click', browseMovies);
    $('#getRecommendationsBtn').on('click', getRecommendationsForModal);
    
    // Load default movies and watchlist on page load
    loadDefaultMovies();
    loadWatchlist();
    
    // Functions
    function loadWatchlist() {
        $.ajax({
            url: '/watchlist',
            method: 'GET',
            success: function(data) {
                watchlist = data;
                updateWatchlistCount();
                
                // If watchlist has items, show it
                if (watchlist.length > 0) {
                    displayWatchlist();
                }
            },
            error: function(xhr, status, error) {
                console.error("Watchlist load error:", error);
            }
        });
    }
    
    function updateWatchlistCount() {
        $('#watchlist-count').text(watchlist.length);
    }
    
    function showWatchlist() {
        if (watchlist.length === 0) {
            alert('Your watchlist is empty. Add movies to your watchlist by clicking the "Add to Watchlist" button when viewing movie details.');
            return;
        }
        
        displayWatchlist();
        
        // Scroll to watchlist section
        $('html, body').animate({
            scrollTop: $('#watchlist-section').offset().top - 100
        }, 500);
    }
    
    function displayWatchlist() {
        const container = $('#watchlist-container');
        container.empty();
        
        watchlist.forEach(function(movie, index) {
            const card = createMovieCard(movie).addClass('animate__animated animate__fadeIn');
            
            // Add watchlist badge
            card.find('.card').prepend('<div class="watchlist-badge"><i class="fas fa-bookmark"></i></div>');
            
            // Add remove from watchlist button
            const removeBtn = $(`<button class="btn btn-sm btn-danger remove-from-watchlist" data-title="${movie.title}">
                                    <i class="fas fa-trash"></i> Remove
                                </button>`);
            
            removeBtn.on('click', function(e) {
                e.stopPropagation(); // Prevent card click
                removeFromWatchlist(movie.title);
            });
            
            card.find('.poster-overlay').append(removeBtn);
            
            container.append(card);
        });
        
        $('#watchlist-section').removeClass('d-none');
    }
    
    function addToWatchlist() {
        if (!currentMovie) return;
        
        // Check if movie is already in watchlist
        const exists = watchlist.some(item => item.title === currentMovie.title);
        if (exists) {
            // Show a message that it's already in the watchlist
            alert(`"${currentMovie.title}" is already in your watchlist!`);
            return;
        }
        
        // Add to watchlist
        watchlist.push({
            title: currentMovie.title,
            vote_average: currentMovie.vote_average,
            genres: currentMovie.genres,
            poster_path: currentMovie.poster_path,
            overview: currentMovie.overview,
            cast: currentMovie.cast || [],
            directors: currentMovie.directors || [],
            age_rating: currentMovie.age_rating || 'Not Rated'
        });
        
        // Save to server
        $.ajax({
            url: '/watchlist',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ movie: currentMovie }),
            success: function(response) {
                // Update button text
                $('#addToWatchlistBtn').html('<i class="fas fa-check"></i> Added to Watchlist');
                
                // Update watchlist count
                updateWatchlistCount();
                
                // Show watchlist section if hidden
                $('#watchlist-section').removeClass('d-none');
                
                // Display the updated watchlist
                displayWatchlist();
            },
            error: function(xhr, status, error) {
                console.error("Error adding to watchlist:", error);
                alert("Failed to add movie to watchlist. Please try again.");
            }
        });
    }
    
    function removeFromWatchlist(title) {
        $.ajax({
            url: '/watchlist',
            method: 'DELETE',
            contentType: 'application/json',
            data: JSON.stringify({ title: title }),
            success: function(response) {
                // Remove from local watchlist
                watchlist = watchlist.filter(movie => movie.title !== title);
                updateWatchlistCount();
                
                // Update display
                if (watchlist.length === 0) {
                    $('#watchlist-section').addClass('d-none');
                } else {
                    displayWatchlist();
                }
            },
            error: function(xhr, status, error) {
                console.error("Remove from watchlist error:", error);
                alert('Failed to remove movie from watchlist. Please try again.');
            }
        });
    }
    
    function clearWatchlist() {
        if (watchlist.length === 0) return;
        
        if (confirm('Are you sure you want to clear your watchlist?')) {
            // Clear each movie one by one
            const promises = watchlist.map(movie => {
                return $.ajax({
                    url: '/watchlist',
                    method: 'DELETE',
                    contentType: 'application/json',
                    data: JSON.stringify({ title: movie.title })
                });
            });
            
            Promise.all(promises)
                .then(() => {
                    watchlist = [];
                    updateWatchlistCount();
                    $('#watchlist-section').addClass('d-none');
                })
                .catch(error => {
                    console.error("Clear watchlist error:", error);
                    alert('Failed to clear watchlist. Please try again.');
                });
        }
    }
    
    function watchTrailer() {
        if (!currentMovie) return;
        
        // Show loading
        $('#watchTrailerBtn').html('<i class="fas fa-spinner fa-spin"></i> Loading...');
        
        // Get trailer
        $.ajax({
            url: '/get_trailer',
            method: 'POST',
            data: { title: currentMovie.title },
            success: function(data) {
                // Reset button
                $('#watchTrailerBtn').html('<i class="fas fa-play-circle"></i> Watch Trailer');
                
                // Set trailer title
                $('#trailerModalTitle').text(data.title);
                
                if (data.video_id) {
                    // Set iframe source
                    $('#trailerIframe').attr('src', data.embed_url);
                    
                    // Show trailer modal
                    const trailerModal = new bootstrap.Modal(document.getElementById('trailerModal'));
                    trailerModal.show();
                    
                    // When trailer modal is closed, stop the video
                    $('#trailerModal').on('hidden.bs.modal', function() {
                        $('#trailerIframe').attr('src', '');
                    });
                } else if (data.search_url) {
                    // Open YouTube search in new tab
                    window.open(data.search_url, '_blank');
                }
            },
            error: function(xhr, status, error) {
                // Reset button
                $('#watchTrailerBtn').html('<i class="fas fa-play-circle"></i> Watch Trailer');
                
                console.error("Trailer error:", error);
                alert('Could not find a trailer for this movie. Please try searching on YouTube.');
            }
        });
    }
    
    function getSearchSuggestions(query) {
        $.ajax({
            url: '/search_suggestions',
            method: 'POST',
            data: { query: query },
            success: function(suggestions) {
                displaySearchSuggestions(suggestions);
            },
            error: function(xhr, status, error) {
                console.error("Suggestion error:", error);
            }
        });
    }
    
    function displaySearchSuggestions(suggestions) {
        const suggestionsContainer = $('#search-suggestions');
        suggestionsContainer.empty();
        
        if (suggestions.length === 0) {
            suggestionsContainer.addClass('d-none');
            return;
        }
        
        suggestions.forEach(function(title) {
            const suggestion = $(`<div class="suggestion-item">${title}</div>`);
            suggestion.on('click', function() {
                $('#search-input').val(title);
                suggestionsContainer.addClass('d-none');
                searchMovies();
            });
            suggestionsContainer.append(suggestion);
        });
        
        suggestionsContainer.removeClass('d-none');
    }
    
    function loadDefaultMovies() {
        // Show loading
        showLoading('Loading blockbuster movies...');
        updateProgress(20);
        
        // Send AJAX request
        $.ajax({
            url: '/default_movies',
            method: 'GET',
            success: function(data) {
                updateProgress(100);
                
                // Hide loading
                hideLoading();
                
                // Display default movies
                displayDefaultMovies(data);
            },
            error: function(xhr, status, error) {
                hideLoading();
                console.error("Default movies error:", error);
            }
        });
    }
    
    function displayDefaultMovies(movies) {
        const container = $('#default-movies-container');
        container.empty();
        
        if (movies.length === 0) {
            container.append(`<div class="col-12 text-center alert alert-info">
                                <p>No movies found. Please try searching for a movie.</p>
                            </div>`);
        } else {
            movies.forEach(function(movie, index) {
                // Create movie card with animation
                const card = createMovieCard(movie).addClass('animate__animated animate__fadeIn');
                
                // Add blockbuster badge
                card.find('.card').prepend('<div class="blockbuster-badge"><i class="fas fa-star"></i> Blockbuster</div>');
                
                // Add with staggered delay
                const delay = index * 100;
                card.css('animation-delay', delay + 'ms');
                
                container.append(card);
            });
        }
        
        // Show the section with animation
        $('#default-movies-section').removeClass('d-none').addClass('animate__animated animate__fadeIn');
    }
    
    function searchMovies(page = 1) {
        const searchTerm = $('#search-input').val().trim();
        
        if (searchTerm === '') {
            return;
        }
        
        // Reset pagination if this is a new search
        if (searchTerm !== currentSearchTerm || page === 1) {
            currentPage = 1;
            currentSearchTerm = searchTerm;
            isSearchActive = true;
            isGenreFilterActive = false;
            currentGenre = '';
        }
        
        // If loading more, increment the page
        if (page > 1) {
            currentPage = page;
        }
        
        // Show loading
        showLoading('Searching for movies...');
        updateProgress(20);
        
        // Hide default movies section
        $('#default-movies-section').addClass('d-none');
        
        // Send AJAX request
        $.ajax({
            url: '/search',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ 
                query: searchTerm,
                page: currentPage
            }),
            success: function(data) {
                updateProgress(100);
                
                // Hide loading
                hideLoading();
                
                // Display search results
                displaySearchResults(data, page > 1);
            },
            error: function(xhr, status, error) {
                hideLoading();
                console.error("Search error:", error);
                alert('An error occurred while searching for movies. Please try again later.');
            }
        });
    }
    
    function displaySearchResults(results, append = false) {
        const searchResults = $('#search-results');
        
        // Clear results if not appending
        if (!append) {
            searchResults.empty();
        } else {
            // Remove load more button if it exists
            $('#load-more-btn-container').remove();
        }
        
        if (results.length === 0) {
            if (!append) {
                searchResults.append('<p class="text-center">No movies found. Try a different search term.</p>');
            } else {
                // If appending and no results, show "no more results" message
                searchResults.append('<div id="load-more-btn-container" class="col-12 text-center mt-3 mb-5"><p>No more movies to load.</p></div>');
            }
        } else {
            // Create a row for movie cards if not appending
            let row;
            if (!append) {
                row = $('<div class="row"></div>');
                searchResults.append(row);
            } else {
                row = searchResults.find('.row').first();
            }
            
            // Add movie cards to the row
            results.forEach(function(movie, index) {
                const card = createMovieCard(movie);
                row.append(card);
            });
            
            // Add "Load More" button
            const loadMoreBtn = $(`
                <div id="load-more-btn-container" class="col-12 text-center mt-3 mb-5">
                    <button id="load-more-btn" class="btn btn-outline-primary">
                        <i class="fas fa-plus"></i> Load More Movies
                    </button>
                </div>
            `);
            
            searchResults.append(loadMoreBtn);
            
            // Add event listener to load more button
            $('#load-more-btn').on('click', function() {
                loadMoreMovies();
            });
            
            // Show the search results
            searchResults.removeClass('d-none');
        }
    }
    
    function showMovieModal(movie) {
        // Set movie details in the modal
        $('#movieModalLabel').text(movie.title);
        $('#moviePoster').attr('src', movie.poster_path || 'https://fakeimg.pl/300x450/333333/ffffff?text=No+Poster');
        $('#movieRating').html(`<i class="fas fa-star"></i> ${movie.vote_average ? movie.vote_average.toFixed(1) : 'N/A'}`);
        $('#movieGenres').text(formatGenres(movie.genres));
        $('#movieOverview').text(movie.overview || 'No overview available.');
        
        // Add age rating
        if (movie.age_rating) {
            $('#movieAgeRating').html(`<span class="badge ${getAgeRatingClass(movie.age_rating)}">${movie.age_rating}</span>`);
            $('#movieAgeRatingContainer').removeClass('d-none');
        } else {
            $('#movieAgeRatingContainer').addClass('d-none');
        }
        
        // Add cast and directors
        if (movie.cast && movie.cast.length > 0) {
            $('#movieCast').text(movie.cast.join(', '));
            $('#movieCastContainer').removeClass('d-none');
        } else {
            $('#movieCastContainer').addClass('d-none');
        }
        
        if (movie.directors && movie.directors.length > 0) {
            $('#movieDirectors').text(movie.directors.join(', '));
            $('#movieDirectorsContainer').removeClass('d-none');
        } else {
            $('#movieDirectorsContainer').addClass('d-none');
        }
        
        // Store the current movie for recommendations
        currentMovie = movie;
        
        // Show the modal
        $('#movieModal').modal('show');
    }
    
    function getRecommendationsForModal() {
        if (!currentMovie) {
            return;
        }
        
        // Hide the modal
        const movieModalEl = document.getElementById('movieModal');
        const movieModal = bootstrap.Modal.getInstance(movieModalEl);
        movieModal.hide();
        
        // Get recommendations
        getRecommendations(currentMovie.title);
    }
    
    function getRecommendations(title) {
        // Show loading
        showLoading('Finding recommendations...');
        updateProgress(10);
        
        // Hide other sections
        $('#recommendations-section').addClass('d-none');
        $('#browse-section').addClass('d-none');
        
        // Send AJAX request
        $.ajax({
            url: '/recommend',
            method: 'POST',
            data: { title: title },
            success: function(data) {
                updateProgress(100);
                
                // Hide loading
                hideLoading();
                
                // Display recommendations
                displayRecommendations(data, title);
            },
            error: function(xhr, status, error) {
                hideLoading();
                console.error("Recommendation error:", error);
                console.error("Status:", status);
                console.error("Response:", xhr.responseText);
                
                // Show error message in recommendations section
                const container = $('#recommendations-container');
                container.empty();
                container.append(`<div class="col-12 text-center alert alert-warning">
                                    <p>Sorry, we couldn't find recommendations for "${title}". This might be because:</p>
                                    <ul class="text-start">
                                        <li>The movie has unique characteristics with few similar movies</li>
                                        <li>The movie might not be in our database</li>
                                        <li>There was a technical issue processing your request</li>
                                    </ul>
                                    <p>Please try another movie or browse our top movies.</p>
                                </div>`);
                
                $('#recommendations-section').removeClass('d-none');
                
                // Scroll to recommendations
                $('html, body').animate({
                    scrollTop: $('#recommendations-section').offset().top - 100
                }, 500);
            }
        });
    }
    
    function displayRecommendations(recommendations, title) {
        const container = $('#recommendations-container');
        container.empty();
        
        if (recommendations.length === 0) {
            container.append(`<div class="col-12 text-center alert alert-info">
                                <p>No recommendations found for "${title}". This might be because:</p>
                                <ul class="text-start">
                                    <li>The movie has unique characteristics with few similar movies</li>
                                    <li>The movie might be new or less popular</li>
                                </ul>
                                <p>Please try another movie or browse our top movies.</p>
                            </div>`);
        } else {
            recommendations.forEach(function(movie, index) {
                // Add animation with staggered delay
                const delay = index * 100;
                const card = createMovieCard(movie).addClass('animate__animated animate__fadeInUp');
                card.css('animation-delay', delay + 'ms');
                container.append(card);
            });
        }
        
        $('#recommendations-section').removeClass('d-none');
        
        // Scroll to recommendations
        $('html, body').animate({
            scrollTop: $('#recommendations-section').offset().top - 100
        }, 500);
    }
    
    function browseMovies(page = 1) {
        // Reset pagination if this is a new browse request
        if (page === 1) {
            currentPage = 1;
            currentSearchTerm = '';
            isSearchActive = false;
            isGenreFilterActive = false;
            currentGenre = '';
        }
        
        // If loading more, increment the page
        if (page > 1) {
            currentPage = page;
        }
        
        // Show loading
        showLoading('Loading top movies...');
        updateProgress(20);
        
        // Hide other sections
        $('#recommendations-section').addClass('d-none');
        $('#search-results').addClass('d-none');
        
        // Reset genre filter
        $('.genre-icon').removeClass('active');
        
        // Send AJAX request
        $.ajax({
            url: `/movies?page=${currentPage}`,
            method: 'GET',
            success: function(data) {
                updateProgress(100);
                
                // Hide loading
                hideLoading();
                
                // Display movies
                displayBrowseMovies(data, page > 1);
                
                // Reset section title
                $('#browse-section h2').text('Browse Top Movies');
            },
            error: function(xhr, status, error) {
                hideLoading();
                console.error("Browse error:", error);
                alert('An error occurred while loading movies. Please try again later.');
            }
        });
    }
    
    function displayBrowseMovies(movies, append = false) {
        const container = $('#browse-container');
        
        // Clear container if not appending
        if (!append) {
            container.empty();
        } else {
            // Remove load more button if it exists
            $('#load-more-browse-btn-container').remove();
        }
        
        if (movies.length === 0) {
            if (!append) {
                container.append(`<div class="col-12 text-center alert alert-info">
                                    <p>No movies found. Please try again later.</p>
                                </div>`);
            } else {
                // If appending and no results, show "no more results" message
                container.append('<div id="load-more-browse-btn-container" class="col-12 text-center mt-3 mb-5"><p>No more movies to load.</p></div>');
            }
        } else {
            movies.forEach(function(movie, index) {
                // Add animation with staggered delay
                const delay = index * 50;
                const card = createMovieCard(movie).addClass('animate__animated animate__fadeInUp');
                card.css('animation-delay', delay + 'ms');
                container.append(card);
            });
            
            // Add "Load More" button
            const loadMoreBtn = $(`
                <div id="load-more-browse-btn-container" class="col-12 text-center mt-3 mb-5">
                    <button id="load-more-browse-btn" class="btn btn-outline-primary">
                        <i class="fas fa-plus"></i> Load More Movies
                    </button>
                </div>
            `);
            
            container.append(loadMoreBtn);
            
            // Add event listener to load more button
            $('#load-more-browse-btn').on('click', function() {
                loadMoreMovies();
            });
        }
        
        // Show the section with animation
        $('#browse-section').removeClass('d-none').addClass('animate__animated animate__fadeIn');
        
        // Scroll to browse section if not appending
        if (!append) {
            $('html, body').animate({
                scrollTop: $('#browse-section').offset().top - 100
            }, 500);
        }
    }
    
    function createMovieCard(movie) {
        // Create a movie card element with enhanced animations
        const card = $(`
            <div class="col-md-4 col-lg-3 mb-4">
                <div class="card movie-card h-100 shadow">
                    <div class="card-img-container">
                        <img src="${movie.poster_path || 'https://fakeimg.pl/300x450/333333/ffffff?text=No+Poster'}" class="card-img-top" alt="${movie.title}">
                        <div class="card-img-overlay">
                            <div class="rating">
                                <i class="fas fa-star"></i> ${movie.vote_average ? movie.vote_average.toFixed(1) : 'N/A'}
                            </div>
                            ${movie.age_rating ? `<div class="age-rating ${getAgeRatingClass(movie.age_rating)}">${movie.age_rating}</div>` : ''}
                            <div class="overlay-content">
                                <button class="btn btn-light btn-sm view-details-overlay mb-2" data-movie='${JSON.stringify(movie).replace(/'/g, "&#39;")}'>
                                    <i class="fas fa-info-circle"></i> View Details
                                </button>
                                <button class="btn btn-outline-light btn-sm add-to-watchlist-overlay" data-title="${movie.title}">
                                    <i class="fas fa-bookmark"></i> Add to Watchlist
                                </button>
                            </div>
                        </div>
                    </div>
                    <div class="card-body">
                        <h5 class="card-title">${movie.title}</h5>
                        <p class="card-text genres">${formatGenres(movie.genres)}</p>
                        ${movie.directors && movie.directors.length > 0 ? 
                            `<p class="card-text directors"><small><i class="fas fa-video"></i> ${movie.directors[0]}</small></p>` : ''}
                    </div>
                    <div class="card-footer">
                        <button class="btn btn-primary btn-sm view-details" data-movie='${JSON.stringify(movie).replace(/'/g, "&#39;")}'>
                            <i class="fas fa-info-circle"></i> Details
                        </button>
                        <button class="btn btn-outline-primary btn-sm add-to-watchlist" data-title="${movie.title}">
                            <i class="fas fa-plus"></i> Watchlist
                        </button>
                    </div>
                </div>
            </div>
        `);
        
        // Add event listeners
        card.find('.view-details, .view-details-overlay').on('click', function() {
            const movieData = $(this).data('movie');
            showMovieModal(movieData);
        });
        
        card.find('.add-to-watchlist, .add-to-watchlist-overlay').on('click', function(e) {
            e.stopPropagation(); // Prevent card click
            addMovieToWatchlist(movie);
        });
        
        return card;
    }
    
    function showLoading(message) {
        loadingText.text(message || 'Loading...');
        $('#loading').removeClass('d-none').addClass('animate__animated animate__fadeIn');
        updateProgress(0);
    }
    
    function hideLoading() {
        $('#loading').addClass('animate__animated animate__fadeOut');
        setTimeout(function() {
            $('#loading').addClass('d-none').removeClass('animate__animated animate__fadeIn animate__fadeOut');
        }, 500);
    }
    
    function updateProgress(value) {
        progressBar.css('width', value + '%');
        
        // Simulate progress if value is less than 100
        if (value < 100) {
            setTimeout(function() {
                const newValue = value + 10;
                if (newValue < 90) {
                    updateProgress(newValue);
                }
            }, 300);
        }
    }
    
    // Helper function to determine age rating class
    function getAgeRatingClass(rating) {
        switch(rating) {
            case 'G':
                return 'bg-success';
            case 'PG':
                return 'bg-info';
            case 'PG-13':
                return 'bg-warning';
            case 'R':
            case 'NC-17':
                return 'bg-danger';
            default:
                return 'bg-secondary';
        }
    }
    
    // Helper function to format genres
    function formatGenres(genresString) {
        if (!genresString) return 'Unknown';
        
        // Remove brackets if present
        let cleaned = genresString.replace(/[\[\]']/g, '');
        
        // Split by commas and trim
        let genres = cleaned.split(',').map(g => g.trim());
        
        // Take only first 3 genres to avoid overflow
        if (genres.length > 3) {
            genres = genres.slice(0, 3);
            return genres.join(', ') + '...';
        }
        
        return genres.join(', ');
    }
    
    // Add a function to load more movies
    function loadMoreMovies() {
        // Increment page number
        currentPage++;
        
        // Determine which type of loading to perform
        if (isSearchActive) {
            // Load more search results
            searchMovies(currentPage);
        } else if (isGenreFilterActive) {
            // Load more genre-filtered movies
            loadMoreGenreMovies(currentGenre, currentPage);
        } else {
            // Load more browse movies
            browseMovies(currentPage);
        }
    }
    
    // Function to load more movies by genre
    function loadMoreGenreMovies(genre, page) {
        // Show loading
        showLoading(`Loading more ${genre} movies...`);
        updateProgress(20);
        
        // Get movies by genre
        $.ajax({
            url: `/movies?genre=${genre}&page=${page}`,
            method: 'GET',
            success: function(data) {
                updateProgress(100);
                hideLoading();
                
                // Display filtered movies
                displayBrowseMovies(data, true);
            },
            error: function(xhr, status, error) {
                hideLoading();
                console.error("Load more genre movies error:", error);
                alert('An error occurred while loading more movies. Please try again later.');
            }
        });
    }
}); 