(() => {
    const byId = (id) => document.getElementById(id);
    const panel = byId('movie-reviews');
    const status = byId('review-status');
    const write = byId('write-review');
    const retry = byId('review-retry');
    const form = byId('review-form');
    const rating = byId('review-rating');
    const body = byId('review-body');
    const remove = byId('delete-review');
    const viewerReviews = byId('viewer-reviews');
    let movieId = null;
    let account = null;
    let mine = null;
    let revision = 0;
    let loaded = false;
    let pendingEditor = null;

    function reviewCard(author, text) {
        const article = document.createElement('article');
        const heading = document.createElement('strong');
        const paragraph = document.createElement('p');
        heading.textContent = author;
        paragraph.textContent = text;
        article.append(heading, paragraph);
        return article;
    }

    function showTMDB(movie) {
        const articles = [];
        const reviews = Array.isArray(movie.tmdb_reviews) ? movie.tmdb_reviews : [];
        for (const review of reviews) {
            if (typeof review?.excerpt !== 'string' || !review.excerpt.trim()) continue;
            const author = typeof review.author === 'string' && review.author.trim() ? review.author : 'TMDB member';
            const article = reviewCard(author, review.excerpt);
            if (typeof review.url === 'string' && /^https:\/\/www\.themoviedb\.org\/review\/[a-zA-Z0-9]+$/.test(review.url)) {
                const link = document.createElement('a');
                link.href = review.url;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                link.textContent = 'Full review';
                article.append(link);
            }
            articles.push(article);
        }
        byId('tmdb-reviews').replaceChildren(...articles);
        byId('tmdb-reviews-link').href = 'https://www.themoviedb.org/movie/' + encodeURIComponent(movie.id) + '/reviews';
    }

    function openEditor(draft) {
        const values = draft || mine;
        rating.value = values?.rating ?? '';
        body.value = values?.body ?? '';
        form.hidden = false;
        write.hidden = true;
        remove.hidden = !mine;
        form.querySelector('[type="submit"]').textContent = mine ? 'Save changes' : 'Publish review';
        rating.focus();
    }

    function signIn(expired = false) {
        pendingEditor = {movieId, userId: account?.user?.id, draft: expired ? {rating: rating.value, body: body.value} : null};
        document.dispatchEvent(new CustomEvent('cinewatch:signin-for-review', {detail: {expired}}));
    }

    function reset() {
        revision++;
        loaded = false;
        mine = null;
        viewerReviews.replaceChildren();
        status.textContent = '';
        write.hidden = retry.hidden = form.hidden = true;
        form.reset();
        for (const input of form.elements) input.disabled = false;
    }

    async function load(method = 'GET', data, message) {
        if (!movieId) return;
        const version = ++revision;
        write.hidden = retry.hidden = true;
        if (account?.available === false) {
            status.textContent = 'CineWatch reviews are currently unavailable.';
            return;
        }
        const reading = method === 'GET';
        const options = {method, cache: 'no-store'};
        if (!reading) {
            options.headers = {'Content-Type': 'application/json'};
            options.body = JSON.stringify(data);
            for (const input of form.elements) input.disabled = true;
        }
        status.textContent = reading ? 'Loading reviews…' : 'Saving changes…';
        try {
            const response = await fetch('/api/movies/' + movieId + '/reviews', options);
            const result = await response.json().catch(() => ({}));
            if (version !== revision) return;
            if (!reading && response.status === 401) {
                signIn(true);
                return;
            }
            if (!response.ok) throw new Error(response.status === 503 ? 'CineWatch reviews are currently unavailable.' : result.error || 'Could not load reviews.');
            mine = result.mine;
            loaded = true;
            form.hidden = true;
            viewerReviews.replaceChildren(...result.reviews.map(review =>
                reviewCard(review.author + ' · ' + review.rating + '/10', review.body)));
            status.textContent = message || (result.reviews.length ? '' : 'Be the first to review this film.');
            write.textContent = account?.user ? (mine ? 'Edit your review' : 'Write a review') : 'Sign in to review';
            write.hidden = false;
            if (!reading) write.focus();
            if (pendingEditor?.movieId === movieId) {
                const saved = pendingEditor;
                pendingEditor = null;
                if (account?.user) openEditor(saved.userId === account.user.id ? saved.draft : null);
            }
        } catch (error) {
            if (version !== revision) return;
            status.textContent = error.message || 'Could not load reviews. Try again.';
            retry.hidden = !reading;
        } finally {
            if (version === revision) for (const input of form.elements) input.disabled = false;
        }
    }

    document.addEventListener('cinewatch:movie', ({detail: movie}) => {
        if (movieId !== movie.id) {
            reset();
            movieId = movie.id;
            if (pendingEditor && pendingEditor.movieId !== movieId) pendingEditor = null;
            panel.open = Boolean(movieId && pendingEditor);
        }
        panel.hidden = !movieId;
        if (movieId) showTMDB(movie);
    });

    byId('movieModal').addEventListener('hidden.bs.modal', () => {
        reset();
        movieId = null;
        panel.open = false;
    });

    document.addEventListener('cinewatch:account', ({detail: next}) => {
        const changed = account?.user?.id !== next.user?.id || account?.available !== next.available;
        account = next;
        if (changed && movieId) {
            reset();
            if (panel.open && !pendingEditor) load();
        }
    });

    panel.addEventListener('toggle', () => {
        if (panel.open && !loaded) load();
    });
    write.addEventListener('click', () => {
        if (account?.user) {
            openEditor();
        } else {
            signIn();
        }
    });
    byId('cancel-review').addEventListener('click', () => {
        form.hidden = true;
        write.hidden = false;
        write.focus();
    });
    retry.addEventListener('click', () => load());
    form.addEventListener('submit', event => {
        event.preventDefault();
        if (!body.value.trim()) {
            status.textContent = 'Write a review before publishing.';
            body.focus();
            return;
        }
        load('PUT', {rating: Number(rating.value), body: body.value.trim()}, 'Your review was saved.');
    });
    remove.addEventListener('click', () => {
        if (window.confirm('Delete your review of this film?')) load('DELETE', {}, 'Your review was deleted.');
    });
})();
