import os
import json
import sqlite3
import uuid
import threading
import time
from flask import Flask, request, jsonify, render_template, send_from_directory, session
from werkzeug.utils import secure_filename
from flask_bcrypt import Bcrypt

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
bcrypt = Bcrypt(app)

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def column_exists(db, table, column):
    cursor = db.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())

def init_db():
    with app.app_context():
        db = get_db()
        # Products
        db.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                description TEXT,
                category TEXT,
                image TEXT,
                image_icon TEXT,
                rating REAL DEFAULT 4.0,
                delivery TEXT,
                stock INTEGER DEFAULT 0,
                available BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Orders
        db.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                items TEXT,
                total REAL,
                phone TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Payments
        db.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                phone TEXT,
                amount REAL,
                status TEXT DEFAULT 'pending',
                transaction_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Admin
        db.execute('''
            CREATE TABLE IF NOT EXISTS admin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        ''')
        # Users (with password_hash)
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Ensure missing columns (for upgrades)
        for col, dtype in [('image','TEXT'),('stock','INTEGER DEFAULT 0'),('available','BOOLEAN DEFAULT 1'),('image_icon','TEXT')]:
            if not column_exists(db, 'products', col):
                db.execute(f'ALTER TABLE products ADD COLUMN {col} {dtype}')
        if not column_exists(db, 'orders', 'phone'):
            db.execute('ALTER TABLE orders ADD COLUMN phone TEXT')
        if not column_exists(db, 'orders', 'status'):
            db.execute('ALTER TABLE orders ADD COLUMN status TEXT DEFAULT "pending"')
        if not column_exists(db, 'users', 'password_hash'):
            db.execute('ALTER TABLE users ADD COLUMN password_hash TEXT')

        db.execute('CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_products_name ON products(name)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)')

        # Create default admin if none exists
        cur = db.execute('SELECT COUNT(*) FROM admin')
        if cur.fetchone()[0] == 0:
            default_password = 'admin123'
            hashed = bcrypt.generate_password_hash(default_password).decode('utf-8')
            db.execute('INSERT INTO admin (username, password_hash) VALUES (?, ?)', ('admin', hashed))
            print(f"✅ Default admin created: admin / {default_password}")

        # Seed sample products if empty
        cur = db.execute('SELECT COUNT(*) FROM products')
        if cur.fetchone()[0] == 0:
            sample_products = [
                {'name': 'Orange', 'price': 30.00, 'description': 'Enjoy the pure, wholesome benefits.', 'category': 'Fruits', 'image_icon': 'fa-apple-whole', 'rating': 4.5, 'delivery': 'Time to ship', 'stock': 50},
                {'name': 'Banana', 'price': 25.00, 'description': 'Rich in potassium.', 'category': 'Fruits', 'image_icon': 'fa-banana', 'rating': 4.2, 'delivery': 'Fast shipping', 'stock': 30},
                {'name': 'Sourdough Bread', 'price': 45.00, 'description': 'Artisanal sourdough.', 'category': 'Breads', 'image_icon': 'fa-bread-slice', 'rating': 4.8, 'delivery': 'Fresh daily', 'stock': 20},
                {'name': 'Carrot', 'price': 15.00, 'description': 'Crunchy and sweet.', 'category': 'Veggies', 'image_icon': 'fa-carrot', 'rating': 4.0, 'delivery': 'Locally sourced', 'stock': 40},
                {'name': 'Milk', 'price': 20.00, 'description': 'Fresh whole milk.', 'category': 'Dairy', 'image_icon': 'fa-glass-milk', 'rating': 4.3, 'delivery': 'Chilled delivery', 'stock': 15},
                {'name': 'Green Salad', 'price': 35.00, 'description': 'Mixed greens with vinaigrette.', 'category': 'Salad', 'image_icon': 'fa-leaf', 'rating': 4.6, 'delivery': 'Ready to eat', 'stock': 10},
                {'name': 'Orange Juice', 'price': 40.00, 'description': 'Freshly squeezed, no sugar.', 'category': 'Drinks', 'image_icon': 'fa-wine-bottle', 'rating': 4.7, 'delivery': 'Chilled', 'stock': 25},
            ]
            for p in sample_products:
                db.execute('''INSERT INTO products (name, price, description, category, image_icon, rating, delivery, stock) VALUES (?,?,?,?,?,?,?,?)''',
                           (p['name'], p['price'], p['description'], p['category'], p['image_icon'], p['rating'], p['delivery'], p['stock']))
            db.commit()
        db.close()

