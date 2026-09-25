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
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps

app = Flask(__name__)

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
    if user_id and user_id in users:
        return users[user_id]
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
   
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    for uid, user in users.items():
        if user['email'] == email:
            if check_password_hash(user['password_hash'], password):
                session.permanent = True
                session['user_id'] = user['id']
                return jsonify({'success': True, 'name': user['name']}), 200
            else:
                return jsonify({'error': 'Invalid credentials'}), 401
    return jsonify({'error': 'User not found'}), 404

@app.route('/api/user/logout', methods=['POST'])
def user_logout():
    session.pop('user_id', None)
    return jsonify({'success': True}), 200

@app.route('/api/signup', methods=['POST'])
def signup():
    global user_id_counter
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    if not name or not email or not password:
        return jsonify({'error': 'All fields required'}), 400
    for user in users.values():
        if user['email'] == email:
            return jsonify({'error': 'Email already registered'}), 400
    hashed = generate_password_hash(password)
    uid = user_id_counter
    user_id_counter += 1
    users[uid] = {
        'id': uid,
        'name': name,
        'email': email,
        'password_hash': hashed,
        'phone': '',
        'address': '',
        'created_at': datetime.now().isoformat(),
        'favorites': [],
        'addresses': []
    }
    return jsonify({'success': True, 'name': name}), 201

@app.route('/api/user/profile', methods=['GET', 'PUT'])
def user_profile():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    if request.method == 'GET':
        return jsonify({
            'user': {
                'id': user['id'],
                'name': user['name'],
                'email': user['email'],
                'phone': user.get('phone', ''),
                'address': user.get('address', ''),
                'created_at': user.get('created_at')
            },
            'favorites': user.get('favorites', []),
            'addresses': user.get('addresses', []),
            'orders': sorted(
    [
        order for order in orders.values()
        if order.get('user_id') == user['id']
    ],
    key=lambda order: order.get('created_at', ''),
    reverse=True
)
        }), 200
    else:
        data = request.get_json()
        if 'name' in data:
            user['name'] = data['name']
        if 'phone' in data:
            user['phone'] = data['phone']
        if 'address' in data:
            user['address'] = data['address']
        return jsonify({'success': True}), 200

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
# PRODUCT ROUTES
# ============================

@app.route('/api/products', methods=['GET', 'POST'])
def products_list():
    if request.method == 'GET':
        return jsonify(list(products.values())), 200
    else:
        admin = get_current_admin()
        if not admin:
            return jsonify({'error': 'Admin required'}), 403
        data = request.get_json()
        global product_id_counter
        new_id = product_id_counter
        product_id_counter += 1
        product = {
            'id': new_id,
            'name': data.get('name', ''),
            'category': data.get('category', 'Fruits'),
            'price': float(data.get('price', 0)),
            'stock': int(data.get('stock', 0)),
            'discount': float(data.get('discount', 0)),
            'prep_time': int(data.get('prep_time', 0)),
            'rating': float(data.get('rating', 0)),
            'featured': int(data.get('featured', 0)),
            'description': data.get('description', ''),
            'image': data.get('image', ''),
            'image_icon': data.get('image_icon', 'fa-apple-alt'),
            'available': int(data.get('available', 1)),
            'sort_order': int(data.get('sort_order', 0))
        }
        products[new_id] = product
        save_notification(f"New product added: {product['name']}", 'inventory')
        return jsonify(product), 201

@app.route('/api/products/<int:pid>', methods=['GET', 'PUT', 'DELETE'])
def product_detail(pid):
    if pid not in products:
        return jsonify({'error': 'Product not found'}), 404
    if request.method == 'GET':
        return jsonify(products[pid]), 200
    elif request.method == 'PUT':
        admin = get_current_admin()
        if not admin:
            return jsonify({'error': 'Admin required'}), 403
        data = request.get_json()
        product = products[pid]
        product['name'] = data.get('name', product['name'])
        product['category'] = data.get('category', product['category'])
        product['price'] = float(data.get('price', product['price']))
        product['stock'] = int(data.get('stock', product['stock']))
        product['discount'] = float(data.get('discount', product['discount']))
        product['prep_time'] = int(data.get('prep_time', product['prep_time']))
        product['rating'] = float(data.get('rating', product['rating']))
        product['featured'] = int(data.get('featured', product['featured']))
        product['description'] = data.get('description', product['description'])
        product['image'] = data.get('image', product['image'])
        product['available'] = int(data.get('available', product['available']))
        product['sort_order'] = int(data.get('sort_order', product['sort_order']))
        return jsonify(product), 200
    else:
        admin = get_current_admin()
        if not admin:
            return jsonify({'error': 'Admin required'}), 403
        del products[pid]
        return jsonify({'success': True}), 200
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

