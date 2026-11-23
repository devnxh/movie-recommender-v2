(() => {
    const nav = document.querySelector('.site-nav');
    const hero = document.querySelector('.orbit-hero');
    const gallery = document.querySelector('.motion-gallery');
    const toggles = document.querySelectorAll('.motion-switch');
    const video = gallery?.querySelector('video');
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
    let enabled = !preference.matches;
    let heroVisible = false;
    let galleryVisible = false;
    let pointer = null;
    let frame = 0;

    function paintDepth() {
        frame = 0;
        if (!hero || !heroVisible || !enabled || document.hidden) return;
        const box = hero.getBoundingClientRect();
        const offsetX = pointer ? ((pointer.x - box.left) / box.width - 0.5) * 12 : 0;
        const offsetY = pointer ? ((pointer.y - box.top) / box.height - 0.5) * 8 : 0;
        const scroll = Math.min(1, Math.max(0, -box.top / box.height));
        hero.style.setProperty('--orbit-x', offsetX.toFixed(2) + 'px');
        hero.style.setProperty('--orbit-y', (offsetY + scroll * 16).toFixed(2) + 'px');
    }

    function queueDepth() {
        if (heroVisible && enabled && !document.hidden && !frame) {
            frame = window.requestAnimationFrame(paintDepth);
        }
    }

    function syncPlayback() {
        document.documentElement.classList.toggle('cinema-motion-on', enabled && !document.hidden);
        const heroRunning = enabled && heroVisible && !document.hidden;
        const galleryRunning = enabled && galleryVisible && !document.hidden;
        hero?.classList.toggle('motion-running', heroRunning);
        gallery?.classList.toggle('motion-running', galleryRunning);
        if (heroRunning) {
            hero.classList.add('motion-introduced');
            queueDepth();
        }
        if (galleryRunning) {
            gallery.classList.add('posters-introduced');
            if (video?.paused) {
                if (!video.src) video.src = video.dataset.src;
                // Keep the still artwork when a browser declines muted playback.
                video.play().catch(() => {});
            }
        } else {
            video?.pause();
        }
        toggles.forEach((toggle) => {
            toggle.classList.toggle('shows-play', !enabled);
            toggle.querySelector('.motion-switch-label').textContent = enabled ? 'Pause motion' : 'Play motion';
        });
    }

    let navScrolled = false;
    function onScroll() {
        const scrolled = window.scrollY > 8;
        if (scrolled !== navScrolled) {
            nav?.classList.toggle('is-scrolled', scrolled);
            navScrolled = scrolled;
        }
        queueDepth();
    }
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });

    toggles.forEach((toggle) => {
        toggle.hidden = false;
        toggle.addEventListener('click', () => {
            enabled = !enabled;
            syncPlayback();
        });
    });
    preference.addEventListener('change', () => {
        enabled = !preference.matches;
        pointer = null;
        syncPlayback();
    });
    document.addEventListener('visibilitychange', syncPlayback);
    hero?.addEventListener('pointermove', (event) => {
        if (!enabled || !finePointer.matches || event.pointerType === 'touch') return;
        pointer = { x: event.clientX, y: event.clientY };
        queueDepth();
    }, { passive: true });
    hero?.addEventListener('pointerleave', () => {
        pointer = null;
        queueDepth();
    });

    if ('IntersectionObserver' in window) {
        const observer = new IntersectionObserver((entries) => {
            for (const entry of entries) {
                if (entry.target === hero) heroVisible = entry.isIntersecting;
                if (entry.target === gallery) galleryVisible = entry.isIntersecting;
            }
            syncPlayback();
        });
        if (hero) observer.observe(hero);
        if (gallery) observer.observe(gallery);
    } else {
        heroVisible = Boolean(hero);
        galleryVisible = Boolean(gallery);
    }
    syncPlayback();
})();
