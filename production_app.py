"""Production API for Fresh Ready Foods. The legacy app.py is retained as a UI reference."""
import base64, hashlib, hmac, json, logging, os, re, time, uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import requests
from flask import Flask, g, jsonify, render_template, request, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from flask_talisman import Talisman
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()
PHONE = re.compile(r"^254[17][0-9]{8}$")
def now(): return datetime.now(timezone.utc)
def fail(message, code=400): return jsonify(error=message), code
def env(name, default=None, required=False):
    value=os.getenv(name, default)
    if required and not value: raise RuntimeError(f"Missing required environment variable: {name}")
    return value

def create_app():
    app=Flask(__name__, static_folder="static", template_folder="templates")
    app.config.update(SQLALCHEMY_DATABASE_URI=env("DATABASE_URL", required=True), SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_size":int(env("DB_POOL_SIZE","20")),"max_overflow":int(env("DB_MAX_OVERFLOW","20")),"pool_pre_ping":True,"pool_recycle":1800},
        JWT_SECRET=env("JWT_SECRET",required=True), JWT_TTL_MINUTES=int(env("JWT_TTL_MINUTES","15")))
    db.init_app(app)
    Limiter(get_remote_address, app=app, default_limits=["300 per minute"], storage_uri=env("REDIS_URL","memory://"))
    if env("FORCE_HTTPS","false").lower()=="true": Talisman(app, content_security_policy={"default-src": "'self'", "script-src": "'self' 'unsafe-inline' https://cdnjs.cloudflare.com", "style-src": "'self' 'unsafe-inline' https://cdnjs.cloudflare.com", "font-src": "'self' data: https://cdnjs.cloudflare.com", "img-src": "'self' data: https:"})
    logging.basicConfig(level=env("LOG_LEVEL","INFO"))

    @app.before_request
    def before(): g.request_id=request.headers.get("X-Request-ID",str(uuid.uuid4())); g.started=time.monotonic()
    @app.after_request
    def headers(response):
        response.headers.update({"X-Request-ID":g.request_id,"X-Content-Type-Options":"nosniff","X-Frame-Options":"DENY","Referrer-Policy":"strict-origin-when-cross-origin"})
        app.logger.info("%s %s %s %.0fms",request.method,request.path,response.status_code,(time.monotonic()-g.started)*1000); return response
    @app.errorhandler(413)
    def large(_): return fail("Image must be 10 MB or smaller",413)

    def q(sql,**args): return db.session.execute(text(sql),args)
    def one(result):
        value=result.mappings().first(); return dict(value) if value else None
    def data(): return request.get_json(silent=True) or {}
    def dump(record):
        return {k:(v.isoformat() if isinstance(v,datetime) else float(v) if isinstance(v,Decimal) else str(v) if isinstance(v,uuid.UUID) else v) for k,v in record.items()}
    def token(user):
        body={"sub":str(user["id"]),"role":user["role"],"exp":int((now()+timedelta(minutes=app.config["JWT_TTL_MINUTES"])).timestamp()),"jti":str(uuid.uuid4())}
        encoded=base64.urlsafe_b64encode(json.dumps(body,separators=(",",":")).encode()).rstrip(b"=").decode()
        return encoded+"."+hmac.new(app.config["JWT_SECRET"].encode(),encoded.encode(),hashlib.sha256).hexdigest()
    def user():
        value=request.headers.get("Authorization",""); raw=value[7:] if value.startswith("Bearer ") else request.cookies.get("access_token")
        try:
            encoded,sig=raw.rsplit(".",1); expected=hmac.new(app.config["JWT_SECRET"].encode(),encoded.encode(),hashlib.sha256).hexdigest()
            body=json.loads(base64.urlsafe_b64decode(encoded+"="*(-len(encoded)%4)))
            if not hmac.compare_digest(sig,expected) or body["exp"]<int(now().timestamp()): raise ValueError
            result=one(q("SELECT id,name,email,phone,address,role,status,created_at FROM users WHERE id=:id AND status='active' AND deleted_at IS NULL",id=body["sub"]))
            if not result: raise ValueError
            return result
        except Exception: return None
    def guard(*roles):
        value=user()
        if not value:return None,fail("Authentication required",401)
        if roles and value["role"] not in roles:return None,fail("Insufficient permissions",403)
        return value,None
    def auth_response(value,status=200):
        access=token(value); response=jsonify(success=True,user=dump(value),access_token=access); response.status_code=status
        response.set_cookie("access_token",access,httponly=True,secure=env("COOKIE_SECURE","true")=="true",samesite="Lax",max_age=900); return response

    @app.get("/health")
    def health(): q("SELECT 1"); return jsonify(status="ok",service="food-ordering-api",request_id=g.request_id)
    @app.post("/api/signup")
    @app.post("/api/auth/register")
    def register():
        value=data(); name=str(value.get("name","")).strip(); email=str(value.get("email","")).lower().strip(); password=value.get("password","")
        if len(name)<2 or "@" not in email or len(password)<10:return fail("Use a name, valid email, and a password of at least 10 characters")
        try:
            created=one(q("INSERT INTO users (name,email,password_hash,role) VALUES (:n,:e,:p,'customer') RETURNING id,name,email,phone,role,status",n=name,e=email,p=generate_password_hash(password))); db.session.commit()
        except Exception: db.session.rollback(); return fail("Email already registered",409)
        return auth_response(created,201)
    @app.post("/api/user/login")
    @app.post("/api/auth/login")
    def login():
        value=data(); record=one(q("SELECT id,name,email,phone,password_hash,role,status FROM users WHERE email=:email AND deleted_at IS NULL",email=str(value.get("email","")).lower().strip()))
        if not record or record["status"]!="active" or not check_password_hash(record["password_hash"],value.get("password","")):return fail("Invalid credentials",401)
        record.pop("password_hash"); return auth_response(record)
    @app.post("/api/user/logout")
    def logout():
        response=jsonify(success=True); response.delete_cookie("access_token"); return response
    @app.route("/api/user/status", methods=["GET"])
    @app.route("/api/user/profile", methods=["GET", "PUT"])
    def profile():
        value,error=guard()
        if error:return error
        if request.method == "PUT":
            incoming=data(); name=str(incoming.get("name", value["name"])).strip(); phone=str(incoming.get("phone", value.get("phone") or "")).replace("+", "").replace(" ", ""); address=str(incoming.get("address", value.get("address") or "")).strip()
            if len(name)<2 or (phone and not PHONE.fullmatch(phone)): return fail("Provide a name and a valid Kenyan phone number")
            q("UPDATE users SET name=:name,phone=:phone,address=:address WHERE id=:id",name=name,phone=phone or None,address=address[:500] or None,id=value["id"]); db.session.commit()
            return jsonify(success=True)
        return jsonify(dump(value))

    @app.get("/api/products")
    def products():
        page=max(1,int(request.args.get("page",1))); size=min(50,max(1,int(request.args.get("page_size",20)))); search=request.args.get("q","").strip(); category=request.args.get("category","").strip()
        rows=q("""SELECT m.id,m.name,m.description,m.price,m.stock,m.image_url AS image,m.is_available AS available,c.name AS category,r.name AS restaurant
        FROM meals m JOIN categories c ON c.id=m.category_id JOIN restaurants r ON r.id=m.restaurant_id
        WHERE m.deleted_at IS NULL AND m.is_available AND r.status='active' AND (:search='' OR m.search_vector @@ plainto_tsquery('simple',:search)) AND (:category='' OR c.name=:category)
        ORDER BY m.created_at DESC LIMIT :size OFFSET :offset""",search=search,category=category,size=size,offset=(page-1)*size).mappings().all()
        return jsonify([dump(dict(x)) for x in rows])
    @app.post("/api/checkout")
    def checkout():
        customer,error=guard()
        if error:return error
        value=data(); phone=str(value.get("phone",customer.get("phone") or "")).replace("+","").replace(" ",""); items=value.get("items",[])
        if not PHONE.fullmatch(phone) or not isinstance(items,list) or not items:return fail("A Kenyan M-Pesa phone and at least one item are required")
        try:
            # Authentication has already performed a read in this request, so use a
            # savepoint that is valid whether SQLAlchemy has opened a transaction.
            with db.session.begin_nested():
                order_id=str(uuid.uuid4()); total=Decimal("0"); restaurant=None; lines=[]
                for item in items:
                    meal=one(q("SELECT id,restaurant_id,name,price,stock FROM meals WHERE id=:id AND deleted_at IS NULL AND is_available FOR UPDATE",id=item.get("id"))); qty=int(item.get("qty",0))
                    if not meal or qty<1 or meal["stock"]<qty:raise ValueError("One or more meals are unavailable")
                    if restaurant and restaurant!=meal["restaurant_id"]:raise ValueError("Place separate orders for each restaurant")
                    restaurant=meal["restaurant_id"]; amount=Decimal(meal["price"])*qty; total+=amount; lines.append((meal,qty,amount)); q("UPDATE meals SET stock=stock-:qty WHERE id=:id",qty=qty,id=meal["id"])
                q("INSERT INTO orders (id,customer_id,restaurant_id,status,subtotal,total,delivery_address) VALUES (:id,:customer,:restaurant,'payment_pending',:total,:total,:address)",id=order_id,customer=customer["id"],restaurant=restaurant,total=total,address=str(value.get("address", ""))[:500])
                for meal,qty,amount in lines:q("INSERT INTO order_items (id,order_id,meal_id,meal_name,unit_price,quantity,line_total) VALUES (:id,:order,:meal,:name,:price,:qty,:total)",id=str(uuid.uuid4()),order=order_id,meal=meal["id"],name=meal["name"],price=meal["price"],qty=qty,total=amount)
                payment=str(uuid.uuid4()); q("INSERT INTO payments (id,order_id,phone,amount,status,idempotency_key) VALUES (:id,:order,:phone,:amount,'initiated',:key)",id=payment,order=order_id,phone=phone,amount=total,key=request.headers.get("Idempotency-Key",str(uuid.uuid4())))
            mpesa=stk_push(app,payment,phone,total,order_id); return jsonify(success=True,order_id=order_id,payment_id=payment,checkoutId=mpesa["CheckoutRequestID"],status="pending"),202
        except ValueError as exc: db.session.rollback(); return fail(str(exc))
        except Exception: db.session.rollback(); app.logger.exception("Checkout failed"); return fail("Unable to start payment",502)
    @app.post("/api/mpesa/callback")
    def callback():
        body=data().get("Body",{}).get("stkCallback",{}); checkout=body.get("CheckoutRequestID")
        if not checkout:return fail("Invalid callback")
        payment=one(q("SELECT id,order_id,status FROM payments WHERE checkout_request_id=:id FOR UPDATE",id=checkout))
        if not payment:return jsonify(ResultCode=0,ResultDesc="Accepted")
        q("INSERT INTO payment_events (id,payment_id,payload) VALUES (:id,:payment,CAST(:payload AS jsonb))",id=str(uuid.uuid4()),payment=payment["id"],payload=json.dumps(data()))
        meta={x.get("Name"):x.get("Value") for x in body.get("CallbackMetadata",{}).get("Item",[])}
        if payment["status"]!="paid" and body.get("ResultCode")==0 and meta.get("MpesaReceiptNumber"):
            q("UPDATE payments SET status='paid',receipt_number=:receipt,paid_at=now(),provider_payload=CAST(:payload AS jsonb) WHERE id=:id",receipt=str(meta["MpesaReceiptNumber"]),payload=json.dumps(data()),id=payment["id"]); q("UPDATE orders SET status='paid',paid_at=now() WHERE id=:id",id=payment["order_id"])
        elif payment["status"]!="paid":q("UPDATE payments SET status='failed',provider_payload=CAST(:payload AS jsonb) WHERE id=:id",payload=json.dumps(data()),id=payment["id"])
        db.session.commit(); return jsonify(ResultCode=0,ResultDesc="Accepted")
    @app.get("/api/checkout/status")
    def payment_status():
        customer,error=guard()
        if error:return error
        record=one(q("SELECT p.status,o.id AS order_id FROM payments p JOIN orders o ON o.id=p.order_id WHERE p.checkout_request_id=:id AND o.customer_id=:customer",id=request.args.get("checkoutId"),customer=customer["id"])); return jsonify(dump(record) if record else {"status":"not_found"})
    @app.get("/api/orders")
    def orders():
        customer,error=guard()
        if error:return error
        rows=q("SELECT id,status,total,created_at FROM orders WHERE customer_id=:id ORDER BY created_at DESC LIMIT 50",id=customer["id"]).mappings().all(); return jsonify([dump(dict(x)) for x in rows])
    @app.put("/api/orders/<order_id>/status")
    def order_status(order_id):
        actor,error=guard("restaurant","admin")
        if error:return error
        status=data().get("status");
        if status not in {"accepted","rejected","preparing","ready","delivered"}:return fail("Invalid order status")
        clause="id=:id" if actor["role"]=="admin" else "id=:id AND restaurant_id IN (SELECT id FROM restaurants WHERE owner_id=:owner)"
        updated=q(f"UPDATE orders SET status=:status,updated_at=now() WHERE {clause}",id=order_id,status=status,owner=actor["id"]); db.session.commit(); return jsonify(success=True) if updated.rowcount else fail("Order not found",404)
    @app.get("/")
    def home():return render_template("index.html")
    @app.get("/admin")
    def admin():return render_template("admin.html")
    @app.get("/manifest.json")
    def manifest():return send_from_directory("static","manifest.json",mimetype="application/manifest+json")
    @app.get("/sw.js")
    def sw():return send_from_directory("static","sw.js",mimetype="application/javascript")
    return app

