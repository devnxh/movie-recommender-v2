(() => {
    const byId = (id) => document.getElementById(id);
    const emit = (name, detail) => document.dispatchEvent(new CustomEvent(name, {detail}));
    const entry = byId('account-entry');
    const dialog = byId('account-dialog');
    const form = byId('account-form');
    const username = byId('account-username');
    const password = byId('account-password');
    const message = byId('account-message');
    const favorite = byId('favorite-movie');
    const favoriteMessage = byId('favorite-message');

    let account = null;
    let currentMovie = null;
    let returnMovie = null;
    let favoriteAfterLogin = false;
    let register = false;
    let busy = false;

    async function request(url, method = 'GET', data = {}) {
        const options = {method, cache: 'no-store'};
        if (method !== 'GET') {
            options.headers = {'Content-Type': 'application/json'};
            options.body = JSON.stringify(data);
        }
        const response = await fetch(url, options);
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(result.error || 'The request could not be completed. Try again.');
            error.status = response.status;
            throw error;
        }
        return result;
    }

    function renderFavorite() {
        favorite.hidden = !account?.available || !currentMovie?.id;
        const saved = account?.favorite_ids?.includes(currentMovie?.id) || false;
        favorite.disabled = busy;
        favorite.setAttribute('aria-pressed', String(saved));
        favorite.querySelector('i').className = (saved ? 'fas' : 'far') + ' fa-heart';
        favorite.querySelector('span').textContent = saved ? 'Remove favorite' : 'Add to favorites';
    }

    function renderAccount() {
        entry.hidden = account?.available === false;
        const label = account?.user ? 'Your account' : 'Sign in';
        entry.setAttribute('aria-label', label);
        entry.querySelector('span').textContent = label;
        form.hidden = !account?.available || Boolean(account.user);
        byId('account-profile').hidden = !account?.user;
        const title = account?.user ? 'Your account' : register ? 'Create account' : 'Sign in';
        byId('account-title').textContent = account?.available ? title : 'Account';
        byId('account-intro').textContent = account?.user
            ? 'Signed in as ' + account.user.username
            : !account?.available ? 'Account access is currently unavailable.'
            : register ? 'Choose a username with 3–32 letters, numbers, underscores or hyphens, and a password of 10–128 characters.'
            : 'Keep your favorite films and get personal recommendations.';
        byId('account-submit').textContent = register ? 'Create account' : 'Sign in';
        byId('account-mode').textContent = register ? 'I already have an account' : 'Create an account';
        password.autocomplete = register ? 'new-password' : 'current-password';
        password.minLength = register ? 10 : 1;
        byId('account-retry').hidden = account !== null;
        [byId('account-submit'), byId('account-signout'), byId('account-mode'), byId('account-retry')].forEach(button => { button.disabled = busy; });
        renderFavorite();
    }

    async function refresh() {
        account = await request('/api/account');
        renderAccount();
        emit('cinewatch:account', account);
    }

    function openAccount() {
        register = false;
        form.reset();
        message.textContent = '';
        renderAccount();
        dialog.showModal();
        if (!form.hidden) username.focus();
    }

    function dismissAccount() {
        dialog.close();
    }

    entry.addEventListener('click', openAccount);
    byId('account-close').addEventListener('click', dismissAccount);
    dialog.addEventListener('close', () => {
        password.value = '';
        favoriteAfterLogin = false;
        if (returnMovie) {
            const film = returnMovie;
            returnMovie = null;
            emit('cinewatch:reopen-movie', film);
        }
    });

    byId('account-mode').addEventListener('click', () => {
        register = !register;
        password.value = '';
        message.textContent = '';
        renderAccount();
        username.focus();
    });
    byId('account-retry').addEventListener('click', () => {
        refresh().catch(() => { message.textContent = 'Could not connect. Try again.'; });
    });

    async function changeFavorite(movie, saved) {
        const result = await request('/api/favorites/' + movie.id, saved ? 'DELETE' : 'PUT');
        account.favorite_ids = result.favorite_ids;
        renderFavorite();
        emit('cinewatch:account', account);
        emit('cinewatch:favorite-changed', movie.id);
    }

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (busy) return;
        busy = true;
        renderAccount();
        message.textContent = register ? 'Creating your account…' : 'Signing in…';
        try {
            await request('/api/account/' + (register ? 'register' : 'login'), 'POST', {
                username: username.value.trim(), password: password.value
            });
            password.value = '';
            await refresh();
            if (favoriteAfterLogin && returnMovie) await changeFavorite(returnMovie, false);
            message.textContent = '';
            if (dialog.open) {
                const returning = Boolean(returnMovie);
                dismissAccount();
                if (!returning) emit('cinewatch:personal-view', 'for-you');
            }
        } catch (error) {
            message.textContent = error.message;
        } finally {
            busy = false;
            renderAccount();
        }
    });

    byId('account-signout').addEventListener('click', async () => {
        if (busy) return;
        busy = true;
        renderAccount();
        try {
            await request('/api/account/logout', 'POST');
            await refresh();
            dismissAccount();
        } catch (error) {
            message.textContent = error.message;
        } finally {
            busy = false;
            renderAccount();
        }
    });

    dialog.querySelectorAll('[data-personal-view]').forEach(button => {
        button.addEventListener('click', () => {
            returnMovie = null;
            dismissAccount();
            emit('cinewatch:personal-view', button.dataset.personalView);
        });
    });

    document.addEventListener('cinewatch:movie', (event) => {
        if (currentMovie?.id !== event.detail.id) favoriteMessage.textContent = '';
        currentMovie = event.detail;
        renderFavorite();
    });

    function signInFromDetails(saveFavorite) {
        if (!currentMovie?.id || account?.available === false) return;
        returnMovie = currentMovie;
        favoriteAfterLogin = saveFavorite;
        const details = byId('movieModal');
        details.addEventListener('hidden.bs.modal', openAccount, {once: true});
        bootstrap.Modal.getInstance(details).hide();
    }

    document.addEventListener('cinewatch:signin-for-review', (event) => {
        if (event.detail?.expired && account?.user) {
            account = {available: true, user: null, favorite_ids: []};
            renderAccount();
            emit('cinewatch:account', account);
        }
        signInFromDetails(false);
    });

    favorite.addEventListener('click', async () => {
        if (busy || !currentMovie?.id || !account?.available) return;
        if (!account.user) {
            signInFromDetails(true);
            return;
        }
        const movie = currentMovie;
        const saved = account.favorite_ids.includes(movie.id);
        busy = true;
        renderAccount();
        favoriteMessage.textContent = '';
        try {
            await changeFavorite(movie, saved);
            if (currentMovie?.id === movie.id) favoriteMessage.textContent = saved ? 'Favorite removed.' : 'Added to favorite films.';
        } catch (error) {
            if (error.status === 401) await refresh().catch(() => {});
            if (currentMovie?.id === movie.id) favoriteMessage.textContent = error.message;
        } finally {
            busy = false;
            renderAccount();
        }
    });

    refresh().catch(() => { account = null; renderAccount(); });
})();
