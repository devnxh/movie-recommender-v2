"""Public film reviews with one editable review per CineWatch account and film."""

import time

from flask import jsonify, request

from accounts import current_user_id, require_json_write, transaction


def register_reviews(app, find_movie):
    @app.route('/api/movies/<int:movie_id>/reviews', methods=['GET', 'PUT', 'DELETE'])
    def movie_reviews(movie_id):
        if find_movie(movie_id).empty:
            return jsonify(error='Film not found.'), 404

        user_id = current_user_id()
        if request.method in ('PUT', 'DELETE'):
            # JSON may escape each of the 1,200 allowed characters as a surrogate pair.
            request.max_content_length = 16 * 1024
            denied = require_json_write()
            if denied is not None:
                return denied
            if user_id is None:
                return jsonify(error='Sign in to review this film.'), 401

        if request.method == 'PUT':
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify(error='Enter a rating and review.'), 400
            rating = data.get('rating')
            body = data.get('body')
            if type(rating) is not int or not 1 <= rating <= 10:
                return jsonify(error='Choose a rating from 1 to 10.'), 400
            if not isinstance(body, str) or not 1 <= len(body.strip()) <= 1200:
                return jsonify(error='Write a review of up to 1,200 characters.'), 400

        with transaction() as query:
            if request.method == 'PUT':
                query(
                    'INSERT INTO cw_reviews (movie_id, user_id, rating, body, updated_at) VALUES (?, ?, ?, ?, ?) '
                    'ON CONFLICT (movie_id, user_id) DO UPDATE SET rating=excluded.rating, '
                    'body=excluded.body, updated_at=excluded.updated_at',
                    (movie_id, user_id, rating, body.strip(), int(time.time())),
                )
            elif request.method == 'DELETE':
                query('DELETE FROM cw_reviews WHERE movie_id=? AND user_id=?', (movie_id, user_id))

            rows = query(
                'SELECT u.username, r.rating, r.body, r.updated_at FROM cw_reviews r '
                'JOIN cw_users u ON u.id=r.user_id WHERE r.movie_id=? '
                'ORDER BY r.updated_at DESC, r.user_id DESC LIMIT 10', (movie_id,),
            ).fetchall()
            mine = None
            if user_id is not None:
                own_row = query(
                    'SELECT rating, body FROM cw_reviews WHERE movie_id=? AND user_id=?', (movie_id, user_id),
                ).fetchone()
                if own_row:
                    mine = {'rating': own_row[0], 'body': own_row[1]}
        response = jsonify(
            reviews=[{'author': author, 'rating': rating, 'body': body, 'updated_at': updated}
                     for author, rating, body, updated in rows], mine=mine,
        )
        response.headers['Cache-Control'] = 'private, no-store'
        return response
