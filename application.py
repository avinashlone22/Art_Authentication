import os
from flask import Flask, render_template, redirect, url_for, flash, request, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import requests
import base64
import random
from datetime import datetime

# --- Flask application Setup ---
application = Flask(__name__)

# Ensure 'instance' folder exists for the database
if not os.path.exists(os.path.join(os.path.dirname(__file__), 'instance')):
    os.makedirs(os.path.join(os.path.dirname(__file__), 'instance'))

# --- Configuration Settings ---
basedir = os.path.abspath(os.path.dirname(__file__))  # Get the absolute path of the current directory
application.config['SECRET_KEY'] = 'your_secret_key'
application.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(basedir, 'instance', 'application.db')}"
application.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
application.config['PRICE_API'] = "https://gi96frqbc5.execute-api.eu-west-1.amazonaws.com"
application.config['AUTH_API'] = "https://rf83t8chb1.execute-api.eu-west-1.amazonaws.com"

# --- Local Storage Config ---
application.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads', 'images')  # Correct path
application.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Limit file size to 16MB
application.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}  # Allowed image file types

# Ensure that the upload folder exists
if not os.path.exists(application.config['UPLOAD_FOLDER']):
    os.makedirs(application.config['UPLOAD_FOLDER'])

# --- Extensions ---
db = SQLAlchemy(application)
login_manager = LoginManager(application)
login_manager.login_view = 'login'

# --- Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Artwork(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500), nullable=False)  # Storing local file path
    price = db.Column(db.Float)
    is_authenticated = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# --- File Upload Helper (Local Storage) ---
def upload_file_to_local(file_obj, upload_folder, filename):
    try:
        file_path = os.path.join(upload_folder, filename)
        file_obj.save(file_path)  # Save file
        return file_path  # Return the local path
    except Exception as e:
        print(f"Error uploading file: {e}")
        return None

# Serve images from local storage
@application.route('/uploads/images/<filename>')
def uploaded_file(filename):
    return send_from_directory(application.config['UPLOAD_FOLDER'], filename)

# --- User Loader ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Routes ---
@application.route('/')
def home():
    return render_template('home.html')

# Registration route
@application.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if username.isnumeric():
            flash("Username cannot be only numbers.", "danger")
            return redirect(url_for('register'))

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "danger")
            return redirect(url_for('register'))

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("Username already exists.", "danger")
            return redirect(url_for('register'))

        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash("Registration successful!", "success")
        return redirect(url_for('login'))

    return render_template('register.html')

# Login route
@application.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))

        flash('Invalid credentials', 'danger')

    return render_template('login.html')

# Logout route
@application.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

# Dashboard route
@application.route('/dashboard')
@login_required
def dashboard():
    artworks = Artwork.query.filter_by(user_id=current_user.id).all()
    return render_template('dashboard.html', artworks=artworks)

# Artwork creation route
@application.route('/create_artwork', methods=['GET', 'POST'])
@login_required
def create_artwork():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        image = request.files['image']

        # Generate a unique filename for the uploaded image
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = secure_filename(f"{timestamp}_{image.filename}")

        # Save the image to local storage
        image_url = upload_file_to_local(image, application.config['UPLOAD_FOLDER'], filename)

        # Create artwork entry with the local image URL
        artwork = Artwork(
            title=title,
            description=description,
            image_url=f'/uploads/images/{filename}',  # Store the relative path to the image
            user_id=current_user.id
        )

        # Encoding the image for further processing (if needed)
        image.seek(0)  # Reset the file pointer after saving
        base64_image = base64.b64encode(image.read()).decode("utf-8")

        # PRICE_API and AUTH_API (same as before)
        try:
            price_res = requests.post(
                application.config['PRICE_API'],
                headers={'Content-Type': 'application/json'},
                json={"file": base64_image}
            )
            if price_res.status_code == 200:
                data = price_res.json()
                artwork.price = data.get("predicted_price", 0)
        except Exception as e:
            print(f"❌ PRICE_API error: {e}")

        try:
            auth_res = requests.post(
                application.config['AUTH_API'],
                headers={'Content-Type': 'application/json'},
                json={"file": base64_image}
            )
            if auth_res.status_code == 200:
                status = auth_res.json().get('status', '').lower()
                artwork.is_authenticated = status == "authentic"
        except Exception as e:
            print(f"❌ AUTH_API error: {e}")

        # Save artwork to the database
        db.session.add(artwork)
        db.session.commit()

        return render_template('artwork_details.html', artwork=artwork)

    return render_template('create_artwork.html')


