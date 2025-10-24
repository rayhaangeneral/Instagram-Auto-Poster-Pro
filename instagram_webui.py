import os
import json
import time
import threading
import random
import pathlib
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory
from werkzeug.utils import secure_filename
from uploader import main as run_uploader, load_config, get_instagram_client, load_upload_history, save_upload_history, add_to_upload_history, load_scheduled_posts, save_scheduled_posts, add_scheduled_post, remove_scheduled_post, clear_all_scheduled_posts, upload_single_image

app = Flask(__name__)
# Use a more secure secret key from environment variable or generate one
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(24)

# Configuration
UPLOAD_FOLDER = 'images'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Global variables to track the uploader status
upload_status = {
    "running": False,
    "message": "System ready for upload process",
    "log": []
}

# Store profile image URL
profile_image_url = None

# Locks for thread safety
status_lock = threading.Lock()
config_lock = threading.Lock()
schedule_lock = threading.Lock()

# Scheduled posts thread
scheduled_posts_thread = None
scheduled_posts_running = False

# Thread references for proper termination
uploader_thread = None
stop_event = threading.Event()

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def log_message(message):
    """Add a message to the log"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] - {message}"
    with status_lock:
        upload_status["log"].append(log_entry)
    print(log_entry)

def run_uploader_thread():
    """Run the uploader in a separate thread"""
    global upload_status
    try:
        with status_lock:
            upload_status["running"] = True
            upload_status["message"] = "Upload process initiated"
        log_message("Upload process initiated")
        
        # Check if config exists
        if not os.path.exists('config.json'):
            log_message("ERROR: config.json not found. Please configure the application first.")
            with status_lock:
                upload_status["running"] = False
                upload_status["message"] = "Configuration file missing"
            return
        
        # Check if config has valid credentials
        try:
            config = load_config()
            if config.get('instagram_username') == 'your_instagram_username' or \
               config.get('instagram_password') == 'your_instagram_password':
                log_message("ERROR: Please update config.json with your actual Instagram credentials")
                with status_lock:
                    upload_status["running"] = False
                    upload_status["message"] = "Invalid credentials in configuration"
                return
        except Exception as e:
            log_message(f"ERROR: Failed to load config: {str(e)}")
            with status_lock:
                upload_status["running"] = False
                upload_status["message"] = "Configuration load error"
            return
        
        # Check if stop was requested before starting
        if stop_event.is_set():
            log_message("Stop requested before starting upload process.")
            with status_lock:
                upload_status["running"] = False
                upload_status["message"] = "Upload process cancelled"
            return
        
        # Run the uploader with stop event checking
        run_uploader_with_stop_check()
        
        # Only set success message if not stopped
        if not stop_event.is_set():
            with status_lock:
                upload_status["message"] = "Upload process completed successfully"
            log_message("Upload process completed successfully")
    except Exception as e:
        if not stop_event.is_set():
            with status_lock:
                upload_status["message"] = f"Process error: {str(e)}"
            log_message(f"Process error: {str(e)}")
    finally:
        with status_lock:
            upload_status["running"] = False

def run_uploader_with_stop_check():
    """Run the uploader with periodic stop checking"""
    config = load_config()
    
    image_dir = pathlib.Path(config['image_directory'])
    uploaded_dir = pathlib.Path(config['uploaded_directory'])
    uploaded_dir.mkdir(exist_ok=True)
    
    log_file = config['log_file']

    def log_message(message):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] - {message}"
        print(log_entry)
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n')

    log_message("--- Starting Instagram Upload Script ---")
    
    try:
        client = get_instagram_client(config)
    except Exception as e:
        log_message(f"FATAL: Could not log in to Instagram. Error: {e}")
        return

    images_to_upload = sorted([f for f in image_dir.glob("*.png") if f.is_file()])
    
    if not images_to_upload:
        log_message("No new images found to upload.")
        return

    log_message(f"Found {len(images_to_upload)} images to process.")

    for image_path in images_to_upload:
        # Check if stop was requested
        if stop_event.is_set():
            log_message("Stop requested. Terminating upload process.")
            return
        
        log_message(f"Processing {image_path.name}...")
        
        success, status = upload_single_image(client, image_path, config)
        
        if success:
            log_message(f"SUCCESS: Uploaded {image_path.name}.")
            
            # Add to upload history
            add_to_upload_history(image_path.name, "SUCCESS")
            
            # Move the file to prevent re-uploading
            image_path.rename(uploaded_dir / image_path.name)
            log_message(f"Moved {image_path.name} to uploaded directory.")
        else:
            log_message(f"ERROR: Failed to upload {image_path.name}. Error: {status}")
            # Add to upload history
            add_to_upload_history(image_path.name, status)
        
        # Check if stop was requested before waiting
        if stop_event.is_set():
            log_message("Stop requested. Terminating upload process.")
            return
        
        # IMPORTANT: Wait for a random, human-like interval
        delay = random.uniform(300, 900) # 5 to 15 minutes
        log_message(f"Waiting for {delay:.2f} seconds to avoid triggering bot detection...")
        
        # Break the sleep into smaller chunks to check for stop requests
        start_time = time.time()
        while time.time() - start_time < delay:
            # Check if stop was requested every second
            if stop_event.is_set():
                log_message("Stop requested during wait period. Terminating upload process.")
                return
            time.sleep(1)  # Check every second

def load_scheduled_posts_safe():
    """Thread-safe loading of scheduled posts"""
    with schedule_lock:
        return load_scheduled_posts()

def save_scheduled_posts_safe(scheduled_posts):
    """Thread-safe saving of scheduled posts"""
    with schedule_lock:
        save_scheduled_posts(scheduled_posts)

def run_scheduled_posts_thread():
    """Run scheduled posts in a separate thread"""
    global scheduled_posts_running
    scheduled_posts_running = True
    
    try:
        # Load configuration
        config = load_config()
        client = get_instagram_client(config)
        
        # Get image directories
        image_dir = config['image_directory']
        uploaded_dir = config['uploaded_directory']
        
        log_message("Scheduled posts monitoring thread started")
        
        while scheduled_posts_running and not stop_event.is_set():
            # Load scheduled posts (thread-safe)
            scheduled_posts = load_scheduled_posts_safe()
            
            # Check for posts that need to be uploaded
            current_time = datetime.now()
            posts_processed = 0
            
            for post in scheduled_posts:
                if post['status'] == 'pending':
                    scheduled_time = datetime.fromisoformat(post['scheduled_time'])
                    if current_time >= scheduled_time:
                        log_message(f"Processing scheduled post: {post['filename']} (scheduled for {post['scheduled_time']})")
                        
                        # Check if stop was requested
                        if stop_event.is_set():
                            log_message("Stop requested. Terminating scheduled posts process.")
                            return
                        
                        # Upload the post
                        image_path = os.path.join(app.config['UPLOAD_FOLDER'], post['filename'])
                        if os.path.exists(image_path):
                            success, status = upload_single_image(client, image_path, config)
                            
                            if success:
                                log_message(f"SCHEDULED UPLOAD SUCCESS: Uploaded {post['filename']}.")
                                # Add to upload history
                                add_to_upload_history(post['filename'], "SUCCESS (Scheduled)")
                                # Move the file to uploaded directory
                                destination_path = os.path.join(uploaded_dir, post['filename'])
                                if os.path.exists(destination_path):
                                    # If file already exists in uploaded directory, remove it first
                                    os.remove(destination_path)
                                os.rename(image_path, destination_path)
                                # Update status
                                post['status'] = 'posted'
                                posts_processed += 1
                            else:
                                log_message(f"SCHEDULED UPLOAD ERROR: Failed to upload {post['filename']}. Error: {status}")
                                # Add to upload history
                                add_to_upload_history(post['filename'], f"ERROR (Scheduled): {status}")
                                # Update status
                                post['status'] = f'error: {status}'
                                posts_processed += 1
                        else:
                            log_message(f"SCHEDULED UPLOAD ERROR: File {post['filename']} not found in {app.config['UPLOAD_FOLDER']}.")
                            post['status'] = 'error: file not found'
                            posts_processed += 1
            
            # Save updated scheduled posts if any were processed (thread-safe)
            if posts_processed > 0:
                save_scheduled_posts_safe(scheduled_posts)
                log_message(f"Processed {posts_processed} scheduled post(s)")
            
            # Check if stop was requested before sleeping
            if stop_event.is_set():
                log_message("Stop requested. Terminating scheduled posts process.")
                return
                
            # Sleep for a while before checking again
            # Break the sleep into smaller chunks to check for stop requests
            sleep_time = 60  # Check every minute
            sleep_interval = 5  # Check every 5 seconds during the sleep period
            
            for _ in range(0, sleep_time, sleep_interval):
                if not scheduled_posts_running or stop_event.is_set():
                    log_message("Stop requested. Terminating scheduled posts process.")
                    return
                time.sleep(sleep_interval)
            
    except Exception as e:
        if not stop_event.is_set():
            log_message(f"ERROR in scheduled posts thread: {str(e)}")
    finally:
        scheduled_posts_running = False
        log_message("Scheduled posts monitoring thread stopped")

@app.route('/')
def index():
    """Main page showing the control panel"""
    config_exists = os.path.exists('config.json')
    with status_lock:
        status = upload_status.copy()
    
    # Get list of uploaded files
    uploaded_files = []
    if os.path.exists(UPLOAD_FOLDER):
        uploaded_files = os.listdir(UPLOAD_FOLDER)
    
    global profile_image_url
    return render_template('premium_index.html', config_exists=config_exists, status=status, 
                          uploaded_files=uploaded_files, profile_image_url=profile_image_url)

@app.route('/schedule')
def schedule():
    """Schedule page for individual post scheduling"""
    config_exists = os.path.exists('config.json')
    
    # Get list of uploaded files from the images directory (ready to be scheduled)
    uploaded_files = []
    if os.path.exists(UPLOAD_FOLDER):
        uploaded_files = os.listdir(UPLOAD_FOLDER)
    
    # Get scheduled posts (thread-safe)
    with schedule_lock:
        scheduled_posts = load_scheduled_posts()
    
    global profile_image_url
    return render_template('premium_schedule.html', config_exists=config_exists, 
                          uploaded_files=uploaded_files, scheduled_posts=scheduled_posts, 
                          profile_image_url=profile_image_url)

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload"""
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file selected for upload"})
    
    files = request.files.getlist('file')  # Handle multiple files
    
    uploaded_files = []
    error_files = []
    
    for file in files:
        if file.filename == '':
            error_files.append("No file selected")
            continue
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename) if file.filename else 'unnamed'
            if filename:  # Check if filename is not empty
                try:
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    log_message(f"File uploaded successfully: {filename}")
                    uploaded_files.append(filename)
                except Exception as e:
                    error_files.append(f"{filename}: {str(e)}")
            else:
                error_files.append("Invalid filename detected")
        else:
            error_files.append(f"Invalid file type for {file.filename}. Only PNG, JPG, and JPEG files are allowed.")
    
    # Prepare response
    if uploaded_files and not error_files:
        return jsonify({"status": "success", "message": f"Successfully uploaded {len(uploaded_files)} file(s): {', '.join(uploaded_files)}"})
    elif uploaded_files and error_files:
        return jsonify({"status": "partial", "message": f"Uploaded {len(uploaded_files)} file(s): {', '.join(uploaded_files)}. Errors: {', '.join(error_files)}"})
    else:
        return jsonify({"status": "error", "message": f"Failed to upload files: {', '.join(error_files)}"})

