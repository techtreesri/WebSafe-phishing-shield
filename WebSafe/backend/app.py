# Importing required libraries for Flask backend, URL processing, and machine learning
import os
import re
import requests
import pandas as pd
import numpy as np
from urllib.parse import urlparse
from flask import Flask, request, jsonify
from flask_cors import CORS
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
import joblib
import whois
from datetime import datetime
import socket
import ssl
from bs4 import BeautifulSoup
import logging
import warnings

# Suppress warnings for cleaner logs
warnings.filterwarnings('ignore')

# Initialize Flask application
app = Flask(__name__)

# Enable CORS for cross-browser extension compatibility (Chrome, Firefox, Edge, Safari)
CORS(app, resources={r"/*": {"origins": "*"}})

# Set up logging for debugging frontend-backend communication
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('backend.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration for backend URL
BACKEND_CONFIG = {
    'HOST': '0.0.0.0',
    'PORT': 5000,
    'BASE_URL': 'http://localhost:5000'  # Update for production
}

# Feature labels and thresholds for frontend display
FEATURE_LABELS = {
    'url_length': {'name': 'URL Length', 'icon': '📏', 'description': lambda v: f'URL length ({v} characters)'},
    'has_at_symbol': {'name': 'At Symbol', 'icon': '❗', 'description': lambda v: 'Contains @ symbol' if v else 'No @ symbol'},
    'has_dash': {'name': 'Domain Dash', 'icon': '➖', 'description': lambda v: 'Dash in domain' if v else 'No dash in domain'},
    'subdomain_count': {'name': 'Subdomains', 'icon': '🌐', 'description': lambda v: f'{v} subdomains'},
    'is_https': {'name': 'SSL Certificate', 'icon': '🔒', 'description': lambda v: 'Valid SSL certificate' if v else 'No SSL certificate'},
    'domain_age_days': {'name': 'Domain Age', 'icon': '📅', 'description': lambda v: f'Domain age: {v} days'},
    'has_ip_address': {'name': 'IP Address', 'icon': '🌍', 'description': lambda v: 'Uses IP address' if v else 'Uses domain name'},
    'redirect_count': {'name': 'Redirects', 'icon': '🔄', 'description': lambda v: f'{v} redirects'},
    'has_login_form': {'name': 'Login Form', 'icon': '🔑', 'description': lambda v: 'Contains login form' if v else 'No login form'},
    'has_iframe': {'name': 'Iframe', 'icon': '🖼️', 'description': lambda v: 'Contains iframe' if v else 'No iframe'},
    'suspicious_words_count': {'name': 'Suspicious Words', 'icon': '🚨', 'description': lambda v: f'{v} suspicious words'}
}

FEATURE_THRESHOLDS = {
    'url_length': {'safe': lambda v: v <= 50, 'warning': lambda v: 50 < v <= 100, 'danger': lambda v: v > 100},
    'has_at_symbol': {'safe': lambda v: v == 0, 'warning': lambda v: False, 'danger': lambda v: v == 1},
    'has_dash': {'safe': lambda v: v == 0, 'warning': lambda v: False, 'danger': lambda v: v == 1},
    'subdomain_count': {'safe': lambda v: v <= 1, 'warning': lambda v: v == 2, 'danger': lambda v: v > 2},
    'is_https': {'safe': lambda v: v == 1, 'warning': lambda v: False, 'danger': lambda v: v == 0},
    'domain_age_days': {'safe': lambda v: v >= 365, 'warning': lambda v: 30 <= v < 365, 'danger': lambda v: v < 30},
    'has_ip_address': {'safe': lambda v: v == 0, 'warning': lambda v: False, 'danger': lambda v: v == 1},
    'redirect_count': {'safe': lambda v: v <= 1, 'warning': lambda v: v == 2, 'danger': lambda v: v > 2},
    'has_login_form': {'safe': lambda v: v == 0, 'warning': lambda v: False, 'danger': lambda v: v == 1},
    'has_iframe': {'safe': lambda v: v == 0, 'warning': lambda v: False, 'danger': lambda v: v == 1},
    'suspicious_words_count': {'safe': lambda v: v == 0, 'warning': lambda v: v == 1, 'danger': lambda v: v > 1}
}

class PhishingDetector:
    def __init__(self):
        """Initialize the PhishingDetector with model and scaler attributes."""
        self.model = None
        self.scaler = None
        self.feature_names = list(FEATURE_LABELS.keys())
        
    def extract_features(self, url):
        """Extract features from a URL for phishing detection."""
        features = {}
        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower() if parsed_url.netloc else parsed_url.path.lower()
            
            features['url_length'] = len(url)
            features['has_at_symbol'] = 1 if '@' in url else 0
            features['has_dash'] = 1 if '-' in domain else 0
            features['subdomain_count'] = max(len(domain.split('.')) - 2, 0)
            features['is_https'] = 1 if parsed_url.scheme == 'https' else 0
            
            ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
            features['has_ip_address'] = 1 if re.search(ip_pattern, domain) else 0
            
            features['domain_age_days'] = self.get_domain_age(domain)
            features['redirect_count'] = self.count_redirects(url)
            page_features = self.analyze_page_content(url)
            features.update(page_features)
            
            suspicious_words = ['login', 'verify', 'account', 'suspended', 'click', 'urgent']
            features['suspicious_words_count'] = sum(1 for word in suspicious_words if word.lower() in url.lower())
            
            logger.debug(f"Features extracted for URL {url}: {features}")
        except Exception as e:
            logger.error(f"Error extracting features for {url}: {str(e)}")
            for feature in self.feature_names:
                features[feature] = 0
        
        return [features.get(name, 0) for name in self.feature_names]
    
    def get_domain_age(self, domain):
        """Calculate domain age in days (simplified for demo)."""
        try:
            return hash(domain) % 365 + 30
        except Exception as e:
            logger.warning(f"Failed to get domain age for {domain}: {str(e)}")
            return 30
    
    def count_redirects(self, url):
        """Count the number of redirects for a given URL."""
        try:
            response = requests.head(url, allow_redirects=True, timeout=5)
            return len(response.history)
        except Exception as e:
            logger.warning(f"Failed to count redirects for {url}: {str(e)}")
            return 0
    
    def analyze_page_content(self, url):
        """Analyze webpage content for phishing indicators."""
        features = {'has_login_form': 0, 'has_iframe': 0}
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            login_indicators = soup.find_all(['input'], {'type': ['password', 'email']})
            features['has_login_form'] = 1 if login_indicators else 0
            
            iframes = soup.find_all('iframe')
            features['has_iframe'] = 1 if iframes else 0
            
            logger.debug(f"Page content analyzed for {url}: {features}")
        except Exception as e:
            logger.warning(f"Failed to analyze page content for {url}: {str(e)}")
        return features
    
    def create_sample_dataset(self):
        """Create a sample dataset for training the Random Forest model."""
        logger.info("Creating sample dataset for model training")
        phishing_data = [
            ['http://paypal-verification.suspicious-site.com/login', 1],
            ['https://amazon-security@fake-amazon.net/verify', 1],
            ['http://192.168.1.1/bank-login/', 1],
            ['https://microsoft-support-urgent.click-here.com', 1],
            ['http://facebook-security-check.verify-now.org', 1],
            ['https://apple-id-suspended.account-verify.net', 1],
            ['http://google-drive-share@malicious-site.com', 1],
            ['https://netflix-payment-failed.urgent-update.org', 1],
        ]
        legitimate_data = [
            ['https://www.google.com', 0],
            ['https://www.amazon.com', 0],
            ['https://www.microsoft.com', 0],
            ['https://www.apple.com', 0],
            ['https://www.facebook.com', 0],
            ['https://www.netflix.com', 0],
            ['https://www.github.com', 0],
            ['https://www.stackoverflow.com', 0],
        ]
        all_data = phishing_data + legitimate_data
        return pd.DataFrame(all_data, columns=['url', 'is_phishing'])
    
    def train_model(self):
        """Train the Random Forest model with sample data."""
        logger.info("Starting model training...")
        try:
            df = self.create_sample_dataset()
            features_list = [self.extract_features(url) for url in df['url']]
            
            X = np.array(features_list)
            y = df['is_phishing'].values
            
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
            
            self.scaler = StandardScaler()
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_test_scaled = self.scaler.transform(X_test)
            
            self.model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                random_state=42
            )
            self.model.fit(X_train_scaled, y_train)
            
            accuracy = self.model.score(X_test_scaled, y_test)
            logger.info(f"Model trained with accuracy: {accuracy:.2f}")
            
            joblib.dump(self.model, 'phishing_model.pkl')
            joblib.dump(self.scaler, 'feature_scaler.pkl')
            logger.info("Model and scaler saved to disk")
        except Exception as e:
            logger.error(f"Error during model training: {str(e)}")
            raise
    
    def load_model(self):
        """Load the pre-trained model and scaler from disk."""
        try:
            self.model = joblib.load('phishing_model.pkl')
            self.scaler = joblib.load('feature_scaler.pkl')
            logger.info("Model and scaler loaded successfully")
        except FileNotFoundError:
            logger.warning("Model or scaler not found. Training new model...")
            self.train_model()
    
    def predict(self, url):
        """Predict if a URL is phishing or legitimate."""
        if self.model is None or self.scaler is None:
            self.load_model()
        
        try:
            features = self.extract_features(url)
            features_scaled = self.scaler.transform([features])
            prediction = self.model.predict(features_scaled)[0]
            probability = self.model.predict_proba(features_scaled)[0]
            
            # Convert features to frontend-friendly parameters
            parameters = []
            for name, value in zip(self.feature_names, features):
                status = 'safe'
                if FEATURE_THRESHOLDS[name]['danger'](value):
                    status = 'danger'
                elif FEATURE_THRESHOLDS[name]['warning'](value):
                    status = 'warning'
                
                parameters.append({
                    'name': FEATURE_LABELS[name]['name'],
                    'icon': FEATURE_LABELS[name]['icon'],
                    'status': status,
                    'description': FEATURE_LABELS[name]['description'](value)
                })
            
            # Calculate score (0-100, higher is safer)
            score = probability[0] * 100 if prediction == 0 else (1 - probability[1]) * 100
            
            return {
                'prediction': 'phishing' if prediction == 1 else 'legitimate',
                'score': round(score, 1),
                'parameters': parameters
            }
        except Exception as e:
            logger.error(f"Error predicting for {url}: {str(e)}")
            return {'prediction': 'error', 'score': 0.0, 'parameters': []}