init_db()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def admin_required():
    if not session.get('admin_logged_in'):
        return jsonify({'error': 'Unauthorized – admin login required'}), 401
    return None

# ---------- Serve HTML ----------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js'), 200, {'Content-Type': 'application/javascript'}

# ---------- API: Products ----------
@app.route('/api/products', methods=['GET'])
def get_products():
    db = get_db()
    products = db.execute('SELECT * FROM products ORDER BY id DESC').fetchall()
    db.close()
    return jsonify([dict(row) for row in products])

@app.route('/api/products', methods=['POST'])
def add_product():
    auth_err = admin_required()
    if auth_err: return auth_err
    data = request.get_json()
    db = get_db()
    db.execute('''INSERT INTO products (name, price, description, category, image, image_icon, rating, delivery, stock, available) VALUES (?,?,?,?,?,?,?,?,?,?)''',
               (data['name'], data['price'], data['description'], data['category'], data.get('image'), data.get('image_icon','fa-apple-alt'), data.get('rating',4.0), data.get('delivery','Delivered'), data.get('stock',0), data.get('available',1)))
    db.commit()
    db.close()
    return jsonify({'status': 'created'}), 201

@app.route('/api/products/<int:pid>', methods=['PUT'])
def update_product(pid):
    auth_err = admin_required()
    if auth_err: return auth_err
    data = request.get_json()
    db = get_db()
    db.execute('''UPDATE products SET name=?, price=?, description=?, category=?, image=?, image_icon=?, rating=?, delivery=?, stock=?, available=? WHERE id=?''',
               (data['name'], data['price'], data['description'], data['category'], data.get('image'), data.get('image_icon','fa-apple-alt'), data.get('rating',4.0), data.get('delivery','Delivered'), data.get('stock',0), data.get('available',1), pid))
    db.commit()
    db.close()
    return jsonify({'status': 'updated'})

@app.route('/api/products/<int:pid>', methods=['DELETE'])
def delete_product(pid):
    auth_err = admin_required()
    if auth_err: return auth_err
    db = get_db()
    db.execute('DELETE FROM products WHERE id = ?', (pid,))
    db.commit()
    db.close()
    return jsonify({'status': 'deleted'})

@app.route('/api/upload', methods=['POST'])
def upload_image():
    auth_err = admin_required()
    if auth_err: return auth_err
    if 'image' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400
    filename = secure_filename(file.filename)
    unique = str(uuid.uuid4()) + '_' + filename
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique))
    return jsonify({'filename': unique, 'url': f'/static/uploads/{unique}'})

# ---------- API: User Auth (server-side) ----------
@app.route('/api/user/login', methods=['POST'])
def user_login():
    data = request.get_json()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    db = get_db()
    user = db.execute('SELECT id, name, password_hash FROM users WHERE email = ?', (email,)).fetchone()
    db.close()
    # If user exists and password_hash is not None, verify
    if user and user['password_hash'] is not None:
        if bcrypt.check_password_hash(user['password_hash'], password):
            session['user_logged_in'] = True
            session['user_email'] = email
            session['user_name'] = user['name']
            return jsonify({'message': 'Login successful', 'name': user['name']}), 200
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/user/logout', methods=['POST'])
def user_logout():
    session.pop('user_logged_in', None)
    session.pop('user_email', None)
    session.pop('user_name', None)
    return jsonify({'message': 'Logged out'}), 200

@app.route('/api/user/status', methods=['GET'])
def user_status():
    if session.get('user_logged_in'):
        return jsonify({
            'logged_in': True,
            'email': session.get('user_email'),
            'name': session.get('user_name')
        }), 200
    return jsonify({'logged_in': False}), 401

# ---------- API: Signup (stores hashed password) ----------
@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.get_json()
    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    if not name or not email or not password:
        return jsonify({'error': 'Name, email, and password required'}), 400
    db = get_db()
    existing = db.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
    if existing:
        db.close()
        return jsonify({'error': 'Email already registered'}), 409
    hashed = bcrypt.generate_password_hash(password).decode('utf-8')
    db.execute('INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)',
               (name, email, hashed))
    db.commit()
    db.close()
    return jsonify({'message': 'User created'}), 201

# ---------- API: Admin Auth ----------
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    db = get_db()
    admin = db.execute('SELECT * FROM admin WHERE username = ?', (username,)).fetchone()
    db.close()
    if admin and bcrypt.check_password_hash(admin['password_hash'], password):
        session['admin_logged_in'] = True
        session['admin_username'] = username
        return jsonify({'message': 'Login successful'}), 200
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    return jsonify({'message': 'Logged out'}), 200

