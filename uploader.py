import os
import json
import time
import random
import pathlib
from instagrapi import Client
from instagrapi.exceptions import LoginRequired
from PIL import Image
from datetime import datetime

# Import encryption module
try:
    from encryption import decrypt_config_file, decrypt_upload_history, decrypt_scheduled_posts
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False
    def decrypt_config_file(file_path='config.json'):
        # Fallback to regular JSON loading if encryption module is not available
        with open(file_path, 'r') as f:
            return json.load(f)
    
    def decrypt_upload_history(file_path='upload_history.json'):
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                return json.load(f)
        return []
    
    def decrypt_scheduled_posts(file_path='scheduled_posts.json'):
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                return json.load(f)
        return []

def load_config(config_path='config.json'):
    """Loads configuration from a JSON file, with decryption if available."""
    return decrypt_config_file(config_path)

def load_upload_history(history_path='upload_history.json'):
    """Loads upload history from a JSON file, with decryption if available."""
    return decrypt_upload_history(history_path)

def save_upload_history(history, history_path='upload_history.json'):
    """Saves upload history to a JSON file."""
    with open(history_path, 'w') as f:
        json.dump(history, f, indent=4)
    
    # Encrypt the file if encryption is available
    if ENCRYPTION_AVAILABLE:
        try:
            from encryption import encrypt_upload_history
            encrypt_upload_history(history_path)
        except Exception:
            pass  # If encryption fails, keep the unencrypted file

def add_to_upload_history(filename, status, history_path='upload_history.json'):
    """Adds an entry to the upload history."""
    history = load_upload_history(history_path)
    entry = {
        "filename": filename,
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "id": len(history) + 1
    }
    history.append(entry)
    save_upload_history(history, history_path)

def load_scheduled_posts(schedule_path='scheduled_posts.json'):
    """Loads scheduled posts from a JSON file, with decryption if available."""
    return decrypt_scheduled_posts(schedule_path)

def save_scheduled_posts(scheduled_posts, schedule_path='scheduled_posts.json'):
    """Saves scheduled posts to a JSON file."""
    with open(schedule_path, 'w') as f:
        json.dump(scheduled_posts, f, indent=4)
    
    # Encrypt the file if encryption is available
    if ENCRYPTION_AVAILABLE:
        try:
            from encryption import encrypt_scheduled_posts
            encrypt_scheduled_posts(schedule_path)
        except Exception:
            pass  # If encryption fails, keep the unencrypted file

def add_scheduled_post(filename, scheduled_time, schedule_path='scheduled_posts.json'):
    """Adds a post to the scheduled posts list."""
    scheduled_posts = load_scheduled_posts(schedule_path)
    
    # Check if post is already scheduled
    for post in scheduled_posts:
        if post['filename'] == filename:
            post['scheduled_time'] = scheduled_time
            post['status'] = 'pending'
            save_scheduled_posts(scheduled_posts, schedule_path)
            return
    
    # Add new scheduled post
    entry = {
        "filename": filename,
        "scheduled_time": scheduled_time,
        "status": "pending",
        "id": len(scheduled_posts) + 1
    }
    scheduled_posts.append(entry)
    save_scheduled_posts(scheduled_posts, schedule_path)

def remove_scheduled_post(filename, schedule_path='scheduled_posts.json'):
    """Removes a post from the scheduled posts list."""
    scheduled_posts = load_scheduled_posts(schedule_path)
    scheduled_posts = [post for post in scheduled_posts if post['filename'] != filename]
    save_scheduled_posts(scheduled_posts, schedule_path)

def clear_all_scheduled_posts(schedule_path='scheduled_posts.json'):
    """Clears all scheduled posts."""
    save_scheduled_posts([], schedule_path)

def get_instagram_client(config):
    """Initializes and logs into the Instagram client, using a saved session if available."""
    cl = Client()
    session_file = pathlib.Path(config['session_file'])
    
    # Decrypt credentials if they are encrypted
    username = config.get('instagram_username', '')
    password = config.get('instagram_password', '')
    
    # If encryption is available, try to decrypt credentials
    if ENCRYPTION_AVAILABLE:
        try:
            from encryption import decrypt_sensitive_data
            # Check if credentials appear to be encrypted (base64-like)
            if len(username) > 50 or len(password) > 50:  # Likely encrypted
                username = decrypt_sensitive_data(username)
                password = decrypt_sensitive_data(password)
        except Exception:
            pass  # If decryption fails, use as is
    
    if session_file.exists():
        print("Found existing session file. Loading settings...")
        cl.load_settings(session_file)
        try:
            cl.login(username, password)
            cl.get_timeline_feed() # Verify the session is still valid
            print("Session is valid.")
        except LoginRequired:
            print("Session expired. Performing full login.")
            session_file.unlink()
            cl.login(username, password)
            cl.dump_settings(session_file)
    else:
        print("No session file found. Performing full login.")
        cl.login(username, password)
        cl.dump_settings(session_file)
        print(f"New session saved to {session_file}")
        
    return cl

def upload_single_image(client, image_path, config):
    """Uploads a single image to Instagram."""
    try:
        # Define the static caption
        static_caption = "Webui used: ComfyUI\nModel Used : JuggernautXLv9"
        
        client.photo_upload(path=image_path, caption=static_caption)
        return True, "SUCCESS"
    except Exception as e:
        return False, f"ERROR: {str(e)}"

def main():
    """Main execution function for the Instagram upload workflow."""
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
        
        # IMPORTANT: Wait for a random, human-like interval
        delay = random.uniform(300, 900) # 5 to 15 minutes
        log_message(f"Waiting for {delay:.2f} seconds to avoid triggering bot detection...")
        time.sleep(delay)

    log_message("--- Script finished ---")

if __name__ == "__main__":
    main()