# ============================
# CHECKOUT / ORDER
# ============================
@app.route('/api/checkout', methods=['POST'])
def checkout():
    user = get_current_user()

    if not user:
        return jsonify({'error': 'Please log in to checkout'}), 401

    data = request.get_json() or {}
    items = data.get('items')
    total = data.get('total')
    phone = data.get('phone')
    delivery = data.get('delivery') or data.get('address')

    if not items or total is None or not phone or not delivery:
        return jsonify({'error': 'Missing required fields'}), 400

    if not str(phone).startswith('254') or len(str(phone)) != 12:
        return jsonify({'error': 'Phone must use format 2547XXXXXXXX'}), 400

    global order_id_counter, payment_id_counter

    order_id = order_id_counter
    order_id_counter += 1

    payment_id = payment_id_counter
    payment_id_counter += 1

    order = {
        'id': order_id,
        'user_id': user['id'],
        'customer': user['name'],
        'phone': phone,
        'items': json.dumps(items),
        'total': float(total),
        'status': 'pending',
        'created_at': datetime.now().isoformat(),
        'note': data.get('note', ''),
        'delivery_address': delivery,
        'payment_id': payment_id
    }

    orders[order_id] = order

    try:
        mpesa_response = send_stk_push(
            phone,
            total,
            f'ORDER-{order_id}'
        )
    except requests.RequestException as error:
        orders.pop(order_id, None)
        return jsonify({
            'error': f'M-Pesa request failed: {error}'
        }), 502

    if mpesa_response.get('ResponseCode') != '0':
        orders.pop(order_id, None)
        return jsonify({
            'error': mpesa_response.get(
                'ResponseDescription',
                'STK push was rejected'
            )
        }), 400

    checkout_id = mpesa_response.get('CheckoutRequestID')

    payments[payment_id] = {
        'id': payment_id,
        'order_id': order_id,
        'phone': phone,
        'amount': float(total),
        'status': 'pending',
        'transaction_id': '',
        'checkout_request_id': checkout_id,
        'created_at': datetime.now().isoformat()
    }

    save_notification(
        f"New order #{order_id} placed by {user['name']}",
        'order'
    )

    return jsonify({
        'success': True,
        'order_id': order_id,
        'checkoutRequestId': checkout_id,
        'payment_id': payment_id
    }), 201
def query_mpesa_status(checkout_id):
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    shortcode = os.getenv('MPESA_SHORTCODE')
    passkey = os.getenv('MPESA_PASSKEY')

    password = base64.b64encode(
        f'{shortcode}{passkey}{timestamp}'.encode()
    ).decode()

    response = requests.post(
        f"{os.getenv('MPESA_BASE_URL')}/mpesa/stkpushquery/v1/query",
        headers={
            'Authorization': f'Bearer {get_mpesa_access_token()}',
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

    response.raise_for_status()
    return response.json()
@app.route('/api/checkout/status', methods=['GET'])
def checkout_status():
    checkout_id = request.args.get('checkoutId')

    payment = next(
        (
            item for item in payments.values()
            if item.get('checkout_request_id') == checkout_id
        ),
        None
    )

    if not payment:
        return jsonify({'error': 'Checkout not found'}), 404

    if payment.get('status') == 'pending':
        try:
            result = query_mpesa_status(checkout_id)
            result_code = result.get('ResultCode')

            if str(result_code) == '0':
                payment['status'] = 'completed'

                order = orders.get(payment['order_id'])
                if order:
                    order['status'] = 'paid'

                save_notification(
                    f"Payment completed for order #{payment['order_id']}",
                    'payment'
                )

            elif str(result_code) in ('1032', '1037'):
                payment['status'] = 'failed'

        except requests.RequestException as error:
            print('M-Pesa status query failed:', error)

    return jsonify({
        'status': payment.get('status', 'pending'),
        'paymentId': payment['id']
    }), 200

@app.route('/api/mpesa/callback', methods=['POST'])
def mpesa_callback():
    callback = request.get_json(silent=True) or {}
    stk_callback = callback.get('Body', {}).get('stkCallback', {})

    checkout_id = stk_callback.get('CheckoutRequestID')
    result_code = stk_callback.get('ResultCode')

    if not checkout_id:
        return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'}), 200

    payment = next(
        (
            item for item in payments.values()
            if item.get('checkout_request_id') == checkout_id
        ),
        None
    )

    if not payment:
        return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'}), 200

    order = orders.get(payment['order_id'])

    if result_code == 0:
        metadata = stk_callback.get('CallbackMetadata', {}).get('Item', [])

        receipt = next(
            (
                item.get('Value')
                for item in metadata
                if item.get('Name') == 'MpesaReceiptNumber'
            ),
            ''
        )

        payment['status'] = 'completed'
        payment['transaction_id'] = receipt
       

        if order:
            order['status'] = 'paid'

        save_notification(
            f"Payment completed for order #{payment['order_id']}",
            'payment'
        )
    else:
        payment['status'] = 'failed'

        if order:
            order['status'] = 'cancelled'

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