@app.route('/start', methods=['POST'])
def start_upload():
    """Start the scheduled posts monitoring"""
    global scheduled_posts_thread, scheduled_posts_running
    
    # Check if scheduled posts thread is already running
    if scheduled_posts_running:
        return jsonify({"status": "error", "message": "Scheduled posts monitoring is already running"})
    
    # Start scheduled posts thread
    scheduled_posts_running = True
    scheduled_posts_thread = threading.Thread(target=run_scheduled_posts_thread)
    scheduled_posts_thread.start()
    
    log_message("Scheduled posts monitoring started via Start button")
    return jsonify({"status": "success", "message": "Scheduled posts monitoring started successfully"})

@app.route('/stop', methods=['POST'])
def stop_upload():
    """Stop the Instagram uploader immediately"""
    global upload_status, scheduled_posts_running, stop_event
    
    # Set the stop event to signal threads to stop
    stop_event.set()
    
    # Stop scheduled posts thread
    scheduled_posts_running = False
    
    # Update status
    with status_lock:
        if not upload_status["running"]:
            return jsonify({"status": "error", "message": "Upload process is not currently running"})
        
        upload_status["running"] = False
        upload_status["message"] = "Upload process stopped by user"
    
    log_message("Stop requested for upload process - All tasks terminated")
    return jsonify({"status": "success", "message": "Upload process stopped successfully"})