@app.route('/api/admin/status', methods=['GET'])
def admin_status():
    if session.get('admin_logged_in'):
        return jsonify({'logged_in': True, 'username': session.get('admin_username')}), 200
    return jsonify({'logged_in': False}), 401

# ---------- API: Users (for admin) ----------
@app.route('/api/users', methods=['GET'])
def get_users():
    auth_err = admin_required()
    if auth_err: return auth_err
    db = get_db()
    users = db.execute('SELECT id, name, email, created_at FROM users ORDER BY created_at DESC').fetchall()
    db.close()
    return jsonify([dict(row) for row in users])

@app.route('/api/users/<int:uid>', methods=['DELETE'])
def delete_user(uid):
    auth_err = admin_required()
    if auth_err: return auth_err
    db = get_db()
    db.execute('DELETE FROM users WHERE id = ?', (uid,))
    db.commit()
    db.close()
    return jsonify({'status': 'deleted'})

# ---------- API: Orders ----------
@app.route('/api/orders', methods=['GET'])
def get_orders():
    auth_err = admin_required()
    if auth_err: return auth_err
    db = get_db()
    orders = db.execute('SELECT * FROM orders ORDER BY created_at DESC').fetchall()
    db.close()
    return jsonify([dict(row) for row in orders])

@app.route('/api/orders/<int:oid>', methods=['PUT'])
def update_order_status(oid):
    auth_err = admin_required()
    if auth_err: return auth_err
    data = request.get_json()
    status = data.get('status')
    db = get_db()
    db.execute('UPDATE orders SET status = ? WHERE id = ?', (status, oid))
    db.commit()
    db.close()
    return jsonify({'status': 'updated'})

@app.route('/api/orders/<int:oid>', methods=['DELETE'])
def delete_order(oid):
    auth_err = admin_required()
    if auth_err: return auth_err
    db = get_db()
    db.execute('DELETE FROM orders WHERE id = ?', (oid,))
    db.commit()
    db.close()
    return jsonify({'status': 'deleted'})

# ---------- API: Payments ----------
@app.route('/api/payments', methods=['GET'])
def get_payments():
    auth_err = admin_required()
    if auth_err: return auth_err
    db = get_db()
    payments = db.execute('SELECT * FROM payments ORDER BY created_at DESC').fetchall()
    db.close()
    return jsonify([dict(row) for row in payments])

@app.route('/api/payments/<int:pid>', methods=['DELETE'])
def delete_payment(pid):
    auth_err = admin_required()
    if auth_err: return auth_err
    db = get_db()
    db.execute('DELETE FROM payments WHERE id = ?', (pid,))
    db.commit()
    db.close()
    return jsonify({'status': 'deleted'})

# ---------- API: Checkout (mock M‑PESA) ----------
@app.route('/api/checkout', methods=['POST'])
def checkout():
    data = request.get_json()
    items = data.get('items', [])
    total = data.get('total', 0)
    phone = data.get('phone', '')
    db = get_db()
    cursor = db.execute('INSERT INTO orders (items, total, phone) VALUES (?, ?, ?)', (json.dumps(items), total, phone))
    db.commit()
    order_id = cursor.lastrowid
    db.close()

    def process_payment():
        time.sleep(2)
        db2 = get_db()
        db2.execute('UPDATE orders SET status = "paid" WHERE id = ?', (order_id,))
        db2.execute('INSERT INTO payments (order_id, phone, amount, status, transaction_id) VALUES (?, ?, ?, ?, ?)',
                    (order_id, phone, total, 'completed', 'MPESA' + str(order_id)))
        db2.commit()
        db2.close()

    threading.Thread(target=process_payment).start()
    return jsonify({'status': 'order_placed', 'order_id': order_id, 'message': 'Payment initiated'})

# ---------- API: Stats ----------
@app.route('/api/stats', methods=['GET'])
def get_stats():
    auth_err = admin_required()
    if auth_err: return auth_err
    db = get_db()
    total_products = db.execute('SELECT COUNT(*) as count FROM products').fetchone()['count']
    total_orders = db.execute('SELECT COUNT(*) as count FROM orders').fetchone()['count']
    total_revenue = db.execute('SELECT SUM(total) as sum FROM orders WHERE status="paid"').fetchone()['sum'] or 0
    pending_orders = db.execute('SELECT COUNT(*) as count FROM orders WHERE status="pending"').fetchone()['count']
    db.close()
    return jsonify({
        'total_products': total_products,
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'pending_orders': pending_orders
    })

# ---------- Error handlers ----------
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)