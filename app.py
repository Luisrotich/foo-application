# app.py - Full Flask backend for Fresh Ready Foods
# Serves customer app at / and admin panel at /admin
import os
import base64
import requests
from pathlib import Path
from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name('.env'), override=True)
print('M-Pesa configuration:')
print('  Base URL:', os.getenv('MPESA_BASE_URL'))
print('  Shortcode:', os.getenv('MPESA_SHORTCODE'))
print('  Consumer key configured:', bool(os.getenv('MPESA_CONSUMER_KEY')))
print('  Consumer secret configured:', bool(os.getenv('MPESA_CONSUMER_SECRET')))
print('  Passkey configured:', bool(os.getenv('MPESA_PASSKEY')))
import os
import json
import uuid
from datetime import datetime, timedelta
from flask import Flask, session, request, jsonify, render_template, send_from_directory
from sqlalchemy import text
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps


app = Flask(__name__)
db = SQLAlchemy()
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL'].replace(
    'postgresql://',
    'postgresql+psycopg://',
    1
)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
    'pool_size': 5,
    'max_overflow': 10,
}

db.init_app(app)
app.config.update(
    SECRET_KEY=os.environ['SECRET_KEY'],
    SESSION_COOKIE_SECURE=os.getenv('RENDER') == 'true',
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    UPLOAD_FOLDER=os.path.join(app.root_path, 'static', 'uploads'),
    MAX_CONTENT_LENGTH=16 * 1024 * 1024
)
# Ensure folders exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
def save_compressed_image(uploaded_file):
    image = Image.open(uploaded_file)
    image = ImageOps.exif_transpose(image).convert('RGB')
    image.thumbnail((800, 800), Image.Resampling.LANCZOS)

    filename = f'{uuid.uuid4().hex}.webp'
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    image.save(filepath, 'WEBP', quality=78, method=6, optimize=True)
    return f'/static/uploads/{filename}'
os.makedirs('templates', exist_ok=True)
os.makedirs('static', exist_ok=True)

# ============================
# DATA STORES (in‑memory)
# ============================

users = {}          # id -> {id, name, email, password_hash, phone, address, created_at, favorites, addresses}
products = {}       # id -> {id, name, category, price, stock, discount, prep_time, rating, featured, description, image, image_icon, available, sort_order}
orders = {}         # id -> {id, user_id, customer, phone, items, total, status, created_at, note, delivery_address, payment_id}
payments = {}       # id -> {id, order_id, phone, amount, status, transaction_id, checkout_request_id, created_at}
deliveries = {}     # id -> {id, name, phone, orders, status, last_delivery}
debts = {}          # id -> {id, customer, phone, amount_owed, paid, due_date, created_at}
notifications = []  # list of {id, type, message, time, read}
admins = {}         # username -> {username, password_hash}

# Default admin
admins['admin'] = {'username': 'admin', 'password_hash': generate_password_hash('admin')}

# ID counters
user_id_counter = 1
product_id_counter = 1
order_id_counter = 1000
payment_id_counter = 500
delivery_id_counter = 300
debt_id_counter = 400
notification_id_counter = 1

# ============================
# HELPER FUNCTIONS
# ============================

def get_current_user():
    user_id = session.get('user_id')

    if not user_id:
        return None

    try:
        user = db.session.execute(
            text("""
                SELECT
                    id,
                    name,
                    email,
                    phone,
                    address,
                    password_hash,
                    role,
                    status,
                    created_at
                FROM users
                WHERE id = :user_id
                LIMIT 1
            """),
            {"user_id": user_id}
        ).mappings().first()

        if not user:
            return None

        if user['status'] != 'active':
            return None

        return dict(user)

    except Exception as e:
        print('Get current user database error:', e)
        return None

def get_current_admin():
    admin_username = session.get('admin_username')
    if admin_username and admin_username in admins:
        return admins[admin_username]
    return None

def save_notification(message, type='order'):
    global notification_id_counter
    notif = {
        'id': notification_id_counter,
        'type': type,
        'message': message,
        'time': datetime.now().strftime('%H:%M'),
        'read': False
    }
    notification_id_counter += 1
    notifications.insert(0, notif)
    return notif

def parse_json_items(items_str):
    try:
        return json.loads(items_str)
    except:
        return []
def get_mpesa_access_token():
    response = requests.get(
        f"{os.getenv('MPESA_BASE_URL')}/oauth/v1/generate"
        "?grant_type=client_credentials",
        auth=(
            os.getenv('MPESA_CONSUMER_KEY'),
            os.getenv('MPESA_CONSUMER_SECRET')
        ),
        timeout=30
    )
    response.raise_for_status()
    return response.json()['access_token']

def validate_mpesa_config():
    required = [
        'MPESA_BASE_URL',
        'MPESA_CONSUMER_KEY',
        'MPESA_CONSUMER_SECRET',
        'MPESA_SHORTCODE',
        'MPESA_PASSKEY',
        'MPESA_CALLBACK_URL'
    ]

    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing M-Pesa settings: {', '.join(missing)}")

def send_stk_push(phone, amount, account_reference):
    validate_mpesa_config()
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    shortcode = os.getenv('MPESA_SHORTCODE')
    passkey = os.getenv('MPESA_PASSKEY')

    password = base64.b64encode(
        f'{shortcode}{passkey}{timestamp}'.encode()
    ).decode()

    payload = {
        'BusinessShortCode': shortcode,
        'Password': password,
        'Timestamp': timestamp,
        'TransactionType': 'CustomerPayBillOnline',
        'Amount': max(1, int(round(float(amount)))),
        'PartyA': phone,
        'PartyB': shortcode,
        'PhoneNumber': phone,
        'CallBackURL': os.getenv('MPESA_CALLBACK_URL'),
        'AccountReference': account_reference,
        'TransactionDesc': 'Food order payment'
    }

    response = requests.post(
        f"{os.getenv('MPESA_BASE_URL')}/mpesa/stkpush/v1/processrequest",
        headers={
            'Authorization': f"Bearer {get_mpesa_access_token()}",
            'Content-Type': 'application/json'
        },
        json=payload,
        timeout=30
    )
    print('M-Pesa response:', response.status_code, response.text)
    response.raise_for_status()
    return response.json()