def stk_push(app,payment_id,phone,amount,order_id):
    key,secret,shortcode,passkey=env("MPESA_CONSUMER_KEY"),env("MPESA_CONSUMER_SECRET"),env("MPESA_SHORTCODE"),env("MPESA_PASSKEY")
    if not all((key,secret,shortcode,passkey)):raise RuntimeError("M-Pesa is not configured")
    base=env("MPESA_BASE_URL","https://sandbox.safaricom.co.ke"); access=requests.get(base+"/oauth/v1/generate?grant_type=client_credentials",auth=(key,secret),timeout=10).json()["access_token"]
    timestamp=datetime.now().strftime("%Y%m%d%H%M%S"); password=base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode()).decode()
    result=requests.post(base+"/mpesa/stkpush/v1/processrequest",headers={"Authorization":"Bearer "+access},json={"BusinessShortCode":shortcode,"Password":password,"Timestamp":timestamp,"TransactionType":"CustomerPayBillOnline","Amount":int(amount),"PartyA":phone,"PartyB":shortcode,"PhoneNumber":phone,"CallBackURL":env("MPESA_CALLBACK_URL",required=True),"AccountReference":order_id,"TransactionDesc":"Food order"},timeout=15).json()
    if result.get("ResponseCode")!="0":raise ValueError(result.get("errorMessage","M-Pesa rejected request"))
    db.session.execute(text("UPDATE payments SET status='pending',checkout_request_id=:checkout,provider_payload=CAST(:payload AS jsonb) WHERE id=:id"),{"checkout":result["CheckoutRequestID"],"payload":json.dumps(result),"id":payment_id}); db.session.commit(); return result

app=create_app()
