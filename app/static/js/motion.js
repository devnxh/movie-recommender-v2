(function () {
    const gallery = document.querySelector('.motion-gallery');
    if (gallery) initGalleryMotion(gallery);

    /* ---------- Nav state on scroll ---------- */
    const nav = document.querySelector('.site-nav');
    if (nav) {
        const onScroll = () => nav.classList.toggle('is-scrolled', window.scrollY > 8);
        onScroll();
        window.addEventListener('scroll', onScroll, { passive: true });
    }

    function initGalleryMotion(gallery) {
        const video = gallery.querySelector('video');
        const toggle = gallery.querySelector('.motion-switch');
        const label = toggle.querySelector('.motion-switch-label');
        const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
        let enabled = !preference.matches;
        let visible = !('IntersectionObserver' in window);

        function syncMotion() {
            const running = enabled && visible && !document.hidden;
            gallery.classList.toggle('motion-running', running);
            toggle.classList.toggle('shows-play', !enabled);
            label.textContent = enabled ? 'Pause motion' : 'Play motion';
            if (running) {
                if (!video.src) video.src = video.dataset.src;
                // Autoplay restrictions leave the poster frame visible.
                video.play().catch(() => {});
            } else {
                video.pause();
            }
        }

        toggle.hidden = false;
        toggle.addEventListener('click', () => {
            enabled = !enabled;
            syncMotion();
        });
        preference.addEventListener('change', () => {
            enabled = !preference.matches;
            syncMotion();
        });
        document.addEventListener('visibilitychange', syncMotion);
        if ('IntersectionObserver' in window) {
            new IntersectionObserver(([entry]) => {
                visible = entry.isIntersecting;
                syncMotion();
            }).observe(gallery);
        }
        syncMotion();
    }
})();