@app.route('/status')
def get_status():
    """Get the current status of the uploader"""
    with status_lock:
        return jsonify(upload_status)

@app.route('/config', methods=['GET', 'POST'])
def config_page():
    """Configuration page for setting up Instagram credentials and paths"""
    global profile_image_url
    
    if request.method == 'POST':
        # Save configuration from form
        config_data = {
            "instagram_username": request.form['instagram_username'],
            "instagram_password": request.form['instagram_password'],
            "session_file": request.form['session_file'],
            "image_directory": request.form['image_directory'],
            "uploaded_directory": request.form['uploaded_directory'],
            "log_file": request.form['log_file']
        }
        
        # Encrypt sensitive fields before saving
        try:
            from encryption import encrypt_sensitive_data
            # Encrypt sensitive fields
            config_data['instagram_username'] = encrypt_sensitive_data(config_data['instagram_username'])
            config_data['instagram_password'] = encrypt_sensitive_data(config_data['instagram_password'])
        except ImportError:
            # If encryption module is not available, save as plain text (not recommended)
            pass
        except Exception:
            # If encryption fails, save as plain text (not recommended)
            pass
        
        with open('config.json', 'w') as f:
            json.dump(config_data, f, indent=4)
        
        # Try to fetch profile image after saving config
        try:
            config = load_config()
            client = get_instagram_client(config)
            user_info = client.account_info()
            if hasattr(user_info, 'profile_pic_url'):
                profile_image_url = user_info.profile_pic_url
        except Exception as e:
            log_message(f"Could not fetch profile image: {str(e)}")
        
        flash("Configuration saved successfully!")
        return redirect(url_for('config_page'))
    
    # Load existing configuration if it exists
    config = {}
    if os.path.exists('config.json'):
        try:
            config = load_config()
        except:
            # If there's an error loading config, use empty config
            config = {}
    
    return render_template('premium_config.html', config=config, profile_image_url=profile_image_url)

