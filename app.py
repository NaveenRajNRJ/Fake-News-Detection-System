from flask import Flask, render_template, request, redirect, url_for, session, flash
import pickle
import pandas as pd
import sqlite3
import hashlib
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'  # Change this in production!

# Configure maximum file size (set to unlimited by removing the limit)
app.config['MAX_CONTENT_LENGTH'] = None  # Remove file size limit

# Load model and vectorizer
model = pickle.load(open('model.pkl', 'rb'))
vectorizer = pickle.load(open('vectorizer.pkl', 'rb'))

# Database initialization
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            news TEXT NOT NULL,
            prediction TEXT NOT NULL,
            confidence REAL,
            category TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    conn.close()

# Hash password function
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Check if user is logged in
def is_logged_in():
    return 'user_id' in session

# Initialize database on startup
init_db()

# ---------------- Authentication Routes ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username and password:
            conn = sqlite3.connect('users.db')
            cursor = conn.cursor()
            cursor.execute('SELECT id, username, password FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
            conn.close()
            
            if user and user[2] == hash_password(password):
                session['user_id'] = user[0]
                session['username'] = user[1]
                flash('Login successful!', 'success')
                return redirect(url_for('home'))
            else:
                flash('Invalid username or password!', 'error')
        else:
            flash('Please fill in all fields!', 'error')
    
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if username and email and password and confirm_password:
            if password != confirm_password:
                flash('Passwords do not match!', 'error')
            elif len(password) < 6:
                flash('Password must be at least 6 characters long!', 'error')
            else:
                conn = sqlite3.connect('users.db')
                cursor = conn.cursor()
                try:
                    cursor.execute('INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
                                 (username, email, hash_password(password)))
                    conn.commit()
                    flash('Account created successfully! Please login.', 'success')
                    conn.close()
                    return redirect(url_for('login'))
                except sqlite3.IntegrityError:
                    flash('Username or email already exists!', 'error')
                    conn.close()
        else:
            flash('Please fill in all fields!', 'error')
    
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully!', 'success')
    return redirect(url_for('login'))

# ---------------- Single News ----------------
@app.route('/', methods=['GET', 'POST'])
def home():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    prediction_text = None
    category_text = None
    confidence_text = None
    news_input = None
    feedback_msg = None

    if request.method == 'POST':
        news_input = request.form.get('news')
        if news_input:
            vect = vectorizer.transform([news_input])
            prediction = model.predict(vect)[0]
            confidence = model.decision_function(vect)[0]
            confidence_score = round(abs(confidence)*100, 2)
            confidence_text = f"Confidence Score: {confidence_score}%"
            category_text = "Category: General"
            prediction_text = f"The news is: {prediction}"
            
            # Store prediction in database
            conn = sqlite3.connect('users.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO predictions (user_id, news, prediction, confidence, category)
                VALUES (?, ?, ?, ?, ?)
            ''', (session['user_id'], news_input, prediction, confidence_score, 'General'))
            conn.commit()
            conn.close()

    return render_template('index.html',
                           prediction_text=prediction_text,
                           category_text=category_text,
                           confidence_text=confidence_text,
                           news_input=news_input,
                           feedback_msg=feedback_msg,
                           username=session.get('username'))

# ---------------- Dashboard Route ----------------
@app.route('/dashboard')
def dashboard():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    # You can add more dashboard statistics here
    # For now, it redirects to bulk analysis
    return redirect(url_for('bulk_news'))
@app.route('/bulk', methods=['GET', 'POST'])
def bulk_news():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    result = None
    error = None

    if request.method == 'POST':
        try:
            file = request.files.get('file')
            if not file:
                error = "Please upload a CSV file."
                return render_template('bulk.html', result=result, error=error, username=session.get('username'))

            df = pd.read_csv(file)

            # Detect the text column automatically
            possible_columns = ['news', 'text', 'article', 'content', 'headline']
            column_found = None
            for col in df.columns:
                if col.strip().lower() in [c.lower() for c in possible_columns]:
                    column_found = col
                    break

            if not column_found:
                error = f"No valid text column found. Rename your column to one of {possible_columns}"
                return render_template('bulk.html', result=result, error=error, username=session.get('username'))

            news_list = df[column_found].dropna().astype(str).tolist()
            vect = vectorizer.transform(news_list)
            predictions = model.predict(vect)
            result = list(zip(news_list, predictions))

        except Exception as e:
            error = f"Error processing file: {e}"

    return render_template('bulk.html', result=result, error=error, username=session.get('username'))

# ---------------- Feedback ----------------
@app.route('/feedback', methods=['POST'])
def feedback():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    news = request.form.get('news')
    user_feedback = request.form.get('feedback')
    feedback_msg = None

    if news and user_feedback:
        # Save feedback in a text file (or DB)
        with open('feedback.txt', 'a') as f:
            f.write(f"User: {session.get('username')}\nNews: {news}\nFeedback: {user_feedback}\nDate: {datetime.now()}\n\n")
        feedback_msg = "✅ Thank you for your feedback!"
    else:
        feedback_msg = "⚠ Feedback could not be submitted."

    return render_template('index.html', feedback_msg=feedback_msg, username=session.get('username'))

# ---------------- History Route ----------------
@app.route('/history')
def history():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT news, prediction, confidence, category, timestamp
        FROM predictions
        WHERE user_id = ?
        ORDER BY timestamp DESC
        LIMIT 10
    ''', (session['user_id'],))
    
    predictions = cursor.fetchall()
    conn.close()
    
    history_data = []
    for pred in predictions:
        history_data.append({
            'news': pred[0],
            'prediction': pred[1],
            'confidence': f"{pred[2]}%" if pred[2] else None,
            'category': pred[3],
            'timestamp': pred[4]
        })
    
    return render_template('history.html', history=history_data, username=session.get('username'))

if __name__ == '__main__':
    app.run(debug=True)
