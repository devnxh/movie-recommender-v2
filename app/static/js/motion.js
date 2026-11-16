/*
 * CineWatch motion: small, deliberate animations.
 * - Movie cards reveal with a "shutter" wipe as they scroll into view, staggered per batch.
 * - The nav firms up once the page is scrolled.
 * Everything is skipped when the user prefers reduced motion.
 */
(function () {
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    /* ---------- Nav state on scroll ---------- */
    const nav = document.querySelector('.site-nav');
    if (nav) {
        const onScroll = () => nav.classList.toggle('is-scrolled', window.scrollY > 8);
        onScroll();
        window.addEventListener('scroll', onScroll, { passive: true });
    }

    if (reduceMotion || !('IntersectionObserver' in window) || !('MutationObserver' in window)) {
        return;
    }

    /* ---------- Card reveal ---------- */
    const STAGGER_MS = 55;
    const MAX_STAGGER_STEPS = 7;
    const REVEAL_MS = 950; // longest transition in .movie-card.reveal (see style.css)

    const revealObserver = new IntersectionObserver((entries) => {
        // Stagger cards that enter the viewport together, left to right
        const entering = entries
            .filter((entry) => entry.isIntersecting)
            .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top
                || a.boundingClientRect.left - b.boundingClientRect.left);

        entering.forEach((entry, i) => {
            const card = entry.target;
            const delay = Math.min(i, MAX_STAGGER_STEPS) * STAGGER_MS;
            card.style.setProperty('--reveal-delay', `${delay}ms`);
            card.classList.add('in-view');
            revealObserver.unobserve(card);

            // Hand the card back to its normal hover styles once the reveal is done
            setTimeout(() => {
                card.classList.remove('reveal', 'in-view');
                card.style.removeProperty('--reveal-delay');
            }, delay + REVEAL_MS);
        });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.12 });

    const prepare = (root) => {
        const cards = root.matches && root.matches('.movie-card')
            ? [root]
            : Array.from(root.querySelectorAll ? root.querySelectorAll('.movie-card') : []);
        cards.forEach((card) => {
            if (card.dataset.revealReady) return;
            card.dataset.revealReady = '1';
            card.classList.add('reveal');
            revealObserver.observe(card);
        });
    };

    // Cards are created by main.js after AJAX calls, so watch for them
    new MutationObserver((mutations) => {
        mutations.forEach((m) => m.addedNodes.forEach((node) => {
            if (node.nodeType === 1) prepare(node);
        }));
    }).observe(document.querySelector('main') || document.body, { childList: true, subtree: true });

    prepare(document);
})();