@app.route('/logs')
def logs():
    """Display the logs"""
    with status_lock:
        logs = upload_status["log"].copy()
    global profile_image_url
    return render_template('premium_logs.html', logs=logs, profile_image_url=profile_image_url)

@app.route('/history')
def history():
    """Display the upload history"""
    try:
        history = load_upload_history()
        # Sort by timestamp descending
        history.sort(key=lambda x: x['timestamp'], reverse=True)
    except:
        history = []
    
    global profile_image_url
    return render_template('premium_history.html', history=history, profile_image_url=profile_image_url)

@app.route('/clear_history', methods=['POST'])
def clear_history():
    """Clear the upload history"""
    try:
        save_upload_history([])
        return jsonify({"status": "success", "message": "Upload history cleared successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to clear history: {str(e)}"})

@app.route('/export_history')
def export_history():
    """Export the upload history as a JSON file"""
    try:
        history = load_upload_history()
        # Sort by timestamp descending
        history.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Convert to JSON string
        history_json = json.dumps(history, indent=2)
        
        # Create response with JSON content
        from flask import Response
        return Response(
            history_json,
            mimetype='application/json',
            headers={'Content-Disposition': 'attachment; filename=upload_history.json'}
        )
    except Exception as e:
        # Fallback to text response if there's an error
        return str(e), 500

