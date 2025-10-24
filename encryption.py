"""
Encryption module for Instagram Auto Poster Pro application.
Implements Fernet symmetric encryption for sensitive data protection.
"""
import os
import json
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def get_encryption_key():
    """
    Retrieve the encryption key from environment variable or generate a deterministic key.
    In production, always use an environment variable.
    """
    # Try to get key from environment variable
    key = os.environ.get('ENCRYPTION_KEY')
    
    if key:
        # If key is provided as base64 string, decode it
        try:
            return base64.urlsafe_b64decode(key)
        except Exception:
            # If it's not base64, derive a key from it
            return derive_key_from_password(key.encode())
    else:
        # Fallback: derive key from a default password (NOT recommended for production)
        # In production, always set ENCRYPTION_KEY environment variable
        default_password = b"instagram_auto_poster_default_key_2025"
        return derive_key_from_password(default_password)


def derive_key_from_password(password: bytes, salt: bytes = b'instagram_auto_poster_salt_2025') -> bytes:
    """
    Derive a Fernet key from a password using PBKDF2.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password))
    return key


def encrypt_data(data: str) -> str:
    """
    Encrypt a string using Fernet symmetric encryption.
    
    Args:
        data (str): The data to encrypt
        
    Returns:
        str: Base64 encoded encrypted data
    """
    key = get_encryption_key()
    fernet = Fernet(key)
    encrypted_data = fernet.encrypt(data.encode())
    return base64.urlsafe_b64encode(encrypted_data).decode()


def decrypt_data(encrypted_data: str) -> str:
    """
    Decrypt a string using Fernet symmetric encryption.
    
    Args:
        encrypted_data (str): Base64 encoded encrypted data
        
    Returns:
        str: Decrypted data
    """
    key = get_encryption_key()
    fernet = Fernet(key)
    # Decode from base64 first
    encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
    decrypted_data = fernet.decrypt(encrypted_bytes)
    return decrypted_data.decode()


def encrypt_sensitive_data(data: str) -> str:
    """
    Encrypt sensitive data (wrapper for encrypt_data).
    
    Args:
        data (str): The sensitive data to encrypt
        
    Returns:
        str: Base64 encoded encrypted data
    """
    return encrypt_data(data)


def decrypt_sensitive_data(encrypted_data: str) -> str:
    """
    Decrypt sensitive data (wrapper for decrypt_data).
    
    Args:
        encrypted_data (str): Base64 encoded encrypted data
        
    Returns:
        str: Decrypted data
    """
    return decrypt_data(encrypted_data)


def encrypt_config_file(file_path: str = 'config.json') -> None:
    """
    Encrypt the config.json file, encrypting sensitive fields.
    
    Args:
        file_path (str): Path to the config file
    """
    if not os.path.exists(file_path):
        return
    
    try:
        # Read the original config file
        with open(file_path, 'r') as f:
            config = json.load(f)
        
        # Encrypt sensitive fields
        if 'instagram_username' in config:
            config['instagram_username'] = encrypt_sensitive_data(config['instagram_username'])
        
        if 'instagram_password' in config:
            config['instagram_password'] = encrypt_sensitive_data(config['instagram_password'])
        
        # Write back the encrypted config
        with open(file_path, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        # If encryption fails, we'll leave the file as is
        pass


def decrypt_config_file(file_path: str = 'config.json') -> dict:
    """
    Decrypt the config.json file, decrypting sensitive fields.
    
    Args:
        file_path (str): Path to the config file
        
    Returns:
        dict: Decrypted configuration
    """
    if not os.path.exists(file_path):
        return {}
    
    try:
        # Read the config file
        with open(file_path, 'r') as f:
            config = json.load(f)
        
        # Decrypt sensitive fields if they appear to be encrypted
        if 'instagram_username' in config:
            try:
                # Check if it looks like encrypted data (base64 encoded)
                if len(config['instagram_username']) > 50:  # Likely encrypted
                    config['instagram_username'] = decrypt_sensitive_data(config['instagram_username'])
            except Exception:
                # If decryption fails, leave as is
                pass
        
        if 'instagram_password' in config:
            try:
                # Check if it looks like encrypted data (base64 encoded)
                if len(config['instagram_password']) > 50:  # Likely encrypted
                    config['instagram_password'] = decrypt_sensitive_data(config['instagram_password'])
            except Exception:
                # If decryption fails, leave as is
                pass
        
        return config
    except Exception:
        # If anything fails, return empty dict
        return {}


def encrypt_upload_history(file_path: str = 'upload_history.json') -> None:
    """
    Encrypt the upload history file.
    
    Args:
        file_path (str): Path to the upload history file
    """
    if not os.path.exists(file_path):
        return
    
    try:
        # Read the original file
        with open(file_path, 'r') as f:
            data = f.read()
        
        # Encrypt the entire file content
        encrypted_data = encrypt_data(data)
        
        # Write the encrypted data
        with open(file_path, 'w') as f:
            f.write(encrypted_data)
    except Exception:
        # If encryption fails, leave the file as is
        pass


def decrypt_upload_history(file_path: str = 'upload_history.json') -> list:
    """
    Decrypt the upload history file.
    
    Args:
        file_path (str): Path to the upload history file
        
    Returns:
        list: Decrypted upload history
    """
    if not os.path.exists(file_path):
        return []
    
    try:
        # Read the encrypted file
        with open(file_path, 'r') as f:
            encrypted_data = f.read()
        
        # Decrypt the data
        decrypted_data = decrypt_data(encrypted_data)
        
        # Parse as JSON
        return json.loads(decrypted_data)
    except Exception:
        # If decryption fails, try to read as regular JSON
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception:
            return []


def encrypt_scheduled_posts(file_path: str = 'scheduled_posts.json') -> None:
    """
    Encrypt the scheduled posts file.
    
    Args:
        file_path (str): Path to the scheduled posts file
    """
    if not os.path.exists(file_path):
        return
    
    try:
        # Read the original file
        with open(file_path, 'r') as f:
            data = f.read()
        
        # Encrypt the entire file content
        encrypted_data = encrypt_data(data)
        
        # Write the encrypted data
        with open(file_path, 'w') as f:
            f.write(encrypted_data)
    except Exception:
        # If encryption fails, leave the file as is
        pass


def decrypt_scheduled_posts(file_path: str = 'scheduled_posts.json') -> list:
    """
    Decrypt the scheduled posts file.
    
    Args:
        file_path (str): Path to the scheduled posts file
        
    Returns:
        list: Decrypted scheduled posts
    """
    if not os.path.exists(file_path):
        return []
    
    try:
        # Read the encrypted file
        with open(file_path, 'r') as f:
            encrypted_data = f.read()
        
        # Decrypt the data
        decrypted_data = decrypt_data(encrypted_data)
        
        # Parse as JSON
        return json.loads(decrypted_data)
    except Exception:
        # If decryption fails, try to read as regular JSON
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception:
            return []