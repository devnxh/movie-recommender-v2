(() => {
    const input = document.getElementById('search-input');
    const genres = document.getElementById('additional-genres');
    const toggle = document.getElementById('toggle-genres');

    toggle.addEventListener('click', () => {
        genres.hidden = !genres.hidden;
        toggle.setAttribute('aria-expanded', String(!genres.hidden));
    });

    function focusSearch() {
        input.scrollIntoView({ block: 'center', behavior: 'instant' });
        input.focus({ preventScroll: true });
        input.select();
    }

    document.getElementById('quick-search').addEventListener('click', focusSearch);
    document.addEventListener('keydown', (event) => {
        if (event.defaultPrevented || event.isComposing || event.repeat || document.querySelector('.modal.show')) return;
        if (event.key !== '/' || event.altKey || event.ctrlKey || event.metaKey) return;
        if (event.target.closest('input, textarea, select, [contenteditable]')) return;
        event.preventDefault();
        focusSearch();
    });
})();
