import os
import sqlite3
import psycopg2
from psycopg2 import extras
import hashlib
import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')

# =======================================================
# Datenbank-Konfiguration
# Wählt automatisch die richtige Datenbank basierend auf der Umgebungsvariable
# =======================================================
def get_db_connection():
    """Stellt die Verbindung zur richtigen Datenbank her"""
    if os.environ.get('DATABASE_URL'):
        # PostgreSQL für die Produktion (z.B. auf Render)
        conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
        # Verwende DictCursor, um die Ausgabe wie bei sqlite3.Row zu erhalten
        return conn, conn.cursor(cursor_factory=extras.DictCursor)
    else:
        # SQLite für die lokale Entwicklung
        conn = sqlite3.connect('app.db')
        conn.row_factory = sqlite3.Row
        return conn, conn.cursor()

def init_db():
    """Datenbank und Tabellen initialisieren"""
    conn, cur = get_db_connection()

    if isinstance(conn, psycopg2.extensions.connection):
        # SQL-Anweisungen für PostgreSQL
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                author_id INTEGER,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (author_id) REFERENCES users (id)
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS todos (
                id SERIAL PRIMARY KEY,
                task TEXT NOT NULL,
                completed BOOLEAN DEFAULT FALSE,
                user_id INTEGER,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
    else:
        # SQL-Anweisungen für SQLite
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                author_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (author_id) REFERENCES users (id)
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task TEXT NOT NULL,
                completed BOOLEAN DEFAULT FALSE,
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

    conn.commit()
    cur.close()
    conn.close()

def hash_password(password):
    """Passwort hashen"""
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    """Decorator für geschützte Routen"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Bitte loggen Sie sich ein.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# === ROUTEN ===

@app.route('/')
def index():
    """Startseite mit aktuellen Blog-Posts"""
    conn, cur = get_db_connection()
    cur.execute('''
        SELECT p.*, u.username 
        FROM posts p 
        JOIN users u ON p.author_id = u.id 
        ORDER BY p.created_at DESC 
        LIMIT 5
    ''')
    posts = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('index.html', posts=posts)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Benutzerregistrierung"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        
        if not username or not password:
            flash('Benutzername und Passwort sind erforderlich!', 'error')
            return render_template('register.html')
        
        conn, cur = get_db_connection()
        try:
            cur.execute(
                'INSERT INTO users (username, password_hash, email) VALUES (%s, %s, %s)',
                (username, hash_password(password), email)
            )
            conn.commit()
            flash('Registrierung erfolgreich!', 'success')
            return redirect(url_for('login'))
        except (sqlite3.IntegrityError, psycopg2.errors.UniqueViolation):
            conn.rollback()
            flash('Benutzername bereits vergeben!', 'error')
        finally:
            cur.close()
            conn.close()
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Benutzeranmeldung"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn, cur = get_db_connection()
        cur.execute(
            'SELECT * FROM users WHERE username = %s AND password_hash = %s',
            (username, hash_password(password))
        )
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('Erfolgreich eingeloggt!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Ungültige Anmeldedaten!', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Benutzer abmelden"""
    session.clear()
    flash('Erfolgreich abgemeldet!', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    """Benutzer-Dashboard"""
    conn, cur = get_db_connection()
    
    # Benutzer-Posts
    cur.execute(
        'SELECT * FROM posts WHERE author_id = %s ORDER BY created_at DESC',
        (session['user_id'],)
    )
    user_posts = cur.fetchall()
    
    # Benutzer-Todos
    cur.execute(
        'SELECT * FROM todos WHERE user_id = %s ORDER BY created_at DESC',
        (session['user_id'],)
    )
    todos = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('dashboard.html', posts=user_posts, todos=todos)

@app.route('/create_post', methods=['GET', 'POST'])
@login_required
def create_post():
    """Neuen Blog-Post erstellen"""
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        
        if not title or not content:
            flash('Titel und Inhalt sind erforderlich!', 'error')
            return render_template('create_post.html')
        
        conn, cur = get_db_connection()
        cur.execute(
            'INSERT INTO posts (title, content, author_id) VALUES (%s, %s, %s)',
            (title, content, session['user_id'])
        )
        conn.commit()
        cur.close()
        conn.close()
        
        flash('Post erfolgreich erstellt!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('create_post.html')

@app.route('/post/<int:post_id>')
def view_post(post_id):
    """Einzelnen Post anzeigen"""
    conn, cur = get_db_connection()
    cur.execute('''
        SELECT p.*, u.username 
        FROM posts p 
        JOIN users u ON p.author_id = u.id 
        WHERE p.id = %s
    ''', (post_id,))
    post = cur.fetchone()
    cur.close()
    conn.close()
    
    if not post:
        flash('Post nicht gefunden!', 'error')
        return redirect(url_for('index'))
    
    return render_template('post.html', post=post)

# === TODO API ROUTEN ===

@app.route('/api/todos', methods=['GET'])
@login_required
def api_get_todos():
    """Todos als JSON zurückgeben"""
    conn, cur = get_db_connection()
    cur.execute(
        'SELECT * FROM todos WHERE user_id = %s ORDER BY created_at DESC',
        (session['user_id'],)
    )
    todos = cur.fetchall()
    cur.close()
    conn.close()
    
    return jsonify([dict(todo) for todo in todos])

@app.route('/api/todos', methods=['POST'])
@login_required
def api_create_todo():
    """Neues Todo via API erstellen"""
    data = request.get_json()
    task = data.get('task')
    
    if not task:
        return jsonify({'error': 'Task ist erforderlich'}), 400
    
    conn, cur = get_db_connection()
    cur.execute(
        'INSERT INTO todos (task, user_id) VALUES (%s, %s) RETURNING id',
        (task, session['user_id'])
    )
    todo = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    
    return jsonify({'id': todo['id'], 'task': task, 'completed': False}), 201

@app.route('/api/todos/<int:todo_id>', methods=['PUT'])
@login_required
def api_update_todo(todo_id):
    """Todo aktualisieren (completed status)"""
    data = request.get_json()
    completed = data.get('completed', False)
    
    conn, cur = get_db_connection()
    cur.execute(
        'UPDATE todos SET completed = %s WHERE id = %s AND user_id = %s',
        (completed, todo_id, session['user_id'])
    )
    conn.commit()
    cur.close()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/todos/<int:todo_id>', methods=['DELETE'])
@login_required
def api_delete_todo(todo_id):
    """Todo löschen"""
    conn, cur = get_db_connection()
    cur.execute(
        'DELETE FROM todos WHERE id = %s AND user_id = %s',
        (todo_id, session['user_id'])
    )
    conn.commit()
    cur.close()
    conn.close()
    
    return jsonify({'success': True})

# === ERROR HANDLER ===

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

# === TEMPLATE FILTER ===

@app.template_filter('datetime')
def datetime_filter(value):
    """Datum formatieren"""
    if isinstance(value, str):
        # Annahme: PostgreSQL und SQLite speichern Datums-Strings in unterschiedlichen Formaten
        try:
            # Versuch, PostgreSQL-Format zu parsen
            value = datetime.datetime.fromisoformat(value)
        except ValueError:
            # Fallback für SQLite-Format
            value = datetime.datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    return value.strftime('%d.%m.%Y %H:%M')

if __name__ == '__main__':
    # Initialisierung der Datenbank
    init_db()
    
    # `debug=True` nur für lokale Entwicklung verwenden
    app.run(host='0.0.0.0', port=5000)