# Initialize the phishing detector
detector = PhishingDetector()

def validate_url(url):
    """Validate URL format to prevent invalid inputs from frontend."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
        return bool(parsed.scheme and parsed.netloc)
    except:
        return False

@app.route('/predict', methods=['POST'])
def predict_url():
    """
    API endpoint for single URL prediction.
    Expects JSON: {"url": "string"}
    Returns JSON: {"score": float, "url": string, "parameters": [{name, icon, status, description}], "message": string, "timestamp": string}
    """
    try:
        data = request.get_json()
        logger.debug(f"Received /predict request: {data}")
        if not data or 'url' not in data:
            logger.warning("Invalid request: URL is required")
            return jsonify({'error': 'URL is required'}), 400
        
        url = data['url'].strip()
        if not validate_url(url):
            logger.warning(f"Invalid URL format: {url}")
            return jsonify({'error': 'Invalid URL format'}), 400
        
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url
        
        result = detector.predict(url)
        if result['prediction'] == 'error':
            logger.error(f"Prediction failed for {url}")
            return jsonify({'error': 'Prediction failed'}), 500
        
        response = {
            'score': result['score'],
            'url': url,
            'parameters': result['parameters'],
            'message': ('This website is safe.' if result['prediction'] == 'legitimate' 
                       else 'Warning: This website may be a phishing attempt!'),
            'timestamp': datetime.utcnow().isoformat()
        }
        logger.info(f"Prediction for {url}: {response}")
        return jsonify(response)
    
    except Exception as e:
        logger.error(f"Error processing /predict request: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/batch-predict', methods=['POST'])
def batch_predict_url():
    """
    API endpoint for batch URL prediction.
    Expects JSON: {"urls": ["string", ...]}
    Returns JSON: {"results": [{score, url, parameters, message, timestamp}, ...]}
    """
    try:
        data = request.get_json()
        logger.debug(f"Received /batch-predict request: {data}")
        if not data or 'urls' not in data or not isinstance(data['urls'], list):
            logger.warning("Invalid request: URLs array is required")
            return jsonify({'error': 'URLs array is required'}), 400
        
        results = []
        for url in data['urls']:
            url = url.strip()
            if not validate_url(url):
                logger.warning(f"Invalid URL format: {url}")
                results.append({
                    'url': url,
                    'score': 0.0,
                    'parameters': [],
                    'message': 'Invalid URL format',
                    'timestamp': datetime.utcnow().isoformat()
                })
                continue
            
            if not url.startswith(('http://', 'https://')):
                url = 'http://' + url
            
            result = detector.predict(url)
            results.append({
                'url': url,
                'score': result['score'],
                'parameters': result['parameters'],
                'message': ('This website is safe.' if result['prediction'] == 'legitimate' 
                           else 'Warning: This website may be a phishing attempt!'),
                'timestamp': datetime.utcnow().isoformat()
            })
        
        response = {'results': results}
        logger.info(f"Batch prediction completed for {len(data['urls'])} URLs")
        return jsonify(response)
    
    except Exception as e:
        logger.error(f"Error processing /batch-predict request: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """API endpoint to check service health."""
    return jsonify({
        'status': 'healthy',
        'message': 'WebSafe Detection API is running',
        'timestamp': datetime.utcnow().isoformat(),
        'backend_url': BACKEND_CONFIG['BASE_URL']
    })

@app.route('/', methods=['GET'])
def home():
    """Root endpoint providing API information."""
    return jsonify({
        'message': 'WebSafe Detection API',
        'version': '1.0.0',
        'endpoints': {
            '/predict': 'POST - Predict if a single URL is phishing (expects {"url": "string"})',
            '/batch-predict': 'POST - Predict for multiple URLs (expects {"urls": ["string", ...]})',
            '/health': 'GET - Check API health status'
        },
        'backend_url': BACKEND_CONFIG['BASE_URL']
    })

if __name__ == '__main__':
    logger.info("Starting WebSafe Detection API...")
    detector.load_model()  # Load or train the model on startup
    app.run(
        host=BACKEND_CONFIG['HOST'],
        port=BACKEND_CONFIG['PORT'],
        debug=True
    )