def validate_filename(filename):
    """Validate filename to prevent path traversal attacks"""
    if not filename or '..' in filename or filename.startswith('/'):
        return False
    return True

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files"""
    # Prevent path traversal by validating the filename
    if not validate_filename(filename):
        return "Invalid filename", 400
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/uploaded/<filename>')
def serve_uploaded_file(filename):
    """Serve files from the uploaded directory"""
    # Prevent path traversal by validating the filename
    if not validate_filename(filename):
        return "Invalid filename", 400
    return send_from_directory('uploaded', filename)

@app.route('/schedule_posts', methods=['POST'])
def schedule_posts():
    """Schedule individual posts"""
    try:
        data = request.get_json()
        posts = data.get('posts', [])
        
        if not posts:
            return jsonify({"status": "error", "message": "No posts provided"})
        
        # Add each post to the schedule with validation
        for post in posts:
            filename = post.get('filename')
            scheduled_time = post.get('scheduled_time')
            
            # Validate inputs
            if not filename or not scheduled_time:
                return jsonify({"status": "error", "message": "Missing filename or scheduled time"})
            
            # Validate filename to prevent path traversal
            if not validate_filename(filename):
                return jsonify({"status": "error", "message": "Invalid filename"})
            
            # Thread-safe operation
            with schedule_lock:
                add_scheduled_post(filename, scheduled_time)
        
        # Start scheduled posts thread if not already running
        global scheduled_posts_thread, scheduled_posts_running
        if not scheduled_posts_running:
            scheduled_posts_thread = threading.Thread(target=run_scheduled_posts_thread)
            scheduled_posts_thread.start()
        
        return jsonify({"status": "success", "message": f"Successfully scheduled {len(posts)} post(s)"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to schedule posts: {str(e)}"})

@app.route('/cancel_schedule', methods=['POST'])
def cancel_schedule():
    """Cancel a scheduled post"""
    try:
        data = request.get_json()
        filename = data.get('filename')
        
        if not filename:
            return jsonify({"status": "error", "message": "No filename provided"})
        
        # Validate filename to prevent path traversal
        if not validate_filename(filename):
            return jsonify({"status": "error", "message": "Invalid filename"})
        
        # Thread-safe operation
        with schedule_lock:
            remove_scheduled_post(filename)
        return jsonify({"status": "success", "message": f"Schedule for {filename} cancelled successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to cancel schedule: {str(e)}"})

@app.route('/clear_all_scheduled', methods=['POST'])
def clear_all_scheduled():
    """Clear all scheduled posts"""
    try:
        # Thread-safe operation
        with schedule_lock:
            clear_all_scheduled_posts()
        return jsonify({"status": "success", "message": "All scheduled posts cleared successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to clear scheduled posts: {str(e)}"})

@app.route('/test_auth', methods=['POST'])
def test_auth():
    """Test Instagram authentication"""
    global profile_image_url
    
    if not os.path.exists('config.json'):
        return jsonify({"status": "error", "message": "Configuration file not found"})
    
    try:
        config = load_config()
        # Check for placeholder values
        if config.get('instagram_username') == 'your_instagram_username':
            return jsonify({"status": "error", "message": "Please update Instagram username in configuration"})
        if config.get('instagram_password') == 'your_instagram_password':
            return jsonify({"status": "error", "message": "Please update Instagram password in configuration"})
        
        # Test authentication
        client = get_instagram_client(config)
        user_info = client.account_info()
        client.get_timeline_feed()  # Verify the session is still valid
        
        # Save profile image URL
        if hasattr(user_info, 'profile_pic_url'):
            profile_image_url = user_info.profile_pic_url
        
        return jsonify({"status": "success", "message": "Authentication successful! Session is valid and active."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Authentication failed: {str(e)}"})

@app.route('/start_scheduled_monitoring', methods=['POST'])
def start_scheduled_monitoring():
    """Start the scheduled posts monitoring thread"""
    global scheduled_posts_thread, scheduled_posts_running
    
    # Check if scheduled posts thread is already running
    if scheduled_posts_running:
        return jsonify({"status": "error", "message": "Scheduled posts monitoring is already running"})
    
    # Start scheduled posts thread
    scheduled_posts_running = True
    scheduled_posts_thread = threading.Thread(target=run_scheduled_posts_thread)
    scheduled_posts_thread.start()
    
    log_message("Scheduled posts monitoring started")
    return jsonify({"status": "success", "message": "Scheduled posts monitoring started successfully"})

@app.route('/stop_scheduled_monitoring', methods=['POST'])
def stop_scheduled_monitoring():
    """Stop the scheduled posts monitoring thread"""
    global scheduled_posts_running
    
    if not scheduled_posts_running:
        return jsonify({"status": "error", "message": "Scheduled posts monitoring is not currently running"})
    
    # Stop scheduled posts thread
    scheduled_posts_running = False
    
    log_message("Scheduled posts monitoring stopped")
    return jsonify({"status": "success", "message": "Scheduled posts monitoring stopped successfully"})

@app.route('/favicon.ico')
def favicon():
    """Serve the favicon"""
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.png', mimetype='image/png')

if __name__ == '__main__':
    # Create necessary directories
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    
    if not os.path.exists('uploaded'):
        os.makedirs('uploaded')
    
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    # Use environment variable to control debug mode, default to False for production
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode, host='127.0.0.1', port=5000)