# Generate artwork route
@application.route('/generate_artwork', methods=['GET', 'POST'])
@login_required
def generate_artwork():
    if request.method == 'POST':
        prompt = request.form['prompt']
        try:
            # 1. Generate image from Pollinations API
            image_url = f"https://image.pollinations.ai/prompt/{prompt.replace(' ', '%20')}"
            response = requests.get(image_url)
            image_data = response.content

            # 2. Save image temporarily
            filename = f"generated_{current_user.id}_{Artwork.query.count()}.jpg"
            image_path = os.path.join(application.config['UPLOAD_FOLDER'], filename)
            with open(image_path, 'wb') as f:
                f.write(image_data)

            # 3. Create the artwork entry with local image URL
            artwork = Artwork(
                title=f"AI Art: {prompt[:50]}",
                description=prompt,
                image_url=f'/uploads/images/{filename}',  # Store relative path to the image
                user_id=current_user.id
            )

            # 4. Encode image to base64 for API processing
            with open(image_path, 'rb') as img_file:
                base64_string = base64.b64encode(img_file.read()).decode('utf-8')

            # 5. PRICE_API request
            try:
                price_res = requests.post(
                    application.config['PRICE_API'],
                    headers={'Content-Type': 'application/json'},
                    json={'file': base64_string}  # Send base64 encoded image to Price API
                )
                print("PRICE_API response:", price_res.status_code, price_res.text)
                if price_res.status_code == 200:
                    data = price_res.json()
                    if 'predicted_price' in data:
                        artwork.price = data.get('predicted_price', 0)
                    else:
                        print("❌ PRICE_API did not return price.")
                else:
                    print("❌ PRICE_API response error:", price_res.status_code)
            except Exception as e:
                print("PRICE_API error:", e)

            # 6. AUTH_API request (same as before)
            try:
                auth_res = requests.post(
                    application.config['AUTH_API'],
                    headers={'Content-Type': 'application/json'},
                    json={'file': base64_string}  # Send base64 encoded image to Auth API
                )
                print("AUTH_API response:", auth_res.status_code, auth_res.text)
                if auth_res.status_code == 200:
                    status = auth_res.json().get('status', '').lower()
                    artwork.is_authenticated = status == "authentic"
            except Exception as e:
                print("AUTH_API error:", e)

            # 7. Save artwork to the database
            db.session.add(artwork)
            db.session.commit()

            return render_template('artwork_details.html', artwork=artwork)

        except Exception as e:
            flash(f'🎨 Artwork generation failed: {str(e)}', 'danger')
            return redirect(url_for('generate_artwork'))

    return render_template('generate_artwork.html')


# Get inspired route
@application.route('/get_inspired')
def get_inspired():
    try:
        page = random.randint(1, 100)
        url = f"https://api.artic.edu/api/v1/artworks?page={page}&limit=5&fields=id,title,image_id,artist_title,date_display"
        response = requests.get(url)
        data = response.json()

        artworks = []
        for item in data.get("data", []):
            image_id = item.get("image_id")
            if image_id:
                image_url = f"https://www.artic.edu/iiif/2/{image_id}/full/843,/0/default.jpg"
                artworks.append({
                    "title": item.get("title"),
                    "artist": item.get("artist_title") or "Unknown Artist",
                    "date": item.get("date_display") or "Unknown Date",
                    "image_url": image_url
                })

        return render_template("get_inspired.html", artworks=artworks)
    except Exception as e:
        flash(f"Failed to load inspirational art: {e}", "danger")
        return render_template("get_inspired.html", artworks=[])

# Delete artwork route
@application.route('/delete_artwork/<int:artwork_id>', methods=['POST'])
@login_required
def delete_artwork(artwork_id):
    # Fetch artwork by id, if not found it raises a 404 error
    artwork = Artwork.query.get_or_404(artwork_id)
    
    # Ensure the current user is the owner of the artwork
    if artwork.user_id != current_user.id:
        flash('You do not have permission to delete this artwork.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        # Construct the full file path using the file's name stored in the artwork object
        file_path = os.path.join(application.config['UPLOAD_FOLDER'], artwork.image_url.split('/')[-1])
        
        # If the image file exists in the local storage, delete it
        if os.path.exists(file_path):
            os.remove(file_path)  # Delete the file from local storage
            print(f"Deleted image file at {file_path}")
        else:
            print(f"File {file_path} not found.")
    
    except Exception as e:
        # In case there is an error deleting the file, print the error
        print(f"Error deleting from local storage: {e}")
    
    # Now delete the artwork from the database
    db.session.delete(artwork)
    db.session.commit()
    
    # Flash a success message
    flash('Artwork deleted successfully.', 'success')
    
    # Redirect back to the dashboard
    return redirect(url_for('dashboard'))

# --- Run ---
if __name__ == '__main__':
    with application.app_context():
        db.create_all()  # Create database tables if they don't exist
    application.run(host='0.0.0.0', port=5000, debug=True)  # Run the Flask app.
