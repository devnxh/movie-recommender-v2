$(function () {
    const pick = document.getElementById('pick-film');
    const another = document.getElementById('pick-another');
    const modal = document.getElementById('movieModal');
    let recentIds = [];
    let pending;

    function notice(element, message) {
        element.hidden = !message;
        element.textContent = message;
    }

    async function draw(button) {
        if (pending) return;
        const controller = new AbortController();
        pending = controller;
        const feedback = document.getElementById(button === another ? 'pick-again-status' : 'pick-status');
        const filters = new URLSearchParams(window.CineWatchFilters.current());
        const url = new URL('/api/surprise', window.location.origin);
        url.search = filters.toString();
        if (recentIds.length) url.searchParams.set('recent', recentIds.join(','));
        button.setAttribute('aria-busy', 'true');
        notice(feedback, 'Choosing a film…');
        try {
            const response = await fetch(url, {signal: controller.signal, cache: 'no-store'});
            if (!response.ok) throw new Error('Pick unavailable');
            const {movie, restarted, has_alternative} = await response.json();
            if (filters.toString() !== new URLSearchParams(window.CineWatchFilters.current()).toString()) {
                notice(feedback, 'Filters changed. Pick again for the new selection.');
                return;
            }
            if (!movie) {
                notice(feedback, 'No films match these filters. Try a wider year range or clear a filter.');
                return;
            }
            if (restarted) recentIds = [];
            if (movie.id) recentIds = [...recentIds.slice(-23), movie.id];
            notice(feedback, '');
            $(document).trigger('cinewatch:open-movie', [movie, pick, has_alternative]);
            if (button === another) {
                const title = document.getElementById('movieModalLabel');
                title.tabIndex = -1;
                title.focus({preventScroll: true});
                title.scrollIntoView({block: 'nearest'});
            }
        } catch (error) {
            notice(feedback, error.name === 'AbortError' ? '' : 'Couldn’t choose a film. Try again.');
        } finally {
            button.removeAttribute('aria-busy');
            if (pending === controller) pending = null;
        }
    }

    pick.addEventListener('click', () => draw(pick));
    another.addEventListener('click', () => draw(another));
    modal.addEventListener('hide.bs.modal', () => pending?.abort());
});
