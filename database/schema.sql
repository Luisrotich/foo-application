CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE users (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name varchar(120) NOT NULL, email varchar(320) NOT NULL UNIQUE,
 phone varchar(16), address varchar(500), password_hash text NOT NULL, role varchar(20) NOT NULL DEFAULT 'customer' CHECK(role IN ('customer','restaurant','admin')),
 status varchar(20) NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended')), created_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz
);
CREATE TABLE restaurants (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id), name varchar(160) NOT NULL, status varchar(20) NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended')), created_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz);
CREATE TABLE categories (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), restaurant_id uuid NOT NULL REFERENCES restaurants(id), name varchar(80) NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(restaurant_id,name));
CREATE TABLE meals (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), restaurant_id uuid NOT NULL REFERENCES restaurants(id), category_id uuid NOT NULL REFERENCES categories(id), name varchar(180) NOT NULL, description text NOT NULL DEFAULT '', price numeric(12,2) NOT NULL CHECK(price>=0), stock integer NOT NULL DEFAULT 0 CHECK(stock>=0), image_url text, is_available boolean NOT NULL DEFAULT true, search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple',coalesce(name,'') || ' ' || coalesce(description,''))) STORED, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz
);
CREATE TABLE orders (id uuid PRIMARY KEY, customer_id uuid NOT NULL REFERENCES users(id), restaurant_id uuid NOT NULL REFERENCES restaurants(id), status varchar(30) NOT NULL, subtotal numeric(12,2) NOT NULL, total numeric(12,2) NOT NULL, delivery_address varchar(500), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), paid_at timestamptz);
CREATE TABLE order_items (id uuid PRIMARY KEY, order_id uuid NOT NULL REFERENCES orders(id), meal_id uuid REFERENCES meals(id), meal_name varchar(180) NOT NULL, unit_price numeric(12,2) NOT NULL, quantity integer NOT NULL CHECK(quantity>0), line_total numeric(12,2) NOT NULL);
CREATE TABLE payments (id uuid PRIMARY KEY, order_id uuid NOT NULL UNIQUE REFERENCES orders(id), phone varchar(16) NOT NULL, amount numeric(12,2) NOT NULL, status varchar(20) NOT NULL, idempotency_key varchar(100) NOT NULL UNIQUE, checkout_request_id varchar(120) UNIQUE, receipt_number varchar(80) UNIQUE, provider_payload jsonb, created_at timestamptz NOT NULL DEFAULT now(), paid_at timestamptz);
CREATE TABLE payment_events (id uuid PRIMARY KEY, payment_id uuid NOT NULL REFERENCES payments(id), payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE audit_logs (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), actor_id uuid REFERENCES users(id), action varchar(100) NOT NULL, entity_type varchar(80) NOT NULL, entity_id uuid, metadata jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX idx_meals_search ON meals USING gin(search_vector);
CREATE INDEX idx_meals_restaurant_active ON meals(restaurant_id,is_available) WHERE deleted_at IS NULL;
CREATE INDEX idx_orders_customer_created ON orders(customer_id,created_at DESC);
CREATE INDEX idx_orders_restaurant_status ON orders(restaurant_id,status,created_at DESC);
CREATE INDEX idx_payments_checkout ON payments(checkout_request_id);
CREATE INDEX idx_payment_events_payment ON payment_events(payment_id,created_at DESC);
