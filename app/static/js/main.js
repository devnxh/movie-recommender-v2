$(document).ready(function() {
    // Variables
    let currentMovie = null;
    const tmdbImageBaseUrl = 'https://image.tmdb.org/t/p/w500';
    let typingTimer;
    let watchlist = [];
    let watchlistBusy = false;
    let watchlistReady = false;
    let noticeTimer;
    let detailsSequence = 0;
    let modalOpener;

    const searchInput = $('#search-input');
    const suggestions = $('#search-suggestions');
    let suggestionRequest = null;
    let selectedSuggestion = -1;
    let activeView = null;
    let discoveryRequest = null;
    let recommendationHistory = [];
    const pageSize = 12;

    $('#movie-search-form').on('submit', function(event) {
        event.preventDefault();
        const query = searchInput.val().trim();
        if (query) openView('search', query);
        else searchInput.trigger('focus');
    });

    searchInput.on('input', scheduleSuggestions).on('blur', dismissSuggestions);
    searchInput.on('keydown', function(event) {
        if (event.originalEvent.isComposing) return;
        const options = suggestions.children();
        if (event.key === 'Escape') {
            if (typingTimer || suggestionRequest || options.length) {
                event.preventDefault();
                dismissSuggestions();
            }
            return;
        }
        if (!options.length) return;
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            if (event.key === 'ArrowDown') selectedSuggestion = (selectedSuggestion + 1) % options.length;
            else selectedSuggestion = selectedSuggestion <= 0 ? options.length - 1 : selectedSuggestion - 1;
            options.removeClass('active').attr('aria-selected', 'false');
            const option = options.eq(selectedSuggestion).addClass('active').attr('aria-selected', 'true');
            searchInput.attr('aria-activedescendant', option.attr('id'));
            option[0].scrollIntoView({ block: 'nearest' });
        } else if (event.key === 'Enter' && selectedSuggestion >= 0) {
            event.preventDefault();
            chooseSuggestion(options.eq(selectedSuggestion).text());
        }
    });

    suggestions.on('pointerdown', '[role="option"]', event => event.preventDefault());
    suggestions.on('click', '[role="option"]', function() { chooseSuggestion($(this).text()); });

    $('#browse-movies, .catalog-jump').on('click', function(event) {
        event.preventDefault();
        openView('browse');
    });
    $('.genre-icon, [data-poster-genre]').on('click', function() {
        const genre = this.dataset.posterGenre || this.dataset.genre || '';
        const clearFilter = !this.dataset.posterGenre && activeView?.mode === 'browse' && activeView.value === genre;
        openView('browse', clearFilter ? '' : genre);
    });
    $(document).on('cinewatch:watchlist', function() {
        leaveDiscovery();
        recommendationHistory = [];
        dismissSuggestions();
        updateGenreChips(null);
    });

    // Watchlist button events
    $('#show-watchlist').on('click', showWatchlist);
    $('#clear-watchlist').on('click', clearWatchlist);

    // Movie modal events
    $('#watchTrailerBtn').on('click', watchTrailer);
    $('#addToWatchlistBtn').on('click', () => saveMovie(currentMovie));

    $('#getRecommendationsBtn').on('click', getRecommendationsForModal);

    // Load default movies and watchlist on page load
    openView('default');
    loadWatchlist();

    // Functions
    function loadWatchlist() {
        watchlistBusy = true;
        syncWatchlistControls();
        return $.getJSON('/watchlist').done(function (movies) {
            watchlist = movies;
            watchlistReady = true;
        }).fail(function () {
            watchlistReady = false;
            watchlistNotice('Your watchlist could not be loaded.', loadWatchlist);
        }).always(function () {
            watchlistBusy = false;
            syncWatchlistControls();
            displayWatchlist();
        });
    }

    function watchlistNotice(message, retry) {
        clearTimeout(noticeTimer);
        $('#watchlist-feedback-text').text(message);
        $('#watchlist-retry').off('click').prop('hidden', !retry);
        if (retry) $('#watchlist-retry').on('click', function () {
            $('#watchlist-feedback').prop('hidden', true);
            retry();
        });
        $('#watchlist-feedback').prop('hidden', false);
        if (!retry) noticeTimer = setTimeout(() => $('#watchlist-feedback').prop('hidden', true), 2800);
    }

    function sameFilm(a, b) {
        return a.id && b.id ? a.id === b.id : a.title === b.title;
    }

    function styleSaveButton(button, movie, modal = false) {
        const saved = watchlist.some(item => sameFilm(item, movie));
        const label = saved ? 'Remove from watchlist' : 'Save to watchlist';
        button.attr({'aria-pressed': String(saved), 'aria-label': label + ' · ' + movie.title, title: label})
            .prop('disabled', watchlistBusy).find('i').attr('class', (saved ? 'fas' : 'far') + ' fa-bookmark');
        if (modal) button.find('span').text(saved ? 'Saved to watchlist' : 'Save to watchlist');
    }

    function syncWatchlistControls() {
        $('#watchlist-count').text(watchlistReady ? watchlist.length : '–');
        $('#show-watchlist').attr('aria-label', watchlistReady ? 'Watchlist, ' + watchlist.length + ' saved' : 'Watchlist');
        $('.movie-save').each(function () { styleSaveButton($(this), $(this).data('movie')); });
        if (currentMovie) styleSaveButton($('#addToWatchlistBtn'), currentMovie, true);
        $('#clear-watchlist, #confirm-clear-watchlist').prop('disabled', watchlistBusy);
    }

    function showWatchlist() {
        $(document).trigger('cinewatch:watchlist');
        $('#watchlist-section').removeClass('d-none');
        $('#clear-watchlist-prompt').prop('hidden', true);
        displayWatchlist();
        document.getElementById('watchlist-heading').focus({preventScroll: true});
        document.getElementById('watchlist-section').scrollIntoView({block: 'start'});
        if (!watchlistReady && !watchlistBusy) loadWatchlist();
    }

    function displayWatchlist() {
        if ($('#watchlist-section').hasClass('d-none')) return;
        const container = $('#watchlist-container').empty();
        watchlist.forEach(movie => container.append(createMovieCard(movie)));
        $('#clear-watchlist').prop('hidden', !watchlist.length || !watchlistReady);
        $('#watchlist-empty').prop('hidden', !watchlistReady || watchlist.length > 0);
        $('#watchlist-state').prop('hidden', watchlistReady)
            .text(watchlistBusy ? 'Loading saved movies…' : 'Your saved movies could not be loaded.');
        $('#watchlist-load-retry').prop('hidden', watchlistReady || watchlistBusy);
    }

    function saveMovie(movie) {
        if (!movie || watchlistBusy) return;
        if (!watchlistReady) {
            loadWatchlist();
            return;
        }
        const remove = watchlist.some(item => sameFilm(item, movie));
        changeWatchlist(remove ? 'DELETE' : 'POST', remove ? {id: movie.id, title: movie.title} : {movie},
            () => {
                watchlist = remove ? watchlist.filter(item => !sameFilm(item, movie)) : [...watchlist, movie];
                return remove ? 'Removed from watchlist' : 'Saved to watchlist';
            });
    }

    function changeWatchlist(method, data, apply) {
        if (watchlistBusy) return;
        const active = document.activeElement;
        const wasInList = document.getElementById('watchlist-section').contains(active);
        const oldIndex = $('#watchlist-container .movie-save').index(active);
        watchlistBusy = true;
        syncWatchlistControls();
        $.ajax({url: '/watchlist', method, contentType: 'application/json', data: JSON.stringify(data)})
            .done(function () {
                const message = apply();
                $('#clear-watchlist-prompt').prop('hidden', true);
                watchlistBusy = false;
                syncWatchlistControls();
                displayWatchlist();
                if (wasInList) {
                    const buttons = $('#watchlist-container .movie-save');
                    const target = oldIndex >= 0 && buttons.length ? buttons.get(Math.min(oldIndex, buttons.length - 1)) : document.getElementById('watchlist-heading');
                    target.focus({preventScroll: true});
                }
                watchlistNotice(message);
            }).fail(function (xhr) {
                // Re-read the session before the next write in case the response was lost.
                loadWatchlist().done(() => watchlistNotice(xhr.responseJSON?.error || 'Could not update your watchlist. Try again.'));
            });
    }

    function clearWatchlist() {
        if (!watchlist.length || watchlistBusy) return;
        $('#clear-watchlist-prompt').prop('hidden', false);
        $('#cancel-clear-watchlist').trigger('focus');
    }

    $('#cancel-clear-watchlist').on('click', function () {
        $('#clear-watchlist-prompt').prop('hidden', true);
        $('#clear-watchlist').trigger('focus');
    });
    $('#confirm-clear-watchlist').on('click', function () {
        changeWatchlist('DELETE', {clear: true}, () => { watchlist = []; return 'Watchlist cleared'; });
    });
    $('#watchlist-browse').on('click', () => $('#browse-movies').trigger('click'));
    $('#watchlist-load-retry').on('click', loadWatchlist);

    function watchTrailer() {
        if (!currentMovie) return;
        const title = currentMovie.title;
        const panel = $('#trailer-panel').prop('hidden', false);
        const youtubeSearch = 'https://www.youtube.com/results?' + new URLSearchParams({search_query: title + ' official trailer'});
        $('#trailer-link').attr('href', youtubeSearch);
        $('#trailer-status').text('Looking for a trailer…');
        $('#watchTrailerBtn').attr('aria-expanded', 'true').prop('disabled', true);
        $.post('/get_trailer', {title}).done(function (data) {
            if (currentMovie?.title !== title || panel.prop('hidden')) return;
            if (typeof data.video_id === 'string' && /^[\w-]{11}$/.test(data.video_id)) {
                $('#trailer-player').prop('hidden', false);
                $('#trailerIframe').attr('src', 'https://www.youtube.com/embed/' + data.video_id);
                $('#trailer-status').text('');
            } else {
                $('#trailer-status').text('Find the official trailer on YouTube.');
            }
        }).fail(function () {
            if (currentMovie?.title === title) $('#trailer-status').text('Trailer lookup is unavailable. You can still search YouTube.');
        });
    }

    function dismissSuggestions() {
        clearTimeout(typingTimer);
        typingTimer = null;
        if (suggestionRequest) {
            suggestionRequest.abort();
            suggestionRequest = null;
        }
        selectedSuggestion = -1;
        suggestions.empty().addClass('d-none');
        searchInput.attr('aria-expanded', 'false').removeAttr('aria-activedescendant');
        $('#suggestion-status').empty();
    }

    function scheduleSuggestions() {
        dismissSuggestions();
        const query = searchInput.val().trim();
        if (query.length < 2) return;
        typingTimer = setTimeout(function() {
            typingTimer = null;
            const request = $.post('/search_suggestions', { query });
            suggestionRequest = request;
            request.done(function(titles) {
                if (suggestionRequest !== request || query !== searchInput.val().trim() || !searchInput.is(':focus')) return;
                titles.forEach(function(title, index) {
                    $('<div>', {
                        id: 'movie-suggestion-' + index, 'class': 'suggestion-item',
                        role: 'option', 'aria-selected': 'false', text: title
                    }).appendTo(suggestions);
                });
                if (titles.length) {
                    suggestions.removeClass('d-none');
                    searchInput.attr('aria-expanded', 'true');
                    $('#suggestion-status').text(titles.length + ' suggestions. Use the up and down arrows to select a title.');
                } else {
                    $('#suggestion-status').text('No suggestions. Press Enter to search the catalog.');
                }
            }).always(function() {
                if (suggestionRequest === request) suggestionRequest = null;
            });
        }, 140);
    }

    function chooseSuggestion(title) {
        searchInput.val(title);
        openView('search', title);
    }

    function updateGenreChips(genre) {
        $('.genre-icon').each(function() {
            const selected = this.dataset.genre === genre;
            $(this).toggleClass('active', selected).attr('aria-pressed', String(selected));
        });
    }

    function leaveDiscovery() {
        activeView = null;
        if (discoveryRequest) discoveryRequest.abort();
        discoveryRequest = null;
        $('#default-movies-section, #browse-section, #search-results, #recommendations-section')
            .addClass('d-none').removeAttr('aria-busy');
        $('#loading').addClass('d-none');
        $('#discovery-announcement').empty();
    }

    function openView(mode, value = '', movieId = null) {
        if (mode === 'recommend') {
            recommendationHistory.push({
                view: activeView, scrollY: window.scrollY,
                query: searchInput.val(), watchlist: $('#watchlist-section').is(':visible')
            });
        } else {
            recommendationHistory = [];
        }
        const sections = {
            default: '#default-movies-section', browse: '#browse-section',
            search: '#search-results', recommend: '#recommendations-section'
        };
        const section = $(sections[mode]);
        const view = { mode, value, movieId, section, grid: section.children('.row').first(), page: 0, movies: [], hasMore: false };
        activateView(view);
        if (mode !== 'default') scrollToResults(view);
        requestPage(view, 1);
    }

    function activateView(view) {
        leaveDiscovery();
        dismissSuggestions();
        activeView = view;
        $('#watchlist-section').addClass('d-none');
        updateGenreChips(view.mode === 'browse' || view.mode === 'default' ? view.value : null);
        const { mode, value, section, grid } = view;
        const heading = section.find('h2').first();
        if (mode === 'search') heading.text('Results for “' + value + '”');
        if (mode === 'recommend') heading.text('More like ' + value);
        if (mode === 'browse') heading.text(value ? value + ' films' : 'All films');
        heading.attr('tabindex', '-1');
        section.children('.discovery-back, .discovery-feedback').remove();
        if (mode === 'recommend' && recommendationHistory.length) {
            $('<button>', {
                type: 'button', 'class': 'discovery-back', text: '← Back to previous results'
            }).on('click', restorePreviousView).prependTo(section);
        }
        grid.empty();
        $('<div class="discovery-feedback"></div>').insertAfter(grid);
        section.removeClass('d-none');
    }

    function restorePreviousView() {
        const previous = recommendationHistory.pop();
        if (!previous) return;
        searchInput.val(previous.query);
        if (previous.watchlist) {
            $('#show-watchlist').trigger('click');
        } else if (previous.view) {
            activateView(previous.view);
            renderMovies(previous.view, previous.view.movies);
            renderFooter(previous.view);
            if (!previous.view.page) requestPage(previous.view, 1);
            previous.view.section.find('h2')[0]?.focus({ preventScroll: true });
        } else {
            openView('default');
        }
        requestAnimationFrame(() => window.scrollTo({ top: previous.scrollY, behavior: 'instant' }));
    }

    function scrollToResults(view) {
        const heading = view.section.find('h2')[0];
        if (heading) heading.focus({ preventScroll: true });
        view.section[0].scrollIntoView({ behavior: 'instant', block: 'start' });
    }

    function pageRequest(view, page) {
        if (view.mode === 'search') {
            return $.ajax({
                url: '/search?view=card', method: 'POST', contentType: 'application/json',
                data: JSON.stringify({ query: view.value, page })
            });
        }
        if (view.mode === 'recommend') return $.post('/recommend?view=card', { title: view.value, id: view.movieId });
        if (view.mode === 'default') return $.getJSON('/default_movies', { view: 'card' });
        return $.getJSON('/movies', { view: 'card', genre: view.value, page });
    }

    function requestPage(view, page) {
        if (activeView !== view || discoveryRequest) return;
        const footer = view.section.children('.discovery-feedback').empty();
        view.section.attr('aria-busy', 'true');
        if (page === 1) {
            $('#loading-text').text(view.mode === 'recommend' ? 'Finding similar films…' : 'Loading films…');
            $('#loading').insertAfter(view.grid).removeClass('d-none');
        } else {
            footer.text('Loading more films…');
        }
        discoveryRequest = pageRequest(view, page);
        discoveryRequest.done(function(movies) {
            if (activeView !== view) return;
            view.page = page;
            view.hasMore = (view.mode === 'browse' || view.mode === 'search') && movies.length === pageSize;
            view.movies.push(...movies);
            renderMovies(view, movies);
            renderFooter(view);
            $('#discovery-announcement').text(view.movies.length + ' films shown.');
        }).fail(function(xhr, status) {
            if (activeView !== view || status === 'abort') return;
            footer.empty().append($('<p>', { role: 'alert', text: 'Films couldn’t be loaded. Please try again.' }));
            $('<button>', { type: 'button', 'class': 'btn btn-glass', text: 'Try again' })
                .on('click', () => requestPage(view, page)).appendTo(footer);
        }).always(function() {
            if (activeView !== view) return;
            discoveryRequest = null;
            view.section.attr('aria-busy', 'false');
            $('#loading').addClass('d-none');
        });
    }

    function renderMovies(view, movies) {
        const batch = document.createDocumentFragment();
        movies.forEach(movie => batch.append(createMovieCard(movie)[0]));
        view.grid.append(batch);
    }

    function renderFooter(view) {
        const footer = view.section.children('.discovery-feedback').empty();
        if (!view.movies.length) {
            const message = view.mode === 'search' ? 'No films matched “' + view.value + '”. Try another title.'
                : view.mode === 'recommend' ? 'No similar films found for this title.' : 'No films found.';
            $('<p>', { text: message }).appendTo(footer);
            const isSearch = view.mode === 'search';
            $('<button>', { type: 'button', 'class': 'btn btn-glass', text: isSearch ? 'Edit search' : 'Browse all films' })
                .on('click', () => isSearch ? searchInput.trigger('focus').trigger('select') : openView('browse'))
                .appendTo(footer);
        } else if (view.hasMore) {
            $('<button>', {
                type: 'button', 'class': 'btn btn-glass load-more-movies',
                id: view.mode === 'search' ? 'load-more-btn' : 'load-more-browse-btn', text: 'Load more films'
            }).on('click', () => requestPage(view, view.page + 1)).appendTo(footer);
        }
    }

    function posterUrl(path) {
        if (typeof path !== 'string' || !path.trim()) return '';
        try {
            const src = path.startsWith('/') && !path.startsWith('//') ? tmdbImageBaseUrl + path : path;
            const url = new URL(src);
            if (['http:', 'https:'].includes(url.protocol) && url.hostname !== 'fakeimg.pl') return url.href;
        } catch { /* Missing and malformed paths use the local poster treatment. */ }
        return '';
    }

    function setPoster(frame, movie, lazy) {
        const title = String(movie.title || '');
        let hash = 0;
        for (const char of title) hash = (hash * 31 + char.codePointAt(0)) >>> 0;
        frame.empty().attr('data-tone', hash % 6);
        $('<span class="missing-poster" aria-hidden="true">').text(title).appendTo(frame);
        const url = posterUrl(movie.poster_path);
        if (url) {
            const image = $('<img alt="" decoding="async" class="card-img-top">').attr('loading', lazy ? 'lazy' : 'eager')
                .on('load', function () { this.classList.add('is-loaded'); })
                .on('error', function () { this.remove(); });
            frame.append(image.attr('src', url));
        }
    }

    function ratingText(value) {
        const rating = Number(value);
        return Number.isFinite(rating) && rating > 0 ? rating.toFixed(1) : '';
    }

    function fillMovieDetails(movie) {
        $('#movieModalLabel').text(movie.title);
        $('#movieGenres').text(formatGenres(movie.genres));
        $('#movieOverview').text(movie.overview || 'An overview is unavailable for this film.');
        const rating = ratingText(movie.vote_average);
        $('#movieRating').prop('hidden', !rating).find('span').text(rating + ' / 10');
        $('#movieAgeRating').prop('hidden', !movie.age_rating || movie.age_rating === 'Not Rated').text(movie.age_rating);
        $('#movieYear').prop('hidden', !movie.year).text(movie.year || '');
        $('#movieRuntime').prop('hidden', !movie.runtime).text(movie.runtime ? movie.runtime + ' min' : '');
        for (const [field, selector] of [['directors', '#movieDirectors'], ['cast', '#movieCast']]) {
            const names = Array.isArray(movie[field]) ? movie[field].join(', ') : '';
            $(selector + 'Container').prop('hidden', !names);
            $(selector).text(names);
        }
        styleSaveButton($('#addToWatchlistBtn'), movie, true);
    }

    function showMovieModal(movie, trigger) {
        currentMovie = movie;
        modalOpener = trigger;
        const sequence = ++detailsSequence;
        setPoster($('#moviePoster'), movie, false);
        fillMovieDetails(movie);
        $('#trailer-panel, #trailer-player').prop('hidden', true);
        $('#watchTrailerBtn').attr('aria-expanded', 'false').prop('disabled', false);
        bootstrap.Modal.getOrCreateInstance(document.getElementById('movieModal')).show();
        $.getJSON('/movie_details', movie.id ? {id: movie.id} : {title: movie.title}).done(function (details) {
            if (sequence !== detailsSequence || !details?.title) return;
            currentMovie = {...movie, ...details};
            if (currentMovie.poster_path !== movie.poster_path) setPoster($('#moviePoster'), currentMovie, false);
            fillMovieDetails(currentMovie);
        });
    }

    $('#movieModal').on('hidden.bs.modal', function () {
        detailsSequence++;
        currentMovie = null;
        $('#trailerIframe').removeAttr('src');
        $('#trailer-panel').prop('hidden', true);
        if (modalOpener?.isConnected && document.activeElement === document.body) modalOpener.focus({preventScroll: true});
    });

    function getRecommendationsForModal() {
        if (!currentMovie) return;
        const { title, id } = currentMovie;
        const dialog = document.getElementById('movieModal');
        $(dialog).one('hidden.bs.modal', () => openView('recommend', title, id));
        bootstrap.Modal.getInstance(dialog).hide();
    }

    function createMovieCard(movie) {
        const column = $('<div class="col-6 col-md-4 col-lg-3 col-xl-2 mb-4">');
        const card = $('<article class="movie-card">').appendTo(column);
        const open = $('<button type="button" class="movie-open">')
            .attr('aria-label', 'View details for ' + movie.title)
            .on('click', function () { showMovieModal(movie, this); }).appendTo(card);
        const poster = $('<span class="card-img-container poster-frame">').appendTo(open);
        setPoster(poster, movie, true);
        const body = $('<span class="movie-caption">').appendTo(open);
        $('<span class="card-title">').text(movie.title).appendTo(body);
        const meta = $('<span class="movie-meta">').appendTo(body);
        if (movie.year) $('<span>').text(movie.year).appendTo(meta);
        if (movie.genres) $('<span class="movie-genre">').text(formatGenres(movie.genres).split(',')[0]).appendTo(meta);
        const rating = ratingText(movie.vote_average);
        if (rating) {
            const score = $('<span class="movie-score"><i class="fas fa-star" aria-hidden="true"></i></span>').attr('aria-label', 'Rated ' + rating + ' out of 10').appendTo(meta);
            score.append(document.createTextNode(rating));
        }
        const save = $('<button type="button" class="movie-save"><i aria-hidden="true"></i></button>')
            .data('movie', movie).on('click', () => saveMovie(movie)).appendTo(card);
        styleSaveButton(save, movie);
        return column;
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

});