def query_mpesa_status(checkout_id):
    validate_mpesa_config()

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    shortcode = os.getenv('MPESA_SHORTCODE')
    passkey = os.getenv('MPESA_PASSKEY')

    password = base64.b64encode(
        f'{shortcode}{passkey}{timestamp}'.encode()
    ).decode()

    response = requests.post(
        f"{os.getenv('MPESA_BASE_URL')}/mpesa/stkpushquery/v1/query",
        headers={
            'Authorization': f"Bearer {get_mpesa_access_token()}",
            'Content-Type': 'application/json'
        },
        json={
            'BusinessShortCode': shortcode,
            'Password': password,
            'Timestamp': timestamp,
            'CheckoutRequestID': checkout_id
        },
        timeout=30
    )

    print('M-Pesa status response:', response.status_code, response.text)

    response.raise_for_status()

    return response.json()

# ============================
# CUSTOMER AUTH ROUTES
# ============================

@app.route('/api/user/status', methods=['GET'])
def user_status():
    user = get_current_user()
    if user:
        return jsonify({
            'id': user['id'],
            'name': user['name'],
            'email': user['email'],
            'phone': user.get('phone', ''),
            'address': user.get('address', ''),
            'created_at': user.get('created_at', datetime.now().isoformat())
        }), 200
    return jsonify({'error': 'Not logged in'}), 401

@app.route('/api/user/login', methods=['POST'])
def user_login():
    data = request.get_json(silent=True) or {}

    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    try:
        user = db.session.execute(
            text("""
                SELECT id, name, email, password_hash, phone, address, status
                FROM users
                WHERE email = :email
                LIMIT 1
            """),
            {"email": email}
        ).mappings().first()

        if not user:
            return jsonify({'error': 'Invalid credentials'}), 401

        if user['status'] != 'active':
            return jsonify({'error': 'Account is not active'}), 403

        if not check_password_hash(user['password_hash'], password):
            return jsonify({'error': 'Invalid credentials'}), 401

        session.permanent = True
        session['user_id'] = str(user['id'])

        return jsonify({
            'success': True,
            'name': user['name']
        }), 200

    except Exception as e:
        db.session.rollback()
        print('Login database error:', e)
        return jsonify({'error': 'Unable to log in'}), 500

@app.route('/api/user/logout', methods=['POST'])
def user_logout():
    session.pop('user_id', None)
    return jsonify({'success': True}), 200

@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.get_json(silent=True) or {}

    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not name or not email or not password:
        return jsonify({'error': 'All fields required'}), 400

    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    try:
        # Check whether the email already exists in Neon
        existing = db.session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": email}
        ).first()

        if existing:
            return jsonify({'error': 'Email already registered'}), 400

        # Hash password before storing it
        password_hash = generate_password_hash(password)

        # Insert the new customer into Neon
        result = db.session.execute(
            text("""
                INSERT INTO users
                    (name, email, password_hash, role, status)
                VALUES
                    (:name, :email, :password_hash, 'customer', 'active')
                RETURNING id
            """),
            {
                "name": name,
                "email": email,
                "password_hash": password_hash
            }
        )

        user_id = result.scalar_one()

        db.session.commit()

        return jsonify({
            'success': True,
            'name': name,
            'user_id': str(user_id)
        }), 201

    except Exception as e:
        db.session.rollback()
        print('Signup database error:', e)
        return jsonify({'error': 'Unable to create account'}), 500
@app.route('/api/user/profile', methods=['GET', 'PUT'])
def user_profile():
    user = get_current_user()

    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    user_id = str(user['id'])

    if request.method == 'GET':
        return jsonify({
            'user': {
                'id': user_id,
                'name': user['name'],
                'email': user['email'],
                'phone': user.get('phone') or '',
                'address': user.get('address') or '',
                'created_at': user.get('created_at')
            },
            'favorites': [],
            'addresses': [],
            'orders': []
        }), 200

    data = request.get_json(silent=True) or {}

    name = data.get('name')
    phone = data.get('phone')
    address = data.get('address')

    updates = {}
    if name is not None:
        updates['name'] = str(name).strip()

    if phone is not None:
        updates['phone'] = str(phone).strip()

    if address is not None:
        updates['address'] = str(address).strip()

    if not updates:
        return jsonify({'success': True}), 200

    try:
        set_parts = []
        params = {'user_id': user_id}

        for field, value in updates.items():
            set_parts.append(f"{field} = :{field}")
            params[field] = value

        db.session.execute(
            text(f"""
                UPDATE users
                SET {', '.join(set_parts)}
                WHERE id = :user_id
            """),
            params
        )

        db.session.commit()

        return jsonify({'success': True}), 200

    except Exception as e:
        db.session.rollback()
        print('Profile database error:', e)
        return jsonify({'error': 'Unable to update profile'}), 500

@app.route('/api/user/change-password', methods=['POST'])
def change_password():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    old = data.get('oldPassword')
    new = data.get('newPassword')
    if not old or not new:
        return jsonify({'error': 'Old and new password required'}), 400
    if not check_password_hash(user['password_hash'], old):
        return jsonify({'error': 'Old password incorrect'}), 400
    if len(new) < 6:
        return jsonify({'error': 'New password must be at least 6 characters'}), 400
    user['password_hash'] = generate_password_hash(new)
    return jsonify({'success': True}), 200

@app.route('/api/user/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json()
    email = data.get('email')
    if not email:
        return jsonify({'error': 'Email required'}), 400
    # In production, send email. For demo, just say sent.
    return jsonify({'success': True, 'message': 'Reset link sent to your email'}), 200

@app.route('/api/user/favorites', methods=['POST', 'DELETE'])
def user_favorites():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    product_id = data.get('productId')
    if not product_id:
        return jsonify({'error': 'Product ID required'}), 400
    if request.method == 'POST':
        if product_id not in user['favorites']:
            user['favorites'].append(product_id)
        return jsonify({'success': True}), 200
    else:
        if product_id in user['favorites']:
            user['favorites'].remove(product_id)
        return jsonify({'success': True}), 200

@app.route('/api/user/addresses', methods=['GET', 'POST', 'DELETE'])
def user_addresses():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    if request.method == 'GET':
        return jsonify(user.get('addresses', [])), 200
    elif request.method == 'POST':
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data'}), 400
        addresses = user.get('addresses', [])
        addresses.append(data)
        user['addresses'] = addresses
        return jsonify({'success': True}), 201
    else:
        data = request.get_json()
        index = data.get('index')
        if index is None or not isinstance(index, int):
            return jsonify({'error': 'Index required'}), 400
        addresses = user.get('addresses', [])
        if 0 <= index < len(addresses):
            addresses.pop(index)
            user['addresses'] = addresses
            return jsonify({'success': True}), 200
        return jsonify({'error': 'Address not found'}), 404

# ============================
# PRODUCTS / INVENTORY
# ============================

def get_or_create_waterfront_restaurant():
    """
    Return the main Waterfront Kitchen restaurant.
    Creates the required system owner, restaurant and categories
    when they do not yet exist.
    """

    # Look for the restaurant first
    restaurant = db.session.execute(
        text("""
            SELECT id
            FROM restaurants
            WHERE name = 'Waterfront Kitchen'
              AND deleted_at IS NULL
            LIMIT 1
        """)
    ).scalar()

    if restaurant:
        return str(restaurant)

    # Create a system restaurant owner because the current admin
    # authentication is still handled separately from the users table.
    owner = db.session.execute(
        text("""
            SELECT id
            FROM users
            WHERE email = 'restaurant@waterfront-kitchen.local'
            LIMIT 1
        """)
    ).scalar()

    if not owner:
        owner = db.session.execute(
            text("""
                INSERT INTO users
                    (name, email, password_hash, role, status)
                VALUES
                    (
                        'Waterfront Kitchen',
                        'restaurant@waterfront-kitchen.local',
                        :password_hash,
                        'restaurant',
                        'active'
                    )
                RETURNING id
            """),
            {
                "password_hash": generate_password_hash(
                    "internal-restaurant-account"
                )
            }
        ).scalar_one()

    restaurant = db.session.execute(
        text("""
            INSERT INTO restaurants
                (owner_id, name, status)
            VALUES
                (:owner_id, 'Waterfront Kitchen', 'active')
            RETURNING id
        """),
        {"owner_id": owner}
    ).scalar_one()

    db.session.commit()

    return str(restaurant)

def get_or_create_category(restaurant_id, category_name):
    """Return a category UUID, creating it when necessary."""

    category_name = (category_name or 'Fruits').strip()

    if not category_name:
        category_name = 'Fruits'

    category = db.session.execute(
        text("""
            SELECT id
            FROM categories
            WHERE restaurant_id = :restaurant_id
              AND name = :name
            LIMIT 1
        """),
        {
            "restaurant_id": restaurant_id,
            "name": category_name
        }
    ).scalar()

    if category:
        return str(category)

    category = db.session.execute(
        text("""
            INSERT INTO categories
                (restaurant_id, name)
            VALUES
                (:restaurant_id, :name)
            RETURNING id
        """),
        {
            "restaurant_id": restaurant_id,
            "name": category_name
        }
    ).scalar_one()

    return str(category)

def product_to_json(row):
    """Convert a Neon meal row to the existing frontend product format."""

    return {
        'id': str(row['id']),
        'name': row['name'],
        'category': row['category'],
        'price': float(row['price']),
        'stock': int(row['stock']),
        'discount': float(row['discount']),
        'prep_time': int(row['prep_time']),
        'rating': float(row['rating']),
        'featured': int(row['featured']),
        'description': row['description'] or '',
        'image': row['image_url'] or '',
        'image_icon': row['image_icon'] or 'fa-apple-alt',
        'available': int(row['is_available']),
        'sort_order': int(row['sort_order'])
    }

@app.route('/api/products', methods=['GET', 'POST'])
def products_list():

    # ============================
    # GET PRODUCTS
    # ============================
    if request.method == 'GET':
        try:
            rows = db.session.execute(
                text("""
                    SELECT
                        m.id,
                        m.name,
                        c.name AS category,
                        m.price,
                        m.stock,
                        m.discount,
                        m.prep_time,
                        m.rating,
                        m.featured,
                        m.description,
                        m.image_url,
                        m.image_icon,
                        m.is_available,
                        m.sort_order
                    FROM meals m
                    JOIN categories c
                        ON c.id = m.category_id
                    WHERE m.deleted_at IS NULL
                    ORDER BY m.sort_order ASC, m.created_at DESC
                """)
            ).mappings().all()

            return jsonify([
                product_to_json(row)
                for row in rows
            ]), 200

        except Exception as e:
            print('Products GET database error:', e)
            return jsonify({'error': 'Unable to load products'}), 500

    # ============================
    # POST / CREATE PRODUCT
    # ============================

    admin = get_current_admin()

    if not admin:
        return jsonify({'error': 'Admin required'}), 403

    data = request.get_json(silent=True) or {}

    try:
        restaurant_id = get_or_create_waterfront_restaurant()

        category_name = data.get('category', 'Fruits')
        category_id = get_or_create_category(
            restaurant_id,
            category_name
        )

        result = db.session.execute(
            text("""
                INSERT INTO meals (
                    restaurant_id,
                    category_id,
                    name,
                    description,
                    price,
                    stock,
                    discount,
                    prep_time,
                    rating,
                    featured,
                    image_url,
                    image_icon,
                    is_available,
                    sort_order
                )
                VALUES (
                    :restaurant_id,
                    :category_id,
                    :name,
                    :description,
                    :price,
                    :stock,
                    :discount,
                    :prep_time,
                    :rating,
                    :featured,
                    :image_url,
                    :image_icon,
                    :is_available,
                    :sort_order
                )
                RETURNING id
            """),
            {
                'restaurant_id': restaurant_id,
                'category_id': category_id,
                'name': data.get('name', ''),
                'description': data.get('description', ''),
                'price': float(data.get('price', 0)),
                'stock': int(data.get('stock', 0)),
                'discount': float(data.get('discount', 0)),
                'prep_time': int(data.get('prep_time', 0)),
                'rating': float(data.get('rating', 0)),
                'featured': int(data.get('featured', 0)),
                'image_url': data.get('image', ''),
                'image_icon': data.get('image_icon', 'fa-apple-alt'),
                'is_available': bool(int(data.get('available', 1))),
                'sort_order': int(data.get('sort_order', 0))
            }
        )

        product_id = result.scalar_one()

        db.session.commit()

        # Keep the existing notification system temporarily.
        save_notification(
            f"New product added: {data.get('name', '')}",
            'inventory'
        )

        row = db.session.execute(
            text("""
                SELECT
                    m.id,
                    m.name,
                    c.name AS category,
                    m.price,
                    m.stock,
                    m.discount,
                    m.prep_time,
                    m.rating,
                    m.featured,
                    m.description,
                    m.image_url,
                    m.image_icon,
                    m.is_available,
                    m.sort_order
                FROM meals m
                JOIN categories c
                    ON c.id = m.category_id
                WHERE m.id = :product_id
            """),
            {'product_id': product_id}
        ).mappings().first()

        return jsonify(product_to_json(row)), 201

    except Exception as e:
        db.session.rollback()
        print('Product CREATE database error:', e)
        return jsonify({'error': 'Unable to create product'}), 500

@app.route('/api/products/<pid>', methods=['GET', 'PUT', 'DELETE'])
def product_detail(pid):

    # ============================
    # GET SINGLE PRODUCT
    # ============================

    if request.method == 'GET':
        try:
            row = db.session.execute(
                text("""
                    SELECT
                        m.id,
                        m.name,
                        c.name AS category,
                        m.price,
                        m.stock,
                        m.discount,
                        m.prep_time,
                        m.rating,
                        m.featured,
                        m.description,
                        m.image_url,
                        m.image_icon,
                        m.is_available,
                        m.sort_order
                    FROM meals m
                    JOIN categories c
                        ON c.id = m.category_id
                    WHERE m.id = :product_id
                      AND m.deleted_at IS NULL
                    LIMIT 1
                """),
                {'product_id': pid}
            ).mappings().first()

            if not row:
                return jsonify({'error': 'Product not found'}), 404

            return jsonify(product_to_json(row)), 200

        except Exception as e:
            print('Product GET database error:', e)
            return jsonify({'error': 'Unable to load product'}), 500

    # ============================
    # ADMIN REQUIRED FOR EDIT/DELETE
    # ============================

    admin = get_current_admin()

    if not admin:
        return jsonify({'error': 'Admin required'}), 403

    # ============================
    # UPDATE PRODUCT
    # ============================

    if request.method == 'PUT':

        data = request.get_json(silent=True) or {}

        try:
            existing = db.session.execute(
                text("""
                    SELECT
                        m.id,
                        m.name,
                        c.name AS category,
                        m.price,
                        m.stock,
                        m.discount,
                        m.prep_time,
                        m.rating,
                        m.featured,
                        m.description,
                        m.image_url,
                        m.image_icon,
                        m.is_available,
                        m.sort_order
                    FROM meals m
                    JOIN categories c
                        ON c.id = m.category_id
                    WHERE m.id = :product_id
                      AND m.deleted_at IS NULL
                    LIMIT 1
                """),
                {'product_id': pid}
            ).mappings().first()

            if not existing:
                return jsonify({'error': 'Product not found'}), 404

            restaurant_id = db.session.execute(
                text("""
                    SELECT restaurant_id
                    FROM meals
                    WHERE id = :product_id
                """),
                {'product_id': pid}
            ).scalar_one()

            category_name = data.get(
                'category',
                existing['category']
            )

            category_id = get_or_create_category(
                str(restaurant_id),
                category_name
            )

            db.session.execute(
                text("""
                    UPDATE meals
                    SET
                        category_id = :category_id,
                        name = :name,
                        description = :description,
                        price = :price,
                        stock = :stock,
                        discount = :discount,
                        prep_time = :prep_time,
                        rating = :rating,
                        featured = :featured,
                        image_url = :image_url,
                        image_icon = :image_icon,
                        is_available = :is_available,
                        sort_order = :sort_order,
                        updated_at = now()
                    WHERE id = :product_id
                """),
                {
                    'product_id': pid,
                    'category_id': category_id,
                    'name': data.get('name', existing['name']),
                    'description': data.get(
                        'description',
                        existing['description'] or ''
                    ),
                    'price': float(
                        data.get('price', existing['price'])
                    ),
                    'stock': int(
                        data.get('stock', existing['stock'])
                    ),
                    'discount': float(
                        data.get('discount', existing['discount'])
                    ),
                    'prep_time': int(
                        data.get('prep_time', existing['prep_time'])
                    ),
                    'rating': float(
                        data.get('rating', existing['rating'])
                    ),
                    'featured': int(
                        data.get('featured', existing['featured'])
                    ),
                    'image_url': data.get(
                        'image',
                        existing['image_url'] or ''
                    ),
                    'image_icon': data.get(
                        'image_icon',
                        existing['image_icon'] or 'fa-apple-alt'
                    ),
                    'is_available': bool(int(
                        data.get(
                            'available',
                            existing['is_available']
                        )
                    )),
                    'sort_order': int(
                        data.get(
                            'sort_order',
                            existing['sort_order']
                        )
                    )
                }
            )

            db.session.commit()

            row = db.session.execute(
                text("""
                    SELECT
                        m.id,
                        m.name,
                        c.name AS category,
                        m.price,
                        m.stock,
                        m.discount,
                        m.prep_time,
                        m.rating,
                        m.featured,
                        m.description,
                        m.image_url,
                        m.image_icon,
                        m.is_available,
                        m.sort_order
                    FROM meals m
                    JOIN categories c
                        ON c.id = m.category_id
                    WHERE m.id = :product_id
                """),
                {'product_id': pid}
            ).mappings().first()

            return jsonify(product_to_json(row)), 200

        except Exception as e:
            db.session.rollback()
            print('Product UPDATE database error:', e)
            return jsonify({'error': 'Unable to update product'}), 500

    # ============================
    # DELETE PRODUCT
    # ============================

    try:
        result = db.session.execute(
            text("""
                UPDATE meals
                SET
                    deleted_at = now(),
                    is_available = false,
                    updated_at = now()
                WHERE id = :product_id
                  AND deleted_at IS NULL
            """),
            {'product_id': pid}
        )

        if result.rowcount == 0:
            db.session.rollback()
            return jsonify({'error': 'Product not found'}), 404

        db.session.commit()

        return jsonify({'success': True}), 200

    except Exception as e:
        db.session.rollback()
        print('Product DELETE database error:', e)
        return jsonify({'error': 'Unable to delete product'}), 500

@app.route('/api/upload', methods=['POST'])
def upload_image():
    admin = get_current_admin()
    if not admin:
        return jsonify({'error': 'Admin required'}), 403

    file = request.files.get('image')
    if not file or not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    try:
        url = save_compressed_image(file)
        return jsonify({'url': url}), 200
    except Exception:
        app.logger.exception('Image compression failed')
        return jsonify({'error': 'Invalid image file'}), 400

# ============================================================
# CHECKOUT / ORDER
# ============================================================

@app.route('/api/checkout', methods=['POST'])
def checkout():
    user = get_current_user()

    if not user:
        return jsonify({'error': 'Please log in to checkout'}), 401

    data = request.get_json(silent=True) or {}

    items = data.get('items') or []
    phone = str(data.get('phone') or '').strip()
    delivery = str(
        data.get('delivery') or data.get('address') or ''
    ).strip()
    note = str(data.get('note') or '').strip()

    if not items:
        return jsonify({'error': 'Cart is empty'}), 400

    if not phone or not delivery:
        return jsonify({
            'error': 'Phone and delivery address are required'
        }), 400

    if not phone.startswith('254') or len(phone) != 12:
        return jsonify({
            'error': 'Phone must use format 2547XXXXXXXX'
        }), 400

    # ---------------------------------------------------------
    # Validate cart and calculate the REAL total from Neon
    # Do not trust price/total sent by the browser.
    # ---------------------------------------------------------
    try:
        restaurant_id = get_or_create_waterfront_restaurant()

        validated_items = []
        subtotal = 0.0

        for item in items:
            meal_id = str(item.get('id') or '').strip()

            try:
                quantity = int(item.get('qty', 0))
            except (TypeError, ValueError):
                quantity = 0

            if not meal_id or quantity <= 0:
                return jsonify({
                    'error': 'Invalid cart item'
                }), 400

            meal = db.session.execute(
                text("""
                    SELECT
                        id,
                        name,
                        price,
                        stock,
                        is_available
                    FROM meals
                    WHERE id = :meal_id
                      AND restaurant_id = :restaurant_id
                      AND deleted_at IS NULL
                    LIMIT 1
                """),
                {
                    'meal_id': meal_id,
                    'restaurant_id': restaurant_id
                }
            ).mappings().first()

            if not meal:
                return jsonify({
                    'error': f'Product {meal_id} was not found'
                }), 404

            if not meal['is_available']:
                return jsonify({
                    'error': f"{meal['name']} is currently unavailable"
                }), 400

            if quantity > int(meal['stock']):
                return jsonify({
                    'error': (
                        f"{meal['name']} only has "
                        f"{meal['stock']} item(s) available"
                    )
                }), 400

            unit_price = float(meal['price'])
            line_total = unit_price * quantity
            subtotal += line_total

            validated_items.append({
                'meal_id': str(meal['id']),
                'meal_name': meal['name'],
                'unit_price': unit_price,
                'quantity': quantity,
                'line_total': line_total
            })

        # Frontend currently calculates tax at 10%.
        tax = round(subtotal * 0.10, 2)
        total = round(subtotal + tax, 2)

        # ---------------------------------------------------------
        # Generate UUIDs ourselves.
        # ---------------------------------------------------------
        import uuid

        order_id = str(uuid.uuid4())
        payment_id = str(uuid.uuid4())
        idempotency_key = str(uuid.uuid4())

        # ---------------------------------------------------------
        # Create order
        # ---------------------------------------------------------
        db.session.execute(
            text("""
                INSERT INTO orders (
                    id,
                    customer_id,
                    restaurant_id,
                    status,
                    subtotal,
                    total,
                    delivery_address,
                    note
                )
                VALUES (
                    :id,
                    :customer_id,
                    :restaurant_id,
                    'pending',
                    :subtotal,
                    :total,
                    :delivery_address,
                    :note
                )
            """),
            {
                'id': order_id,
                'customer_id': str(user['id']),
                'restaurant_id': restaurant_id,
                'subtotal': subtotal,
                'total': total,
                'delivery_address': delivery,
                'note': note
            }
        )

        # ---------------------------------------------------------
        # Create order items
        # ---------------------------------------------------------
        for item in validated_items:
            db.session.execute(
                text("""
                    INSERT INTO order_items (
                        id,
                        order_id,
                        meal_id,
                        meal_name,
                        unit_price,
                        quantity,
                        line_total
                    )
                    VALUES (
                        :id,
                        :order_id,
                        :meal_id,
                        :meal_name,
                        :unit_price,
                        :quantity,
                        :line_total
                    )
                """),
                {
                    'id': str(uuid.uuid4()),
                    'order_id': order_id,
                    'meal_id': item['meal_id'],
                    'meal_name': item['meal_name'],
                    'unit_price': item['unit_price'],
                    'quantity': item['quantity'],
                    'line_total': item['line_total']
                }
            )

        # ---------------------------------------------------------
        # Create pending payment BEFORE calling M-Pesa.
        # This prevents callback race conditions.
        # ---------------------------------------------------------
        db.session.execute(
            text("""
                INSERT INTO payments (
                    id,
                    order_id,
                    phone,
                    amount,
                    status,
                    idempotency_key
                )
                VALUES (
                    :id,
                    :order_id,
                    :phone,
                    :amount,
                    'pending',
                    :idempotency_key
                )
            """),
            {
                'id': payment_id,
                'order_id': order_id,
                'phone': phone,
                'amount': total,
                'idempotency_key': idempotency_key
            }
        )

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        print('Checkout database error:', e)

        return jsonify({
            'error': 'Unable to create order'
        }), 500

    # ---------------------------------------------------------
    # Send M-Pesa STK Push
    # ---------------------------------------------------------
    try:
        mpesa_response = send_stk_push(
            phone,
            total,
            f'ORDER-{order_id}'
        )

    except requests.RequestException as error:
        print('M-Pesa request failed:', error)

        try:
            db.session.execute(
                text("""
                    UPDATE payments
                    SET status = 'failed'
                    WHERE id = :payment_id
                """),
                {'payment_id': payment_id}
            )

            db.session.execute(
                text("""
                    UPDATE orders
                    SET status = 'cancelled',
                        updated_at = now()
                    WHERE id = :order_id
                """),
                {'order_id': order_id}
            )

            db.session.commit()

        except Exception as db_error:
            db.session.rollback()
            print('Failed to update failed payment:', db_error)

        return jsonify({
            'error': 'M-Pesa request failed'
        }), 502

    # ---------------------------------------------------------
    # Check M-Pesa response
    # ---------------------------------------------------------
    if mpesa_response.get('ResponseCode') != '0':
        description = mpesa_response.get(
            'ResponseDescription',
            'STK push was rejected'
        )

        try:
            db.session.execute(
                text("""
                    UPDATE payments
                    SET status = 'failed',
                        provider_payload = :payload
                    WHERE id = :payment_id
                """),
                {
                    'payment_id': payment_id,
                    'payload': json.dumps(mpesa_response)
                }
            )

            db.session.execute(
                text("""
                    UPDATE orders
                    SET status = 'cancelled',
                        updated_at = now()
                    WHERE id = :order_id
                """),
                {'order_id': order_id}
            )

            db.session.commit()

        except Exception as db_error:
            db.session.rollback()
            print('Failed to save rejected payment:', db_error)

        return jsonify({
            'error': description
        }), 400

    checkout_id = mpesa_response.get('CheckoutRequestID')

    if not checkout_id:
        return jsonify({
            'error': 'M-Pesa did not return a checkout reference'
        }), 502

    # ---------------------------------------------------------
    # Save M-Pesa checkout request ID
    # ---------------------------------------------------------
    try:
        db.session.execute(
            text("""
                UPDATE payments
                SET checkout_request_id = :checkout_id,
                    provider_payload = :payload
                WHERE id = :payment_id
            """),
            {
                'checkout_id': checkout_id,
                'payload': json.dumps(mpesa_response),
                'payment_id': payment_id
            }
        )

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        print('Payment update error:', e)

        return jsonify({
            'error': 'Unable to save payment reference'
        }), 500

    print(
        f'Order created: {order_id} | '
        f'Payment: {payment_id} | '
        f'Checkout: {checkout_id}'
    )

    return jsonify({
        'success': True,
        'order_id': order_id,
        'checkoutRequestId': checkout_id,
        'payment_id': payment_id,
        'subtotal': subtotal,
        'tax': tax,
        'total': total
    }), 201

# ============================================================
# CHECKOUT STATUS
# ============================================================

@app.route('/api/checkout/status', methods=['GET'])
def checkout_status():
    checkout_id = request.args.get('checkoutId')

    if not checkout_id:
        return jsonify({
            'error': 'Missing checkout ID'
        }), 400

    try:
        payment = db.session.execute(
            text("""
                SELECT
                    id,
                    order_id,
                    status,
                    checkout_request_id,
                    receipt_number
                FROM payments
                WHERE checkout_request_id = :checkout_id
                LIMIT 1
            """),
            {'checkout_id': checkout_id}
        ).mappings().first()

        if not payment:
            return jsonify({
                'error': 'Checkout not found'
            }), 404

        current_status = payment['status']

        # Already completed/failed.
        if current_status != 'pending':
            return jsonify({
                'status': current_status,
                'paymentId': str(payment['id'])
            }), 200

        # -----------------------------------------------------
        # Ask Safaricom for current payment status.
        # -----------------------------------------------------
        try:
            result = query_mpesa_status(checkout_id)

            result_code = result.get('ResultCode')

            if str(result_code) == '0':
                metadata = (
                    result.get('CallbackMetadata', {}).get('Item', [])
                )

                receipt = next(
                    (
                        item.get('Value')
                        for item in metadata
                        if item.get('Name') == 'MpesaReceiptNumber'
                    ),
                    None
                )

                db.session.execute(
                    text("""
                        UPDATE payments
                        SET status = 'completed',
                            receipt_number = :receipt,
                            paid_at = now(),
                            provider_payload = :payload
                        WHERE id = :payment_id
                    """),
                    {
                        'receipt': str(receipt) if receipt else None,
                        'payload': json.dumps(result),
                        'payment_id': str(payment['id'])
                    }
                )

                db.session.execute(
                    text("""
                        UPDATE orders
                        SET status = 'paid',
                            paid_at = now(),
                            updated_at = now()
                        WHERE id = :order_id
                    """),
                    {
                        'order_id': str(payment['order_id'])
                    }
                )

                db.session.commit()

                current_status = 'completed'

            elif str(result_code) in (
                '1032',
                '1037',
                '1',
                '2'
            ):
                db.session.execute(
                    text("""
                        UPDATE payments
                        SET status = 'failed',
                            provider_payload = :payload
                        WHERE id = :payment_id
                    """),
                    {
                        'payload': json.dumps(result),
                        'payment_id': str(payment['id'])
                    }
                )

                db.session.execute(
                    text("""
                        UPDATE orders
                        SET status = 'cancelled',
                            updated_at = now()
                        WHERE id = :order_id
                    """),
                    {
                        'order_id': str(payment['order_id'])
                    }
                )

                db.session.commit()

                current_status = 'failed'

        except requests.RequestException as error:
            print(
                'M-Pesa status query failed:',
                error
            )

        return jsonify({
            'status': current_status,
            'paymentId': str(payment['id'])
        }), 200

    except Exception as e:
        db.session.rollback()
        print('Checkout status database error:', e)

        return jsonify({
            'error': 'Unable to check payment status'
        }), 500

# ============================================================
# M-PESA CALLBACK
# ============================================================

@app.route('/api/mpesa/callback', methods=['POST'])
def mpesa_callback():
    callback = request.get_json(silent=True) or {}

    print('M-Pesa callback received:', json.dumps(callback))

    stk_callback = (
        callback
        .get('Body', {})
        .get('stkCallback', {})
    )

    checkout_id = stk_callback.get('CheckoutRequestID')
    result_code = stk_callback.get('ResultCode')

    if not checkout_id:
        return jsonify({
            'ResultCode': 0,
            'ResultDesc': 'Accepted'
        }), 200

    try:
        payment = db.session.execute(
            text("""
                SELECT
                    id,
                    order_id,
                    status
                FROM payments
                WHERE checkout_request_id = :checkout_id
                LIMIT 1
            """),
            {
                'checkout_id': checkout_id
            }
        ).mappings().first()

        # Always acknowledge Safaricom's callback.
        if not payment:
            print(
                'Callback payment not found:',
                checkout_id
            )

            return jsonify({
                'ResultCode': 0,
                'ResultDesc': 'Accepted'
            }), 200

        # Ignore duplicate callback.
        if payment['status'] == 'completed':
            return jsonify({
                'ResultCode': 0,
                'ResultDesc': 'Accepted'
            }), 200

        if str(result_code) == '0':
            metadata = (
                stk_callback
                .get('CallbackMetadata', {})
                .get('Item', [])
            )

            receipt = next(
                (
                    item.get('Value')
                    for item in metadata
                    if item.get('Name') == 'MpesaReceiptNumber'
                ),
                None
            )

            db.session.execute(
                text("""
                    UPDATE payments
                    SET status = 'completed',
                        receipt_number = :receipt,
                        paid_at = now(),
                        provider_payload = :payload
                    WHERE id = :payment_id
                """),
                {
                    'receipt': str(receipt) if receipt else None,
                    'payload': json.dumps(callback),
                    'payment_id': str(payment['id'])
                }
            )

            db.session.execute(
                text("""
                    UPDATE orders
                    SET status = 'paid',
                        paid_at = now(),
                        updated_at = now()
                    WHERE id = :order_id
                """),
                {
                    'order_id': str(payment['order_id'])
                }
            )

            db.session.execute(
                text("""
                    INSERT INTO payment_events (
                        id,
                        payment_id,
                        payload
                    )
                    VALUES (
                        :id,
                        :payment_id,
                        :payload
                    )
                """),
                {
                    'id': str(uuid.uuid4()),
                    'payment_id': str(payment['id']),
                    'payload': json.dumps(callback)
                }
            )

            db.session.commit()

            print(
                f'Payment completed: '
                f'{checkout_id} | receipt={receipt}'
            )

        else:
            db.session.execute(
                text("""
                    UPDATE payments
                    SET status = 'failed',
                        provider_payload = :payload
                    WHERE id = :payment_id
                """),
                {
                    'payload': json.dumps(callback),
                    'payment_id': str(payment['id'])
                }
            )

            db.session.execute(
                text("""
                    UPDATE orders
                    SET status = 'cancelled',
                        updated_at = now()
                    WHERE id = :order_id
                """),
                {
                    'order_id': str(payment['order_id'])
                }
            )

            db.session.execute(
                text("""
                    INSERT INTO payment_events (
                        id,
                        payment_id,
                        payload
                    )
                    VALUES (
                        :id,
                        :payment_id,
                        :payload
                    )
                """),
                {
                    'id': str(uuid.uuid4()),
                    'payment_id': str(payment['id']),
                    'payload': json.dumps(callback)
                }
            )

            db.session.commit()

            print(
                f'Payment failed: '
                f'{checkout_id} | ResultCode={result_code}'
            )

    except Exception as e:
        db.session.rollback()
        print('M-Pesa callback database error:', e)

    # Safaricom should receive 200 even if our internal
    # processing has an issue.
    return jsonify({
        'ResultCode': 0,
        'ResultDesc': 'Accepted'
    }), 200
# ============================
# ADMIN ROUTES
# ============================
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
   
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    print(f"🔐 Admin login attempt: username='{username}', password='{password}'")  # Debug

    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400

    # Ensure admin exists
    if username not in admins:
        admins[username] = {
            'username': username,
            'password_hash': generate_password_hash(username)  # default
        }
        print(f"🆕 Created new admin: {username}")

    admin = admins[username]

    # ----- DEMO FALLBACK: accept both 'admin' and 'admin123' for the default admin -----
    if username == 'admin' and password in ('admin', 'admin123'):
        # Force the hash to match the entered password (so it works next time too)
        admins['admin']['password_hash'] = generate_password_hash(password)
        session['admin_username'] = username
        return jsonify({'success': True, 'username': username}), 200

    # Normal hash check
    if check_password_hash(admin['password_hash'], password):
        session['admin_username'] = username
        return jsonify({'success': True, 'username': username}), 200

    return jsonify({'error': 'Invalid credentials'}), 401
@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('admin_username', None)
    return jsonify({'success': True}), 200

@app.route('/api/admin/status', methods=['GET'])
def admin_status():
    admin = get_current_admin()
    if admin:
        return jsonify({'username': admin['username']}), 200
    return jsonify({'error': 'Not logged in'}), 401

@app.route('/api/stats', methods=['GET'])
def stats():
    admin = get_current_admin()
    if not admin:
        return jsonify({'error': 'Admin required'}), 403
    total_products = len(products)
    total_orders = len(orders)
    total_revenue = sum(o['total'] for o in orders.values() if o.get('status') in ['paid', 'delivered', 'completed'])
    pending_orders = len([o for o in orders.values() if o.get('status') == 'pending'])
    total_users = len(users)
    return jsonify({
        'total_products': total_products,
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'pending_orders': pending_orders,
        'total_users': total_users
    }), 200

@app.route('/api/orders', methods=['GET'])
def admin_orders():
    admin = get_current_admin()
    if not admin:
        return jsonify({'error': 'Admin required'}), 403
    order_list = sorted(orders.values(), key=lambda o: o['created_at'], reverse=True)
    return jsonify(order_list), 200

@app.route('/api/orders/<int:oid>/status', methods=['PUT'])
def update_order_status(oid):
    admin = get_current_admin()
    if not admin:
        return jsonify({'error': 'Admin required'}), 403
    if oid not in orders:
        return jsonify({'error': 'Order not found'}), 404
    data = request.get_json()
    new_status = data.get('status')
    if new_status not in ['pending', 'preparing', 'dispatched', 'delivered', 'cancelled', 'paid']:
        return jsonify({'error': 'Invalid status'}), 400
    orders[oid]['status'] = new_status
    save_notification(f"Order #{oid} status updated to {new_status}", 'order')
    return jsonify({'success': True}), 200

@app.route('/api/orders/<int:oid>', methods=['DELETE'])
def delete_order(oid):
    admin = get_current_admin()
    if not admin:
        return jsonify({'error': 'Admin required'}), 403
    if oid in orders:
        del orders[oid]
        return jsonify({'success': True}), 200
    return jsonify({'error': 'Order not found'}), 404

@app.route('/api/payments', methods=['GET'])
def admin_payments():
    admin = get_current_admin()
    if not admin:
        return jsonify({'error': 'Admin required'}), 403
    payment_list = sorted(payments.values(), key=lambda p: p['created_at'], reverse=True)
    return jsonify(payment_list), 200

@app.route('/api/payments/<int:pid>', methods=['DELETE'])
def delete_payment(pid):
    admin = get_current_admin()
    if not admin:
        return jsonify({'error': 'Admin required'}), 403
    if pid in payments:
        del payments[pid]
        return jsonify({'success': True}), 200
    return jsonify({'error': 'Payment not found'}), 404

@app.route('/api/users', methods=['GET'])
def admin_users():
    admin = get_current_admin()
    if not admin:
        return jsonify({'error': 'Admin required'}), 403
    user_list = []
    for uid, u in users.items():
        user_orders = [o for o in orders.values() if o.get('user_id') == uid]
        order_count = len(user_orders)
        total_spent = sum(o['total'] for o in user_orders if o.get('status') in ['paid', 'delivered', 'completed'])
        u_copy = u.copy()
        u_copy['order_count'] = order_count
        u_copy['total_spent'] = total_spent
        u_copy.pop('password_hash', None)
        user_list.append(u_copy)
    return jsonify(user_list), 200

@app.route('/api/users/<int:uid>', methods=['DELETE'])
def delete_user(uid):
    admin = get_current_admin()
    if not admin:
        return jsonify({'error': 'Admin required'}), 403
    if uid in users:
        del users[uid]
        return jsonify({'success': True}), 200
    return jsonify({'error': 'User not found'}), 404

@app.route('/api/deliveries', methods=['GET', 'POST'])
def deliveries_route():
    admin = get_current_admin()
    if not admin:
        return jsonify({'error': 'Admin required'}), 403
    if request.method == 'GET':
        return jsonify(list(deliveries.values())), 200
    else:
        data = request.get_json()
        global delivery_id_counter
        did = delivery_id_counter
        delivery_id_counter += 1
        delivery = {
            'id': did,
            'name': data.get('name', ''),
            'phone': data.get('phone', ''),
            'orders': int(data.get('orders', 0)),
            'status': data.get('status', 'active'),
            'last_delivery': data.get('last_delivery', datetime.now().isoformat())
        }
        deliveries[did] = delivery
        return jsonify(delivery), 201

@app.route('/api/deliveries/<int:did>', methods=['PUT', 'DELETE'])
def delivery_detail(did):
    admin = get_current_admin()
    if not admin:
        return jsonify({'error': 'Admin required'}), 403
    if did not in deliveries:
        return jsonify({'error': 'Delivery not found'}), 404
    if request.method == 'PUT':
        data = request.get_json()
        d = deliveries[did]
        d['name'] = data.get('name', d['name'])
        d['phone'] = data.get('phone', d['phone'])
        d['orders'] = int(data.get('orders', d['orders']))
        d['status'] = data.get('status', d['status'])
        d['last_delivery'] = data.get('last_delivery', d['last_delivery'])
        return jsonify(d), 200
    else:
        del deliveries[did]
        return jsonify({'success': True}), 200

@app.route('/api/debts', methods=['GET', 'POST'])
def debts_route():
    admin = get_current_admin()
    if not admin:
        return jsonify({'error': 'Admin required'}), 403
    if request.method == 'GET':
        return jsonify(list(debts.values())), 200
    else:
        data = request.get_json()
        global debt_id_counter
        did = debt_id_counter
        debt_id_counter += 1
        debt = {
            'id': did,
            'customer': data.get('customer', ''),
            'phone': data.get('phone', ''),
            'amount_owed': float(data.get('amount_owed', 0)),
            'paid': float(data.get('paid', 0)),
            'due_date': data.get('due_date', ''),
            'created_at': datetime.now().isoformat()
        }
        debts[did] = debt
        return jsonify(debt), 201

@app.route('/api/debts/<int:did>', methods=['PUT', 'DELETE'])
def debt_detail(did):
    admin = get_current_admin()
    if not admin:
        return jsonify({'error': 'Admin required'}), 403
    if did not in debts:
        return jsonify({'error': 'Debt not found'}), 404
    if request.method == 'PUT':
        data = request.get_json()
        d = debts[did]
        d['customer'] = data.get('customer', d['customer'])
        d['phone'] = data.get('phone', d['phone'])
        d['amount_owed'] = float(data.get('amount_owed', d['amount_owed']))
        d['paid'] = float(data.get('paid', d['paid']))
        d['due_date'] = data.get('due_date', d['due_date'])
        return jsonify(d), 200
    else:
        del debts[did]
        return jsonify({'success': True}), 200

@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    admin = get_current_admin()
    if not admin:
        return jsonify({'error': 'Admin required'}), 403
    return jsonify(notifications), 200


# ...existing code...

@app.route('/api/user/notifications', methods=['GET'])
def user_notifications():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    user_orders = [
        {
            'id': order['id'],
            'status': order.get('status', 'pending'),
            'created_at': order.get('created_at'),
            'total': order.get('total', 0)
        }
        for order in orders.values()
        if order.get('user_id') == user['id']
    ]

    return jsonify({'orders': user_orders}), 200

# ...existing code...

# ============================
# SERVE HTML PAGES
# ============================

@app.route('/')
def customer_app():
    return render_template('index.html')

@app.route('/admin')
def admin_panel():
    return render_template('admin.html')

# Static files
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

# ============================
# SEED DATA (demo)
# ============================

def seed_data():
    global user_id_counter, product_id_counter, order_id_counter, payment_id_counter
    if not users:
        hashed = generate_password_hash('password123')
        users[1] = {
            'id': 1,
            'name': 'John Doe',
            'email': 'john@example.com',
            'password_hash': hashed,
            'phone': '254745972350',
            'address': 'Kimathi Street',
            'created_at': datetime.now().isoformat(),
            'favorites': [],
            'addresses': []
        }
        user_id_counter = 2

    if not products:
        sample_products = [
            {'id': 1, 'name': 'Organic Apple', 'category': 'Fruits', 'price': 2.99, 'stock': 25, 'discount': 0, 'prep_time': 5, 'rating': 4.5, 'featured': 1, 'description': 'Fresh organic apples', 'image': '', 'image_icon': 'fa-apple-alt', 'available': 1, 'sort_order': 1},
          {'id': 7, 'name': 'Tomato', 'category': 'Veggies', 'price': 1.49, 'stock': 3, 'discount': 0, 'prep_time': 5, 'rating': 3.9, 'featured': 0, 'description': 'Ripe tomatoes', 'image': '', 'image_icon': 'fa-apple-alt', 'available': 1, 'sort_order': 7},
        ]
        for p in sample_products:
            products[p['id']] = p
        product_id_counter = 9

  

   

# Seed on startup
with app.app_context():
    seed_data()

# ============================
# RUN
# ============================
if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.getenv('PORT', 5000)),
        debug=False
    )