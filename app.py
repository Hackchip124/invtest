import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
import uuid
import barcode
from barcode.writer import ImageWriter
import os
import base64
from io import BytesIO
import hashlib
import time
import matplotlib.pyplot as plt
from fpdf import FPDF
import tempfile

# ==============================================
# DATABASE SETUP & CONFIGURATION
# ==============================================

def initialize_database():
    """Initialize the database with all required tables and migrate schema if needed"""
    conn = sqlite3.connect('inventory.db')
    cursor = conn.cursor()
    
    # Users Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin', 'manager', 'sales')),
        full_name TEXT,
        email TEXT,
        phone TEXT,
        is_active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Suppliers Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS suppliers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        contact_person TEXT,
        email TEXT,
        phone TEXT,
        address TEXT,
        tax_number TEXT,
        payment_terms INTEGER DEFAULT 30,
        is_active BOOLEAN DEFAULT 1,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Customers Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS customers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        tax_number TEXT,
        contact TEXT,
        email TEXT,
        phone TEXT,
        address TEXT NOT NULL,
        payment_terms INTEGER DEFAULT 30,
        credit_limit REAL DEFAULT 0,
        is_active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Products Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS products (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        category TEXT,
        subcategory TEXT,
        barcode TEXT UNIQUE,
        sku TEXT UNIQUE,
        current_stock REAL NOT NULL DEFAULT 0,
        min_stock REAL DEFAULT 5,
        max_stock REAL,
        unit TEXT DEFAULT 'pcs',
        cost_price REAL DEFAULT 0,
        selling_price REAL NOT NULL,
        vat_rate REAL DEFAULT 5.0,
        supplier_id TEXT,
        is_active BOOLEAN DEFAULT 1,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
    )''')
    
    # Inventory Transactions Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventory_transactions (
        id TEXT PRIMARY KEY,
        product_id TEXT NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('purchase', 'sale', 'adjustment', 'return')),
        quantity REAL NOT NULL,
        unit_price REAL NOT NULL,
        total_value REAL NOT NULL,
        reference_id TEXT,
        notes TEXT,
        user_id TEXT NOT NULL,
        supplier_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(product_id) REFERENCES products(id),
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
    )''')
    
    # Sales Orders Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS sales_orders (
        id TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL,
        order_date TIMESTAMP NOT NULL,
        required_date TIMESTAMP,
        status TEXT NOT NULL CHECK(status IN ('draft', 'pending_approval', 'approved', 'processing', 'completed', 'cancelled')),
        subtotal REAL NOT NULL,
        discount REAL DEFAULT 0,
        vat_amount REAL NOT NULL,
        total_amount REAL NOT NULL,
        payment_status TEXT CHECK(payment_status IN ('pending', 'partial', 'paid')),
        payment_method TEXT,
        notes TEXT,
        user_id TEXT NOT NULL,
        approved_by TEXT,
        approved_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(customer_id) REFERENCES customers(id),
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(approved_by) REFERENCES users(id)
    )''')
    
    # Order Items Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS order_items (
        id TEXT PRIMARY KEY,
        order_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        quantity REAL NOT NULL,
        unit_price REAL NOT NULL,
        discount REAL DEFAULT 0,
        vat_rate REAL DEFAULT 5.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(order_id) REFERENCES sales_orders(id),
        FOREIGN KEY(product_id) REFERENCES products(id)
    )''')
    
    # Payments Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS payments (
        id TEXT PRIMARY KEY,
        order_id TEXT NOT NULL,
        amount REAL NOT NULL,
        payment_date TIMESTAMP NOT NULL,
        payment_method TEXT NOT NULL,
        reference TEXT,
        notes TEXT,
        user_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(order_id) REFERENCES sales_orders(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    
    # Check for missing columns and add them if needed
    cursor.execute("PRAGMA table_info(products)")
    product_columns = [column[1] for column in cursor.fetchall()]
    
    if 'category' not in product_columns:
        cursor.execute("ALTER TABLE products ADD COLUMN category TEXT")
    if 'subcategory' not in product_columns:
        cursor.execute("ALTER TABLE products ADD COLUMN subcategory TEXT")
    
    # Check for missing columns in sales_orders
    cursor.execute("PRAGMA table_info(sales_orders)")
    order_columns = [column[1] for column in cursor.fetchall()]
    
    if 'vat_rate' not in order_columns:
        cursor.execute("ALTER TABLE sales_orders ADD COLUMN vat_rate REAL DEFAULT 5.0")
    
    # Create default admin user if not exists
    cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
    if cursor.fetchone()[0] == 0:
        admin_id = generate_short_id("U-")
        password_hash = hash_password("admin123")  # Default admin password
        cursor.execute(
            """INSERT INTO users (
                id, username, password_hash, role, 
                full_name, email, phone
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                admin_id,
                "admin",
                password_hash,
                "admin",
                "System Administrator",
                "admin@example.com",
                "1234567890"
            )
        )
    
    conn.commit()
    conn.close()

# ==============================================
# UTILITY FUNCTIONS
# ==============================================

def generate_short_id(prefix=""):
    """Generate shorter readable IDs"""
    return prefix + str(uuid.uuid4().hex)[:8].upper()

def hash_password(password):
    """Securely hash passwords using PBKDF2"""
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt + key

def verify_password(stored_password, provided_password):
    """Verify a password against stored hash"""
    salt = stored_password[:16]
    stored_key = stored_password[16:]
    new_key = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt, 100000)
    return stored_key == new_key

# ==============================================
# AUTHENTICATION & USER MANAGEMENT
# ==============================================

def authenticate_user(username, password):
    """Authenticate user credentials"""
    conn = sqlite3.connect('inventory.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT id, username, password_hash, role, full_name, is_active FROM users WHERE username = ?",
            (username,)
        )
        user = cursor.fetchone()
        
        if user and user[5] and verify_password(user[2], password):
            return {
                'id': user[0],
                'username': user[1],
                'role': user[3],
                'full_name': user[4] if user[4] else user[1]
            }
        return None
    except sqlite3.OperationalError as e:
        if "no such column: full_name" in str(e):
            cursor.execute(
                "SELECT id, username, password_hash, role, is_active FROM users WHERE username = ?",
                (username,)
            )
            user = cursor.fetchone()
            
            if user and user[4] and verify_password(user[2], password):
                return {
                    'id': user[0],
                    'username': user[1],
                    'role': user[3],
                    'full_name': user[1]
                }
            return None
        raise
    finally:
        conn.close()

def update_last_login(user_id):
    """Update user's last login timestamp"""
    conn = sqlite3.connect('inventory.db')
    try:
        conn.execute(
            "UPDATE users SET updated_at = ? WHERE id = ?",
            (datetime.now(), user_id)
        )
        conn.commit()
    finally:
        conn.close()

def get_users(active_only=True):
    """Get list of all users"""
    conn = sqlite3.connect('inventory.db')
    try:
        query = "SELECT id, username, role, full_name, email, phone, is_active FROM users"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY username"
        return pd.read_sql(query, conn)
    except sqlite3.OperationalError as e:
        if "no such column: full_name" in str(e):
            query = "SELECT id, username, role, email, phone, is_active FROM users"
            if active_only:
                query += " WHERE is_active = 1"
            query += " ORDER BY username"
            users = pd.read_sql(query, conn)
            users['full_name'] = users['username']
            return users
        raise
    finally:
        conn.close()

def add_user(user_data):
    """Add a new user to the system"""
    conn = sqlite3.connect('inventory.db')
    try:
        user_id = generate_short_id("U-")
        password_hash = hash_password(user_data['password'])
        conn.execute(
            """INSERT INTO users (
                id, username, password_hash, role, 
                full_name, email, phone
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                user_data['username'],
                password_hash,
                user_data['role'],
                user_data.get('full_name', user_data['username']),
                user_data.get('email'),
                user_data.get('phone')
            )
        )
        conn.commit()
        return user_id
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            raise ValueError("Username already exists")
        raise
    finally:
        conn.close()

def update_user(user_id, user_data):
    """Update user information"""
    conn = sqlite3.connect('inventory.db')
    try:
        conn.execute(
            """UPDATE users SET 
                username = ?,
                role = ?,
                full_name = ?,
                email = ?,
                phone = ?,
                updated_at = ?
            WHERE id = ?""",
            (
                user_data['username'],
                user_data['role'],
                user_data.get('full_name'),
                user_data.get('email'),
                user_data.get('phone'),
                datetime.now(),
                user_id
            )
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            raise ValueError("Username already exists")
        raise
    finally:
        conn.close()

def set_user_status(user_id, active):
    """Activate or deactivate a user"""
    conn = sqlite3.connect('inventory.db')
    try:
        conn.execute(
            "UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?",
            (int(active), datetime.now(), user_id)
        )
        conn.commit()
    finally:
        conn.close()

def change_user_password(user_id, new_password):
    """Change a user's password"""
    conn = sqlite3.connect('inventory.db')
    try:
        password_hash = hash_password(new_password)
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (password_hash, datetime.now(), user_id)
        )
        conn.commit()
    finally:
        conn.close()

# ==============================================
# SUPPLIER MANAGEMENT
# ==============================================

def get_suppliers(active_only=True):
    """Get list of all suppliers"""
    conn = sqlite3.connect('inventory.db')
    try:
        query = "SELECT * FROM suppliers"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY name"
        return pd.read_sql(query, conn)
    finally:
        conn.close()

def add_supplier(supplier_data):
    """Add a new supplier"""
    conn = sqlite3.connect('inventory.db')
    try:
        supplier_id = generate_short_id("S-")
        conn.execute(
            """INSERT INTO suppliers (
                id, name, contact_person, email, phone,
                address, tax_number, payment_terms, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                supplier_id,
                supplier_data['name'],
                supplier_data.get('contact_person'),
                supplier_data.get('email'),
                supplier_data.get('phone'),
                supplier_data.get('address'),
                supplier_data.get('tax_number'),
                supplier_data.get('payment_terms', 30),
                supplier_data.get('notes')
            )
        )
        conn.commit()
        return supplier_id
    except sqlite3.IntegrityError as e:
        raise ValueError("Could not add supplier: " + str(e))
    finally:
        conn.close()

def get_supplier_by_id(supplier_id):
    """Get supplier details by ID"""
    conn = sqlite3.connect('inventory.db')
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM suppliers WHERE id = ?",
            (supplier_id,)
        )
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        return dict(zip(columns, row)) if row else None
    finally:
        conn.close()

def update_supplier(supplier_id, supplier_data):
    """Update supplier information"""
    conn = sqlite3.connect('inventory.db')
    try:
        conn.execute(
            """UPDATE suppliers SET 
                name = ?,
                contact_person = ?,
                email = ?,
                phone = ?,
                address = ?,
                tax_number = ?,
                payment_terms = ?,
                notes = ?,
                updated_at = ?
            WHERE id = ?""",
            (
                supplier_data['name'],
                supplier_data.get('contact_person'),
                supplier_data.get('email'),
                supplier_data.get('phone'),
                supplier_data.get('address'),
                supplier_data.get('tax_number'),
                supplier_data.get('payment_terms'),
                supplier_data.get('notes'),
                datetime.now(),
                supplier_id
            )
        )
        conn.commit()
    except Exception as e:
        raise ValueError("Could not update supplier: " + str(e))
    finally:
        conn.close()

def set_supplier_status(supplier_id, active):
    """Activate or deactivate a supplier"""
    conn = sqlite3.connect('inventory.db')
    try:
        conn.execute(
            "UPDATE suppliers SET is_active = ?, updated_at = ? WHERE id = ?",
            (int(active), datetime.now(), supplier_id)
        )
        conn.commit()
    finally:
        conn.close()

# ==============================================
# PRODUCT MANAGEMENT
# ==============================================

def get_products(active_only=True):
    """Get list of all products"""
    conn = sqlite3.connect('inventory.db')
    try:
        query = """
        SELECT p.*, s.name as supplier_name 
        FROM products p
        LEFT JOIN suppliers s ON p.supplier_id = s.id
        """
        if active_only:
            query += " WHERE p.is_active = 1"
        query += " ORDER BY p.name"
        return pd.read_sql(query, conn)
    finally:
        conn.close()

def add_product(product_data):
    """Add a new product with automatic barcode generation"""
    conn = sqlite3.connect('inventory.db')
    try:
        product_id = generate_short_id("P-")
        
        # Generate barcode if not provided
        barcode_value = product_data.get('barcode', str(uuid.uuid4().int)[:12])
        
        conn.execute(
            """INSERT INTO products (
                id, name, description, category, subcategory, barcode, sku,
                current_stock, min_stock, max_stock, unit,
                cost_price, selling_price, vat_rate, supplier_id, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                product_id,
                product_data['name'],
                product_data.get('description'),
                product_data.get('category'),
                product_data.get('subcategory'),
                barcode_value,
                product_data.get('sku', f"SKU-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4().int)[:4]}"),
                product_data.get('current_stock', 0),
                product_data.get('min_stock', 5),
                product_data.get('max_stock'),
                product_data.get('unit', 'pcs'),
                product_data.get('cost_price', 0),
                product_data['selling_price'],
                product_data.get('vat_rate', 5.0),
                product_data.get('supplier_id'),
                product_data.get('notes')
            )
        )
        conn.commit()
        return product_id
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            raise ValueError("Product with this barcode or SKU already exists")
        raise
    finally:
        conn.close()

def update_product(product_id, product_data):
    """Update existing product information"""
    conn = sqlite3.connect('inventory.db')
    try:
        conn.execute(
            """UPDATE products SET 
                name = ?,
                description = ?,
                category = ?,
                subcategory = ?,
                barcode = ?,
                sku = ?,
                min_stock = ?,
                max_stock = ?,
                unit = ?,
                cost_price = ?,
                selling_price = ?,
                vat_rate = ?,
                supplier_id = ?,
                notes = ?,
                updated_at = ?
            WHERE id = ?""",
            (
                product_data['name'],
                product_data.get('description'),
                product_data.get('category'),
                product_data.get('subcategory'),
                product_data.get('barcode'),
                product_data.get('sku'),
                product_data.get('min_stock'),
                product_data.get('max_stock'),
                product_data.get('unit'),
                product_data.get('cost_price'),
                product_data['selling_price'],
                product_data.get('vat_rate'),
                product_data.get('supplier_id'),
                product_data.get('notes'),
                datetime.now(),
                product_id
            )
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            raise ValueError("Product with this barcode or SKU already exists")
        raise
    finally:
        conn.close()

def delete_product(product_id):
    """Mark product as inactive (soft delete)"""
    conn = sqlite3.connect('inventory.db')
    try:
        conn.execute(
            "UPDATE products SET is_active = 0, updated_at = ? WHERE id = ?",
            (datetime.now(), product_id)
        )
        conn.commit()
    finally:
        conn.close()

def update_product_stock(product_id, quantity, transaction_type, user_id, supplier_id=None, reference_id=None, notes=None):
    """Update product stock level"""
    conn = sqlite3.connect('inventory.db')
    try:
        conn.execute("BEGIN TRANSACTION")
        
        # Record transaction
        transaction_id = generate_short_id("TXN-")
        product = get_product_by_id(product_id)
        if not product:
            raise ValueError("Product not found")
        
        unit_price = product['cost_price'] if transaction_type == 'purchase' else product['selling_price']
        
        conn.execute(
            """INSERT INTO inventory_transactions (
                id, product_id, type, quantity,
                unit_price, total_value, reference_id, notes, user_id, supplier_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                transaction_id,
                product_id,
                transaction_type,
                quantity,
                unit_price,
                quantity * unit_price,
                reference_id,
                notes,
                user_id,
                supplier_id
            )
        )
        
        # Update stock
        if transaction_type == 'purchase':
            conn.execute(
                """UPDATE products SET 
                    current_stock = current_stock + ?,
                    cost_price = ((cost_price * current_stock) + (? * ?)) / (current_stock + ?),
                    updated_at = ?
                WHERE id = ?""",
                (quantity, unit_price, quantity, quantity, datetime.now(), product_id)
            )
        elif transaction_type in ['sale', 'adjustment']:
            conn.execute(
                "UPDATE products SET current_stock = current_stock - ?, updated_at = ? WHERE id = ?",
                (quantity, datetime.now(), product_id)
            )
        elif transaction_type == 'return':
            conn.execute(
                "UPDATE products SET current_stock = current_stock + ?, updated_at = ? WHERE id = ?",
                (quantity, datetime.now(), product_id)
            )
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_product_by_id(product_id):
    """Get product details by ID"""
    conn = sqlite3.connect('inventory.db')
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM products WHERE id = ?",
            (product_id,)
        )
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        return dict(zip(columns, row)) if row else None
    finally:
        conn.close()

def generate_barcode(product_id, product_name):
    """Generate barcode image for a product"""
    try:
        code = barcode.get_barcode_class('code128')
        barcode_image = code(product_id, writer=ImageWriter())
        
        # Save to temp file
        temp_dir = tempfile.mkdtemp()
        file_path = os.path.join(temp_dir, f"{product_name}_{product_id}")
        filename = barcode_image.save(file_path)
        
        return filename
    except Exception as e:
        raise ValueError(f"Failed to generate barcode: {str(e)}")

def get_product_categories():
    """Get unique product categories"""
    conn = sqlite3.connect('inventory.db')
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL ORDER BY category")
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()

def get_product_subcategories(category=None):
    """Get unique product subcategories"""
    conn = sqlite3.connect('inventory.db')
    try:
        cursor = conn.cursor()
        if category:
            cursor.execute("""
                SELECT DISTINCT subcategory 
                FROM products 
                WHERE subcategory IS NOT NULL AND category = ?
                ORDER BY subcategory
            """, (category,))
        else:
            cursor.execute("""
                SELECT DISTINCT subcategory 
                FROM products 
                WHERE subcategory IS NOT NULL 
                ORDER BY subcategory
            """)
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()

# ==============================================
# CUSTOMER MANAGEMENT
# ==============================================

def get_customers(active_only=True):
    """Get list of all customers"""
    conn = sqlite3.connect('inventory.db')
    try:
        query = "SELECT * FROM customers"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY name"
        return pd.read_sql(query, conn)
    finally:
        conn.close()

def add_customer(customer_data):
    """Add a new customer"""
    conn = sqlite3.connect('inventory.db')
    try:
        customer_id = generate_short_id("C-")
        conn.execute(
            """INSERT INTO customers (
                id, name, tax_number, contact,
                email, phone, address, payment_terms, credit_limit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                customer_id,
                customer_data['name'],
                customer_data.get('tax_number'),
                customer_data.get('contact'),
                customer_data.get('email'),
                customer_data.get('phone'),
                customer_data['address'],
                customer_data.get('payment_terms', 30),
                customer_data.get('credit_limit', 0)
            )
        )
        conn.commit()
        return customer_id
    except sqlite3.IntegrityError as e:
        raise ValueError("Could not add customer: " + str(e))
    finally:
        conn.close()

def get_customer_by_id(customer_id):
    """Get customer details by ID"""
    conn = sqlite3.connect('inventory.db')
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM customers WHERE id = ?",
            (customer_id,)
        )
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        return dict(zip(columns, row)) if row else None
    finally:
        conn.close()

def update_customer(customer_id, customer_data):
    """Update customer information"""
    conn = sqlite3.connect('inventory.db')
    try:
        conn.execute(
            """UPDATE customers SET 
                name = ?,
                tax_number = ?,
                contact = ?,
                email = ?,
                phone = ?,
                address = ?,
                payment_terms = ?,
                credit_limit = ?,
                updated_at = ?
            WHERE id = ?""",
            (
                customer_data['name'],
                customer_data.get('tax_number'),
                customer_data.get('contact'),
                customer_data.get('email'),
                customer_data.get('phone'),
                customer_data['address'],
                customer_data.get('payment_terms'),
                customer_data.get('credit_limit'),
                datetime.now(),
                customer_id
            )
        )
        conn.commit()
    except Exception as e:
        raise ValueError("Could not update customer: " + str(e))
    finally:
        conn.close()

def set_customer_status(customer_id, active):
    """Activate or deactivate a customer"""
    conn = sqlite3.connect('inventory.db')
    try:
        conn.execute(
            "UPDATE customers SET is_active = ?, updated_at = ? WHERE id = ?",
            (int(active), datetime.now(), customer_id)
        )
        conn.commit()
    finally:
        conn.close()

# ==============================================
# SALES ORDER MANAGEMENT
# ==============================================

def create_sales_order(order_data):
    """Create a new sales order with proper financial calculations"""
    conn = sqlite3.connect('inventory.db')
    try:
        conn.execute("BEGIN TRANSACTION")
        
        # Calculate order totals first
        subtotal = 0
        vat_amount = 0
        
        for item in order_data['items']:
            line_total = item['quantity'] * item['unit_price'] * (1 - item.get('discount', 0)/100)
            item_vat = line_total * (item.get('vat_rate', 5.0)/100)
            subtotal += line_total
            vat_amount += item_vat
        
        total_amount = subtotal + vat_amount - order_data.get('discount', 0)
        
        # Create order header with all calculated values
        order_id = generate_short_id("ORD-")
        conn.execute(
            """INSERT INTO sales_orders (
                id, customer_id, order_date, required_date, status,
                subtotal, discount, vat_amount, total_amount,
                payment_status, notes, user_id, vat_rate
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order_id,
                order_data['customer_id'],
                order_data.get('order_date', datetime.now()),
                order_data.get('required_date'),
                order_data.get('status', 'draft'),
                subtotal,
                order_data.get('discount', 0),
                vat_amount,
                total_amount,
                'pending',
                order_data.get('notes'),
                order_data['user_id'],
                order_data.get('vat_rate', 5.0)
            )
        )
        
        # Process order items
        for item in order_data['items']:
            item_id = generate_short_id("ITM-")
            conn.execute(
                """INSERT INTO order_items (
                    id, order_id, product_id, quantity,
                    unit_price, discount, vat_rate
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_id,
                    order_id,
                    item['product_id'],
                    item['quantity'],
                    item['unit_price'],
                    item.get('discount', 0),
                    item.get('vat_rate', 5.0)
                )
            )
        
        conn.commit()
        return order_id
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_sales_orders(status=None, user_id=None, customer_id=None, days=None):
    """Get list of sales orders with filtering options"""
    conn = sqlite3.connect('inventory.db')
    try:
        query = """
        SELECT 
            so.id, so.order_date, so.required_date, so.status,
            c.name as customer, c.tax_number,
            u.username as sales_person,
            so.subtotal, so.discount, so.vat_amount, so.total_amount,
            so.payment_status, so.payment_method, so.notes,
            so.created_at, so.updated_at
        FROM sales_orders so
        JOIN customers c ON so.customer_id = c.id
        JOIN users u ON so.user_id = u.id
        """
        conditions = []
        if status:
            conditions.append(f"so.status = '{status}'")
        if user_id:
            conditions.append(f"so.user_id = '{user_id}'")
        if customer_id:
            conditions.append(f"so.customer_id = '{customer_id}'")
        if days:
            conditions.append(f"so.order_date >= date('now', '-{days} days')")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY so.order_date DESC"
        return pd.read_sql(query, conn)
    finally:
        conn.close()

def get_sales_order_by_id(order_id):
    """Get sales order details by ID"""
    conn = sqlite3.connect('inventory.db')
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT 
                so.*, 
                c.name as customer_name, 
                c.tax_number as customer_tax_number,
                c.address as customer_address,
                c.contact as customer_contact,
                c.phone as customer_phone,
                u.full_name as sales_person_name
            FROM sales_orders so
            JOIN customers c ON so.customer_id = c.id
            JOIN users u ON so.user_id = u.id
            WHERE so.id = ?""",
            (order_id,)
        )
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        return dict(zip(columns, row)) if row else None
    finally:
        conn.close()

def get_order_items(order_id):
    """Get items for a specific order"""
    conn = sqlite3.connect('inventory.db')
    try:
        query = """
        SELECT 
            oi.*,
            p.name as product_name,
            p.description as product_description,
            p.sku as product_sku,
            p.unit as product_unit,
            oi.quantity * oi.unit_price * (1 - oi.discount/100) as line_total,
            (oi.quantity * oi.unit_price * (1 - oi.discount/100)) * (oi.vat_rate/100) as line_vat
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = ?
        """
        return pd.read_sql(query, conn, params=(order_id,))
    finally:
        conn.close()

def update_order_status(order_id, status, user_id=None):
    """Update order status"""
    conn = sqlite3.connect('inventory.db')
    try:
        if status == 'approved':
            conn.execute(
                """UPDATE sales_orders SET 
                    status = ?,
                    approved_by = ?,
                    approved_at = ?,
                    updated_at = ?
                WHERE id = ?""",
                (status, user_id, datetime.now(), datetime.now(), order_id)
            )
        else:
            conn.execute(
                """UPDATE sales_orders SET 
                    status = ?,
                    updated_at = ?
                WHERE id = ?""",
                (status, datetime.now(), order_id)
            )
        conn.commit()
    finally:
        conn.close()

def process_order_payment(order_id, amount, payment_method, reference, notes, user_id):
    """Process payment for an order with proper status updates"""
    conn = sqlite3.connect('inventory.db')
    try:
        conn.execute("BEGIN TRANSACTION")
        
        # Get current order details
        cursor = conn.cursor()
        cursor.execute(
            "SELECT total_amount, payment_status FROM sales_orders WHERE id = ?", 
            (order_id,)
        )
        order = cursor.fetchone()
        
        if not order:
            raise ValueError("Order not found")
        
        total_amount = order[0]
        current_status = order[1]
        
        # Calculate existing payments
        cursor.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE order_id = ?", 
            (order_id,)
        )
        total_paid = cursor.fetchone()[0]
        
        # Validate new payment
        new_total_paid = total_paid + amount
        balance = total_amount - new_total_paid
        
        if amount <= 0:
            raise ValueError("Payment amount must be positive")
        if amount > total_amount - total_paid:
            raise ValueError(f"Payment exceeds remaining balance of ${total_amount - total_paid:,.2f}")
        
        # Record the payment
        payment_id = generate_short_id("PAY-")
        cursor.execute(
            """INSERT INTO payments (
                id, order_id, amount, payment_date,
                payment_method, reference, notes, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payment_id,
                order_id,
                amount,
                datetime.now(),
                payment_method,
                reference,
                notes,
                user_id
            )
        )
        
        # Determine new payment status
        if abs(balance) < 0.01:  # Account for floating point rounding
            new_payment_status = 'paid'
        elif new_total_paid > 0:
            new_payment_status = 'partial'
        else:
            new_payment_status = 'pending'
        
        # Update order payment status
        cursor.execute(
            """UPDATE sales_orders SET 
                payment_status = ?,
                payment_method = ?,
                updated_at = ?
            WHERE id = ?""",
            (new_payment_status, payment_method, datetime.now(), order_id)
        )
        
        conn.commit()
        return payment_id
        
    except Exception as e:
        conn.rollback()
        raise ValueError(f"Payment processing failed: {str(e)}")
    finally:
        conn.close()

def get_payments(order_id):
    """Get payments for an order"""
    conn = sqlite3.connect('inventory.db')
    try:
        query = """
        SELECT 
            p.*,
            u.username as processed_by
        FROM payments p
        JOIN users u ON p.user_id = u.id
        WHERE p.order_id = ?
        ORDER BY p.payment_date
        """
        return pd.read_sql(query, conn, params=(order_id,))
    finally:
        conn.close()

def get_total_payments(order_id):
    """Get total payments received for an order"""
    conn = sqlite3.connect('inventory.db')
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE order_id = ?",
            (order_id,)
        )
        return cursor.fetchone()[0]
    finally:
        conn.close()

def fulfill_order(order_id, user_id):
    """Fulfill an approved order (deduct from inventory)"""
    conn = sqlite3.connect('inventory.db')
    try:
        conn.execute("BEGIN TRANSACTION")
        
        # Get order items
        items = get_order_items(order_id)
        if items.empty:
            raise ValueError("No items found for this order")
        
        # Process each item
        for _, item in items.iterrows():
            update_product_stock(
                item['product_id'],
                item['quantity'],
                'sale',
                user_id,
                reference_id=order_id,
                notes=f"Order fulfillment for order {order_id}"
            )
        
        # Update order status
        update_order_status(order_id, 'completed')
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

def generate_invoice_pdf(order_id):
    """Generate PDF invoice for an order"""
    try:
        order = get_sales_order_by_id(order_id)
        if not order:
            raise ValueError("Order not found")
        
        items = get_order_items(order_id)
        if items.empty:
            raise ValueError("No items found for this order")
        
        payments = get_payments(order_id)
        total_paid = get_total_payments(order_id)
        balance = order['total_amount'] - total_paid
        
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        
        # Header
        pdf.cell(200, 10, txt="INVOICE", ln=1, align='C')
        pdf.ln(10)
        
        # Company Info
        pdf.cell(200, 10, txt="Your Company Name", ln=1)
        pdf.cell(200, 10, txt="123 Business Street", ln=1)
        pdf.cell(200, 10, txt="City, Country", ln=1)
        pdf.cell(200, 10, txt=f"Tax ID: 123456789", ln=1)
        pdf.ln(10)
        
        # Invoice Info
        pdf.cell(200, 10, txt=f"Invoice #: {order_id}", ln=1)
        pdf.cell(200, 10, txt=f"Date: {order['order_date'].strftime('%Y-%m-%d') if isinstance(order['order_date'], datetime) else order['order_date']}", ln=1)
        pdf.cell(200, 10, txt=f"Status: {order['status'].title()}", ln=1)
        pdf.ln(10)
        
        # Customer Info
        pdf.cell(200, 10, txt="Bill To:", ln=1)
        pdf.cell(200, 10, txt=f"{order['customer_name']}", ln=1)
        if order['customer_tax_number']:
            pdf.cell(200, 10, txt=f"Tax #: {order['customer_tax_number']}", ln=1)
        pdf.cell(200, 10, txt=f"{order['customer_address']}", ln=1)
        if order['customer_phone']:
            pdf.cell(200, 10, txt=f"Phone: {order['customer_phone']}", ln=1)
        pdf.ln(10)
        
        # Items Table
        pdf.cell(60, 10, txt="Description", border=1)
        pdf.cell(30, 10, txt="Qty", border=1)
        pdf.cell(30, 10, txt="Unit Price", border=1)
        pdf.cell(30, 10, txt="Discount %", border=1)
        pdf.cell(40, 10, txt="Amount", border=1, ln=1)
        
        for _, item in items.iterrows():
            pdf.cell(60, 10, txt=item['product_name'], border=1)
            pdf.cell(30, 10, txt=f"{item['quantity']} {item['product_unit']}", border=1)
            pdf.cell(30, 10, txt=f"{item['unit_price']:.2f}", border=1)
            pdf.cell(30, 10, txt=f"{item['discount']:.1f}%", border=1)
            pdf.cell(40, 10, txt=f"{item['line_total']:.2f}", border=1, ln=1)
        
        # Totals
        pdf.cell(150, 10, txt="Subtotal:", align='R')
        pdf.cell(40, 10, txt=f"{order['subtotal']:.2f}", ln=1)
        pdf.cell(150, 10, txt="Discount:", align='R')
        pdf.cell(40, 10, txt=f"{order['discount']:.2f}", ln=1)
        
        # Use vat_rate from order if available, otherwise default to 5%
        vat_rate = order.get('vat_rate', 5.0)
        pdf.cell(150, 10, txt=f"VAT ({vat_rate}%):", align='R')
        pdf.cell(40, 10, txt=f"{order['vat_amount']:.2f}", ln=1)
        pdf.cell(150, 10, txt="Total Amount:", align='R')
        pdf.cell(40, 10, txt=f"{order['total_amount']:.2f}", ln=1)
        
        # Payments
        if not payments.empty:
            pdf.ln(10)
            pdf.cell(200, 10, txt="Payments:", ln=1)
            pdf.cell(60, 10, txt="Date", border=1)
            pdf.cell(50, 10, txt="Method", border=1)
            pdf.cell(40, 10, txt="Amount", border=1)
            pdf.cell(40, 10, txt="Reference", border=1, ln=1)
            
            for _, payment in payments.iterrows():
                pdf.cell(60, 10, txt=payment['payment_date'].strftime('%Y-%m-%d') if isinstance(payment['payment_date'], datetime) else payment['payment_date'], border=1)
                pdf.cell(50, 10, txt=payment['payment_method'], border=1)
                pdf.cell(40, 10, txt=f"{payment['amount']:.2f}", border=1)
                pdf.cell(40, 10, txt=payment['reference'], border=1, ln=1)
            
            pdf.cell(110, 10, txt="Total Paid:", align='R')
            pdf.cell(40, 10, txt=f"{total_paid:.2f}", ln=1)
            pdf.cell(110, 10, txt="Balance Due:", align='R')
            pdf.cell(40, 10, txt=f"{balance:.2f}", ln=1)
        
        # Footer
        pdf.ln(20)
        pdf.cell(200, 10, txt="Thank you for your business!", align='C')
        
        # Save to temp file
        temp_dir = tempfile.mkdtemp()
        file_path = os.path.join(temp_dir, f"invoice_{order_id}.pdf")
        pdf.output(file_path)
        
        return file_path
    except Exception as e:
        raise ValueError(f"Failed to generate invoice: {str(e)}")

# ==============================================
# REPORTING FUNCTIONS
# ==============================================

def generate_sales_report(start_date, end_date):
    """Generate sales report for given date range"""
    conn = sqlite3.connect('inventory.db')
    try:
        query = f"""
        SELECT 
            so.id as order_id,
            so.order_date,
            c.name as customer,
            u.username as sales_person,
            so.subtotal,
            so.discount,
            so.vat_amount,
            so.total_amount,
            so.payment_status,
            so.payment_method,
            so.status
        FROM sales_orders so
        JOIN customers c ON so.customer_id = c.id
        JOIN users u ON so.user_id = u.id
        WHERE date(so.order_date) BETWEEN '{start_date}' AND '{end_date}'
        ORDER BY so.order_date
        """
        return pd.read_sql(query, conn)
    finally:
        conn.close()

def generate_vat_report(start_date, end_date):
    """Generate VAT report for given date range"""
    conn = sqlite3.connect('inventory.db')
    try:
        query = f"""
        SELECT 
            so.id as order_id,
            so.order_date,
            c.name as customer,
            c.tax_number,
            so.total_amount,
            so.vat_amount,
            so.payment_status
        FROM sales_orders so
        JOIN customers c ON so.customer_id = c.id
        WHERE date(so.order_date) BETWEEN '{start_date}' AND '{end_date}'
        ORDER BY so.order_date
        """
        return pd.read_sql(query, conn)
    finally:
        conn.close()

def generate_inventory_report():
    """Generate inventory status report"""
    conn = sqlite3.connect('inventory.db')
    try:
        query = """
        SELECT 
            p.name,
            p.category,
            p.subcategory,
            p.current_stock,
            p.min_stock,
            p.max_stock,
            p.unit,
            p.cost_price,
            p.selling_price,
            s.name as supplier
        FROM products p
        LEFT JOIN suppliers s ON p.supplier_id = s.id
        WHERE p.is_active = 1
        ORDER BY p.category, p.subcategory, p.name
        """
        return pd.read_sql(query, conn)
    finally:
        conn.close()

# ==============================================
# PAGE FUNCTIONS
# ==============================================

def dashboard_page():
    """Render the main dashboard"""
    st.title("Dashboard Overview")
    
    try:
        # Key metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Products", len(get_products()))
        with col2:
            st.metric("Active Customers", len(get_customers()))
        with col3:
            st.metric("Pending Approval", len(get_sales_orders(status='pending_approval')))
        with col4:
            monthly_sales = get_sales_orders(days=30)['total_amount'].sum()
            st.metric("Monthly Sales", f"${monthly_sales:,.2f}")
        
        # Inventory alerts (only for managers and admins)
        if st.session_state.user['role'] in ['admin', 'manager']:
            st.subheader("Inventory Alerts")
            inventory = get_products()
            low_stock = inventory[(inventory['current_stock'] <= inventory['min_stock']) & (inventory['is_active'] == 1)]
            overstock = inventory[(inventory['max_stock'].notna()) & (inventory['current_stock'] >= inventory['max_stock']) & (inventory['is_active'] == 1)]
            
            if not low_stock.empty:
                st.warning("Low Stock Items")
                st.dataframe(low_stock[['name', 'category', 'current_stock', 'min_stock', 'unit']])
            
            if not overstock.empty:
                st.warning("Overstock Items")
                st.dataframe(overstock[['name', 'category', 'current_stock', 'max_stock', 'unit']])
            
            if low_stock.empty and overstock.empty:
                st.success("No inventory alerts")
        
        # Recent sales
        st.subheader("Recent Sales Orders")
        recent_orders = get_sales_orders(days=7)
        st.dataframe(recent_orders)
    except Exception as e:
        st.error(f"Failed to load dashboard data: {str(e)}")

def inventory_management_page():
    """Render inventory management page (only for managers and admins)"""
    if st.session_state.user['role'] not in ['admin', 'manager']:
        st.warning("You don't have permission to access this page")
        return
    
    st.title("Inventory Management")
    
    tab1, tab2, tab3 = st.tabs(["Current Inventory", "Stock Movements", "Stock Adjustment"])
    
    with tab1:
        try:
            st.subheader("Current Inventory")
            inventory = get_products()
            st.dataframe(inventory)
            
            if st.button("Export Inventory Report"):
                report = generate_inventory_report()
                csv = report.to_csv(index=False)
                st.download_button(
                    label="Download CSV",
                    data=csv,
                    file_name=f"inventory_report_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime='text/csv'
                )
        except Exception as e:
            st.error(f"Failed to load inventory data: {str(e)}")
    
    with tab2:
        try:
            st.subheader("Stock Movements")
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input("From Date", datetime.now() - timedelta(days=30))
            with col2:
                end_date = st.date_input("To Date", datetime.now())
            
            transactions = pd.read_sql(f"""
                SELECT 
                    it.created_at,
                    p.name as product,
                    it.type,
                    it.quantity,
                    it.unit_price,
                    it.total_value,
                    u.username as user,
                    s.name as supplier,
                    it.notes
                FROM inventory_transactions it
                JOIN products p ON it.product_id = p.id
                JOIN users u ON it.user_id = u.id
                LEFT JOIN suppliers s ON it.supplier_id = s.id
                WHERE date(it.created_at) BETWEEN '{start_date}' AND '{end_date}'
                ORDER BY it.created_at DESC
            """, sqlite3.connect('inventory.db'))
            
            st.dataframe(transactions)
        except Exception as e:
            st.error(f"Failed to load transaction data: {str(e)}")
    
    with tab3:
        try:
            st.subheader("Stock Adjustment")
            products = get_products()
            suppliers = get_suppliers()
            
            selected_product = st.selectbox(
                "Select Product",
                options=products['id'],
                format_func=lambda x: products[products['id'] == x]['name'].iloc[0]
            )
            
            if selected_product:
                product = get_product_by_id(selected_product)
                if not product:
                    st.error("Product not found")
                else:
                    st.write(f"Current Stock: {product['current_stock']} {product['unit']}")
                    
                    with st.form("stock_adjustment"):
                        adjustment_type = st.selectbox("Type", ["purchase", "sale", "adjustment", "return"])
                        quantity = st.number_input("Quantity", min_value=0.01, step=0.01)
                        
                        if adjustment_type == "purchase":
                            supplier_id = st.selectbox(
                                "Supplier",
                                options=suppliers['id'],
                                format_func=lambda x: suppliers[suppliers['id'] == x]['name'].iloc[0]
                            )
                        else:
                            supplier_id = None
                        
                        notes = st.text_input("Notes")
                        
                        submit = st.form_submit_button("Submit Adjustment")
                        if submit:
                            try:
                                update_product_stock(
                                    selected_product,
                                    quantity,
                                    adjustment_type,
                                    st.session_state.user['id'],
                                    supplier_id=supplier_id,
                                    notes=notes
                                )
                                st.success("Stock updated successfully!")
                                time.sleep(1)
                            except Exception as e:
                                st.error(f"Error updating stock: {str(e)}")
        except Exception as e:
            st.error(f"Failed to load product data: {str(e)}")

def product_management_page():
    """Render product management page with edit/delete functionality"""
    if st.session_state.user['role'] not in ['admin', 'manager']:
        st.warning("You don't have permission to access this page")
        return
    
    st.title("Product Management")
    
    tab1, tab2, tab3 = st.tabs(["View Products", "Add Product", "Edit Product"])
    
    with tab1:
        try:
            st.subheader("Product List")
            products = get_products(active_only=False)
            st.dataframe(products)
            
            # Barcode generation
            selected_product_id = st.selectbox(
                "Select Product to Generate Barcode",
                options=products[products['is_active'] == 1]['id'],
                format_func=lambda x: products[products['id'] == x]['name'].iloc[0],
                key="barcode_product"
            )
            
            if selected_product_id and st.button("Generate Barcode"):
                try:
                    product = get_product_by_id(selected_product_id)
                    if not product:
                        st.error("Product not found")
                    else:
                        barcode_file = generate_barcode(product['id'], product['name'])
                        
                        st.image(barcode_file, caption=f"Barcode for {product['name']}")
                        
                        with open(barcode_file, "rb") as f:
                            st.download_button(
                                label="Download Barcode",
                                data=f,
                                file_name=f"barcode_{product['name']}.png",
                                mime="image/png"
                            )
                except Exception as e:
                    st.error(f"Failed to generate barcode: {str(e)}")
        except Exception as e:
            st.error(f"Failed to load product data: {str(e)}")
    
    with tab2:
        try:
            st.subheader("Add New Product")
            suppliers = get_suppliers()
            categories = get_product_categories()
            
            with st.form("add_product_form"):
                name = st.text_input("Name*")
                description = st.text_area("Description")
                
                col1, col2 = st.columns(2)
                with col1:
                    category = st.text_input("Category")
                    if categories:
                        category = st.selectbox(
                            "Or select existing category",
                            [""] + categories,
                            index=0,
                            key="category_select"
                        )
                with col2:
                    subcategory = st.text_input("Subcategory")
                    if category:
                        subcategories = get_product_subcategories(category)
                        if subcategories:
                            subcategory = st.selectbox(
                                "Or select existing subcategory",
                                [""] + subcategories,
                                index=0,
                                key="subcategory_select"
                            )
                
                barcode = st.text_input("Barcode (leave blank to auto-generate)")
                sku = st.text_input("SKU (leave blank to auto-generate)")
                current_stock = st.number_input("Initial Stock", min_value=0.0, value=0.0)
                min_stock = st.number_input("Minimum Stock", min_value=0.0, value=5.0)
                max_stock = st.number_input("Maximum Stock (optional)", min_value=0.0)
                unit = st.text_input("Unit", value="pcs")
                cost_price = st.number_input("Cost Price", min_value=0.0, value=0.0)
                selling_price = st.number_input("Selling Price*", min_value=0.0)
                vat_rate = st.number_input("VAT Rate %", min_value=0.0, max_value=100.0, value=5.0)
                
                if not suppliers.empty:
                    supplier_id = st.selectbox(
                        "Supplier (optional)",
                        options=[None] + list(suppliers['id']),
                        format_func=lambda x: suppliers[suppliers['id'] == x]['name'].iloc[0] if x else "None"
                    )
                else:
                    supplier_id = None
                
                notes = st.text_area("Notes")
                
                submit = st.form_submit_button("Add Product")
                if submit:
                    try:
                        product_data = {
                            'name': name,
                            'description': description,
                            'category': category if category else None,
                            'subcategory': subcategory if subcategory else None,
                            'barcode': barcode if barcode else None,  # Will be auto-generated if None
                            'sku': sku if sku else None,  # Will be auto-generated if None
                            'current_stock': current_stock,
                            'min_stock': min_stock,
                            'max_stock': max_stock if max_stock > 0 else None,
                            'unit': unit,
                            'cost_price': cost_price,
                            'selling_price': selling_price,
                            'vat_rate': vat_rate,
                            'supplier_id': supplier_id,
                            'notes': notes
                        }
                        product_id = add_product(product_data)
                        st.success(f"Product added successfully! ID: {product_id}")
                        time.sleep(1)
                      
                    except Exception as e:
                        st.error(f"Error adding product: {str(e)}")
        except Exception as e:
            st.error(f"Failed to load form data: {str(e)}")
    
    with tab3:
        try:
            st.subheader("Edit Product")
            products = get_products(active_only=False)
            selected_product = st.selectbox(
                "Select Product to Edit",
                options=products[products['is_active'] == 1]['id'],
                format_func=lambda x: products[products['id'] == x]['name'].iloc[0]
            )
            
            if selected_product:
                product = get_product_by_id(selected_product)
                
                if product:
                    with st.form("edit_product_form"):
                        name = st.text_input("Name*", value=product['name'])
                        description = st.text_area("Description", value=product['description'])
                        
                        categories = get_product_categories()
                        current_category = product['category'] if product['category'] else ""
                        category = st.text_input("Category", value=current_category)
                        if categories:
                            category = st.selectbox(
                                "Or select existing category",
                                [""] + categories,
                                index=0 if not current_category else categories.index(current_category) + 1,
                                key="edit_category_select"
                            )
                        
                        subcategories = get_product_subcategories(category if category else current_category)
                        current_subcategory = product['subcategory'] if product['subcategory'] else ""
                        subcategory = st.text_input("Subcategory", value=current_subcategory)
                        if subcategories:
                            subcategory = st.selectbox(
                                "Or select existing subcategory",
                                [""] + subcategories,
                                index=0 if not current_subcategory else subcategories.index(current_subcategory) + 1,
                                key="edit_subcategory_select"
                            )
                        
                        barcode = st.text_input("Barcode", value=product['barcode'])
                        sku = st.text_input("SKU", value=product['sku'])
                        min_stock = st.number_input("Minimum Stock", min_value=0.0, value=product['min_stock'])
                        max_stock = st.number_input("Maximum Stock (optional)", min_value=0.0, value=product['max_stock'] if product['max_stock'] else 0.0)
                        unit = st.text_input("Unit", value=product['unit'])
                        cost_price = st.number_input("Cost Price", min_value=0.0, value=product['cost_price'])
                        selling_price = st.number_input("Selling Price*", min_value=0.0, value=product['selling_price'])
                        vat_rate = st.number_input("VAT Rate %", min_value=0.0, max_value=100.0, value=product['vat_rate'])
                        
                        suppliers = get_suppliers()
                        if not suppliers.empty:
                            supplier_id = st.selectbox(
                                "Supplier",
                                options=[None] + list(suppliers['id']),
                                format_func=lambda x: suppliers[suppliers['id'] == x]['name'].iloc[0] if x else "None",
                                index=0 if not product['supplier_id'] else list(suppliers['id']).index(product['supplier_id']) + 1
                            )
                        
                        notes = st.text_area("Notes", value=product['notes'])
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.form_submit_button("Update Product"):
                                try:
                                    product_data = {
                                        'name': name,
                                        'description': description,
                                        'category': category if category else None,
                                        'subcategory': subcategory if subcategory else None,
                                        'barcode': barcode,
                                        'sku': sku,
                                        'min_stock': min_stock,
                                        'max_stock': max_stock if max_stock > 0 else None,
                                        'unit': unit,
                                        'cost_price': cost_price,
                                        'selling_price': selling_price,
                                        'vat_rate': vat_rate,
                                        'supplier_id': supplier_id,
                                        'notes': notes
                                    }
                                    update_product(selected_product, product_data)
                                    st.success("Product updated successfully!")
                                    time.sleep(1)
                                    
                                except Exception as e:
                                    st.error(f"Error updating product: {str(e)}")
                        
                        with col2:
                            if st.form_submit_button("Delete Product"):
                                try:
                                    delete_product(selected_product)
                                    st.success("Product marked as inactive!")
                                    time.sleep(1)
                                    
                                except Exception as e:
                                    st.error(f"Error deleting product: {str(e)}")
                else:
                    st.error("Product not found")
        except Exception as e:
            st.error(f"Failed to load product data: {str(e)}")

def sales_management_page():
    """Render sales order management page with improved workflow"""
    st.title("Sales Order Management")
    
    try:
        # Determine available tabs based on user role
        if st.session_state.user['role'] == 'sales':
            tabs = ["Create Order", "View Orders"]
            tab1, tab2 = st.tabs(tabs)
            tab3 = None  # No third tab for sales
        elif st.session_state.user['role'] == 'manager':
            tabs = ["Approve Orders", "View Orders"]
            tab1, tab2 = st.tabs(tabs)
            tab3 = None  # No third tab for manager
        else:  # admin
            tabs = ["Create Order", "View Orders", "Process Payments"]
            tab1, tab2, tab3 = st.tabs(tabs)
        
        # CREATE ORDER TAB (for sales and admin)
        if tab1 and st.session_state.user['role'] in ['sales', 'admin']:
            with tab1:
                st.subheader("Create New Order")
                customers = get_customers()
                products = get_products()
                
                with st.form("create_order_form", clear_on_submit=True):
                    col1, col2 = st.columns(2)
                    with col1:
                        customer_id = st.selectbox(
                            "Customer*",
                            options=customers['id'],
                            format_func=lambda x: customers[customers['id'] == x]['name'].iloc[0]
                        )
                    with col2:
                        required_date = st.date_input("Required Date")
                    
                    notes = st.text_area("Notes")
                    
                    st.subheader("Order Items")
                    items = []
                    
                    # Dynamic item addition
                    num_items = st.number_input("Number of Items", min_value=1, max_value=20, value=1)
                    
                    for i in range(num_items):
                        with st.expander(f"Item {i+1}"):
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                product_id = st.selectbox(
                                    f"Product {i+1}*",
                                    options=products['id'],
                                    format_func=lambda x: products[products['id'] == x]['name'].iloc[0],
                                    key=f"product_{i}"
                                )
                            with col2:
                                quantity = st.number_input(
                                    "Quantity*",
                                    min_value=0.01,
                                    value=1.0,
                                    step=0.01,
                                    key=f"quantity_{i}"
                                )
                            with col3:
                                unit_price = st.number_input(
                                    "Unit Price*",
                                    min_value=0.0,
                                    value=products[products['id'] == product_id]['selling_price'].iloc[0],
                                    key=f"price_{i}"
                                )
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                discount = st.number_input(
                                    "Discount %",
                                    min_value=0.0,
                                    max_value=100.0,
                                    value=0.0,
                                    key=f"discount_{i}"
                                )
                            with col2:
                                vat_rate = st.number_input(
                                    "VAT Rate %",
                                    min_value=0.0,
                                    max_value=100.0,
                                    value=products[products['id'] == product_id]['vat_rate'].iloc[0],
                                    key=f"vat_{i}"
                                )
                            
                            if product_id and quantity > 0:
                                items.append({
                                    'product_id': product_id,
                                    'quantity': quantity,
                                    'unit_price': unit_price,
                                    'discount': discount,
                                    'vat_rate': vat_rate
                                })
                    
                    order_discount = st.number_input("Order Discount", min_value=0.0, max_value=100.0, value=0.0)
                    
                    submit = st.form_submit_button("Create Order")
                    if submit:
                        if not items:
                            st.error("Please add at least one item to the order")
                        else:
                            try:
                                order_data = {
                                    'customer_id': customer_id,
                                    'required_date': required_date,
                                    'notes': notes,
                                    'discount': order_discount,
                                    'user_id': st.session_state.user['id'],
                                    'items': items,
                                    'vat_rate': 5.0  # Default VAT rate
                                }
                                
                                with st.spinner("Creating order..."):
                                    order_id = create_sales_order(order_data)
                                    
                                    # For sales role, set to pending approval
                                    if st.session_state.user['role'] == 'sales':
                                        update_order_status(order_id, 'pending_approval')
                                        st.success(f"Order created successfully and sent for approval! ID: {order_id}")
                                    else:
                                        st.success(f"Order created successfully! ID: {order_id}")
                                    
                                    time.sleep(2)
                                
                            except Exception as e:
                                st.error(f"Error creating order: {str(e)}")

        # APPROVE ORDERS TAB (for manager)
        elif tab1 and st.session_state.user['role'] == 'manager':
            with tab1:
                st.subheader("Orders Pending Approval")
                pending_orders = get_sales_orders(status='pending_approval')
                
                if not pending_orders.empty:
                    selected_order = st.selectbox(
                        "Select Order to Approve",
                        options=pending_orders['id']
                    )
                    
                    order_details = pending_orders[pending_orders['id'] == selected_order].iloc[0]
                    order_items = get_order_items(selected_order)
                    
                    st.write(f"**Customer:** {order_details['customer']}")
                    st.write(f"**Order Date:** {order_details['order_date']}")
                    st.write(f"**Sales Person:** {order_details['sales_person']}")
                    st.write(f"**Total Amount:** ${order_details['total_amount']:,.2f}")
                    
                    st.dataframe(order_items)
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Approve Order"):
                            try:
                                update_order_status(selected_order, 'approved', st.session_state.user['id'])
                                st.success("Order approved successfully!")
                                time.sleep(1)
                                
                            except Exception as e:
                                st.error(f"Error: {str(e)}")
                    with col2:
                        if st.button("Reject Order"):
                            try:
                                update_order_status(selected_order, 'cancelled')
                                st.success("Order rejected successfully!")
                                time.sleep(1)
                                
                            except Exception as e:
                                st.error(f"Error: {str(e)}")
                else:
                    st.info("No orders pending approval")

        # VIEW ORDERS TAB (for all roles)
        if tab2:
            with tab2:
                st.subheader("Sales Orders")
                
                # Filter options
                col1, col2 = st.columns(2)
                with col1:
                    status_filter = st.selectbox(
                        "Filter by Status",
                        ["All", "draft", "pending_approval", "approved", "processing", "completed", "cancelled"]
                    )
                with col2:
                    days_filter = st.selectbox(
                        "Filter by Time Period",
                        ["All", "Last 7 days", "Last 30 days", "Last 90 days"]
                    )
                
                # Get orders based on filters
                try:
                    if st.session_state.user['role'] == 'sales':
                        base_orders = get_sales_orders(user_id=st.session_state.user['id'])
                    else:
                        base_orders = get_sales_orders()
                    
                    if status_filter != "All":
                        base_orders = base_orders[base_orders['status'] == status_filter]
                    
                    if days_filter != "All":
                        days = int(days_filter.split()[1])
                        cutoff_date = datetime.now() - timedelta(days=days)
                        base_orders = base_orders[pd.to_datetime(base_orders['order_date']) >= cutoff_date]
                    
                    if not base_orders.empty:
                        selected_order = st.selectbox(
                            "Select Order to View Details",
                            options=base_orders['id']
                        )
                        
                        order_details = base_orders[base_orders['id'] == selected_order].iloc[0]
                        order_items = get_order_items(selected_order)
                        
                        st.write(f"**Order ID:** {order_details['id']}")
                        st.write(f"**Customer:** {order_details['customer']}")
                        st.write(f"**Order Date:** {order_details['order_date']}")
                        st.write(f"**Status:** {order_details['status'].title()}")
                        st.write(f"**Payment Status:** {order_details['payment_status'].title() if order_details['payment_status'] else 'Not Paid'}")
                        st.write(f"**Total Amount:** ${order_details['total_amount']:,.2f}")
                        st.write(f"**Notes:** {order_details['notes']}")
                        
                        st.subheader("Order Items")
                        st.dataframe(order_items)
                        
                        # Generate invoice button (only for managers and admins)
                        if st.session_state.user['role'] in ['admin', 'manager']:
                            if st.button("Generate Invoice"):
                                try:
                                    invoice_path = generate_invoice_pdf(selected_order)
                                    
                                    with open(invoice_path, "rb") as f:
                                        st.download_button(
                                            label="Download Invoice",
                                            data=f,
                                            file_name=f"invoice_{selected_order}.pdf",
                                            mime="application/pdf"
                                        )
                                except Exception as e:
                                    st.error(f"Error generating invoice: {str(e)}")
                        
                        # Fulfill order button (for approved orders, only for managers and admins)
                        if order_details['status'] == 'approved' and st.session_state.user['role'] in ['manager', 'admin']:
                            if st.button("Fulfill Order (Deduct from Inventory)"):
                                try:
                                    fulfill_order(selected_order, st.session_state.user['id'])
                                    st.success("Order fulfilled and inventory updated!")
                                    time.sleep(1)
                                    
                                except Exception as e:
                                    st.error(f"Error: {str(e)}")
                    else:
                        st.info("No orders found matching your criteria")
                except Exception as e:
                    st.error(f"Failed to load order data: {str(e)}")

        # PROCESS PAYMENTS TAB (only for admin)
        if tab3 and st.session_state.user['role'] == 'admin':
            with tab3:
                st.subheader("Process Payments")
                
                # Get orders that need payment
                try:
                    orders = get_sales_orders()
                    payable_orders = orders[orders['status'].isin(['approved', 'processing', 'completed'])]
                    
                    if not payable_orders.empty:
                        selected_order = st.selectbox(
                            "Select Order to Process Payment",
                            options=payable_orders['id'],
                            format_func=lambda x: f"Order {x} - ${payable_orders[payable_orders['id']==x]['total_amount'].iloc[0]:.2f}"
                        )
                        
                        if selected_order:
                            order_details = payable_orders[payable_orders['id'] == selected_order].iloc[0]
                            total_paid = get_total_payments(selected_order)
                            balance = order_details['total_amount'] - total_paid
                            
                            st.write(f"**Customer:** {order_details['customer']}")
                            st.write(f"**Order Total:** ${order_details['total_amount']:,.2f}")
                            st.write(f"**Amount Paid:** ${total_paid:,.2f}")
                            st.write(f"**Balance Due:** ${balance:,.2f}")
                            
                            # Show payment history
                            payments = get_payments(selected_order)
                            if not payments.empty:
                                st.write("**Payment History**")
                                st.dataframe(payments[['payment_date', 'amount', 'payment_method', 'reference']])
                            
                            # Payment form
                            with st.form("payment_form"):
                                amount = st.number_input(
                                    "Payment Amount*",
                                    min_value=0.01,
                                    max_value=float(balance) if balance > 0 else float(order_details['total_amount']),
                                    value=min(float(balance), float(order_details['total_amount'])),
                                    step=0.01,
                                    format="%.2f"
                                )
                                
                                payment_method = st.selectbox(
                                    "Payment Method*",
                                    ["Cash", "Credit Card", "Bank Transfer", "Check", "Other"]
                                )
                                
                                payment_date = st.date_input("Payment Date", datetime.now())
                                reference = st.text_input("Reference/Check Number")
                                notes = st.text_area("Notes")
                                
                                submitted = st.form_submit_button("Process Payment")
                                if submitted:
                                    try:
                                        payment_id = process_order_payment(
                                            selected_order,
                                            amount,
                                            payment_method,
                                            reference,
                                            notes,
                                            st.session_state.user['id']
                                        )
                                        st.success(f"Payment processed successfully! Payment ID: {payment_id}")
                                        time.sleep(1)
                                        
                                    except Exception as e:
                                        st.error(f"Error processing payment: {str(e)}")
                    else:
                        st.info("No payable orders found")
                except Exception as e:
                    st.error(f"Failed to load payment data: {str(e)}")
    except Exception as e:
        st.error(f"Error in sales management: {str(e)}")

def customer_management_page():
    """Render customer management page (only for managers and admins)"""
    if st.session_state.user['role'] not in ['admin', 'manager']:
        st.warning("You don't have permission to access this page")
        return
    
    st.title("Customer Management")
    
    tab1, tab2, tab3 = st.tabs(["View Customers", "Add Customer", "Edit Customer"])
    
    with tab1:
        try:
            st.subheader("Customer List")
            customers = get_customers(active_only=False)
            st.dataframe(customers)
        except Exception as e:
            st.error(f"Failed to load customer data: {str(e)}")
    
    with tab2:
        try:
            st.subheader("Add New Customer")
            with st.form("add_customer_form"):
                name = st.text_input("Name*")
                tax_number = st.text_input("Tax Number")
                contact = st.text_input("Contact Person")
                email = st.text_input("Email")
                phone = st.text_input("Phone")
                address = st.text_area("Address*")
                payment_terms = st.number_input("Payment Terms (days)", min_value=0, value=30)
                credit_limit = st.number_input("Credit Limit", min_value=0.0, value=0.0)
                
                submit = st.form_submit_button("Add Customer")
                if submit:
                    try:
                        customer_data = {
                            'name': name,
                            'tax_number': tax_number,
                            'contact': contact,
                            'email': email,
                            'phone': phone,
                            'address': address,
                            'payment_terms': payment_terms,
                            'credit_limit': credit_limit
                        }
                        customer_id = add_customer(customer_data)
                        st.success(f"Customer added successfully! ID: {customer_id}")
                        time.sleep(1)
                        
                    except Exception as e:
                        st.error(f"Error adding customer: {str(e)}")
        except Exception as e:
            st.error(f"Failed to load form data: {str(e)}")
    
    with tab3:
        try:
            st.subheader("Edit Customer")
            customers = get_customers(active_only=False)
            selected_customer = st.selectbox(
                "Select Customer",
                options=customers['id'],
                format_func=lambda x: customers[customers['id'] == x]['name'].iloc[0]
            )
            
            if selected_customer:
                customer = get_customer_by_id(selected_customer)
                
                with st.form("edit_customer_form"):
                    new_name = st.text_input("Name", value=customer['name'])
                    new_tax = st.text_input("Tax Number", value=customer['tax_number'])
                    new_contact = st.text_input("Contact Person", value=customer['contact'])
                    new_email = st.text_input("Email", value=customer['email'])
                    new_phone = st.text_input("Phone", value=customer['phone'])
                    new_address = st.text_area("Address", value=customer['address'])
                    new_terms = st.number_input(
                        "Payment Terms (days)", 
                        min_value=0, 
                        value=customer['payment_terms']
                    )
                    new_credit = st.number_input(
                        "Credit Limit", 
                        min_value=0.0, 
                        value=customer['credit_limit']
                    )
                    is_active = st.checkbox("Active", value=bool(customer['is_active']))
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.form_submit_button("Update Customer"):
                            try:
                                customer_data = {
                                    'name': new_name,
                                    'tax_number': new_tax,
                                    'contact': new_contact,
                                    'email': new_email,
                                    'phone': new_phone,
                                    'address': new_address,
                                    'payment_terms': new_terms,
                                    'credit_limit': new_credit
                                }
                                update_customer(selected_customer, customer_data)
                                set_customer_status(selected_customer, is_active)
                                st.success("Customer updated successfully!")
                                time.sleep(1)
                                
                            except Exception as e:
                                st.error(f"Error updating customer: {str(e)}")
        except Exception as e:
            st.error(f"Failed to load customer data: {str(e)}")

def supplier_management_page():
    """Render supplier management page (only for managers and admins)"""
    if st.session_state.user['role'] not in ['admin', 'manager']:
        st.warning("You don't have permission to access this page")
        return
    
    st.title("Supplier Management")
    
    tab1, tab2, tab3 = st.tabs(["View Suppliers", "Add Supplier", "Edit Supplier"])
    
    with tab1:
        try:
            st.subheader("Supplier List")
            suppliers = get_suppliers(active_only=False)
            st.dataframe(suppliers)
        except Exception as e:
            st.error(f"Failed to load supplier data: {str(e)}")
    
    with tab2:
        try:
            st.subheader("Add New Supplier")
            with st.form("add_supplier_form"):
                name = st.text_input("Name*")
                contact_person = st.text_input("Contact Person")
                email = st.text_input("Email")
                phone = st.text_input("Phone")
                address = st.text_area("Address")
                tax_number = st.text_input("Tax Number")
                payment_terms = st.number_input("Payment Terms (days)", min_value=0, value=30)
                notes = st.text_area("Notes")
                
                submit = st.form_submit_button("Add Supplier")
                if submit:
                    try:
                        supplier_data = {
                            'name': name,
                            'contact_person': contact_person,
                            'email': email,
                            'phone': phone,
                            'address': address,
                            'tax_number': tax_number,
                            'payment_terms': payment_terms,
                            'notes': notes
                        }
                        supplier_id = add_supplier(supplier_data)
                        st.success(f"Supplier added successfully! ID: {supplier_id}")
                        time.sleep(1)
                        
                    except Exception as e:
                        st.error(f"Error adding supplier: {str(e)}")
        except Exception as e:
            st.error(f"Failed to load form data: {str(e)}")
    
    with tab3:
        try:
            st.subheader("Edit Supplier")
            suppliers = get_suppliers(active_only=False)
            selected_supplier = st.selectbox(
                "Select Supplier",
                options=suppliers['id'],
                format_func=lambda x: suppliers[suppliers['id'] == x]['name'].iloc[0]
            )
            
            if selected_supplier:
                supplier = get_supplier_by_id(selected_supplier)
                
                with st.form("edit_supplier_form"):
                    new_name = st.text_input("Name", value=supplier['name'])
                    new_contact = st.text_input("Contact Person", value=supplier['contact_person'])
                    new_email = st.text_input("Email", value=supplier['email'])
                    new_phone = st.text_input("Phone", value=supplier['phone'])
                    new_address = st.text_area("Address", value=supplier['address'])
                    new_tax = st.text_input("Tax Number", value=supplier['tax_number'])
                    new_terms = st.number_input(
                        "Payment Terms (days)", 
                        min_value=0, 
                        value=supplier['payment_terms']
                    )
                    new_notes = st.text_area("Notes", value=supplier['notes'])
                    is_active = st.checkbox("Active", value=bool(supplier['is_active']))
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.form_submit_button("Update Supplier"):
                            try:
                                supplier_data = {
                                    'name': new_name,
                                    'contact_person': new_contact,
                                    'email': new_email,
                                    'phone': new_phone,
                                    'address': new_address,
                                    'tax_number': new_tax,
                                    'payment_terms': new_terms,
                                    'notes': new_notes
                                }
                                update_supplier(selected_supplier, supplier_data)
                                set_supplier_status(selected_supplier, is_active)
                                st.success("Supplier updated successfully!")
                                time.sleep(1)
                                
                            except Exception as e:
                                st.error(f"Error updating supplier: {str(e)}")
        except Exception as e:
            st.error(f"Failed to load supplier data: {str(e)}")

def user_management_page():
    """Render user management page (only for admins)"""
    if st.session_state.user['role'] != 'admin':
        st.warning("You don't have permission to access this page")
        return
    
    st.title("User Management")
    
    tab1, tab2, tab3 = st.tabs(["View Users", "Add User", "Edit User"])
    
    with tab1:
        try:
            st.subheader("User List")
            users = get_users(active_only=False)
            st.dataframe(users)
        except Exception as e:
            st.error(f"Failed to load user data: {str(e)}")
    
    with tab2:
        try:
            st.subheader("Add New User")
            with st.form("add_user_form"):
                username = st.text_input("Username*")
                password = st.text_input("Password*", type="password")
                role = st.selectbox("Role*", ["admin", "manager", "sales"])
                full_name = st.text_input("Full Name")
                email = st.text_input("Email")
                phone = st.text_input("Phone")
                
                submit = st.form_submit_button("Add User")
                if submit:
                    try:
                        user_data = {
                            'username': username,
                            'password': password,
                            'role': role,
                            'full_name': full_name,
                            'email': email,
                            'phone': phone
                        }
                        user_id = add_user(user_data)
                        st.success(f"User added successfully! ID: {user_id}")
                        time.sleep(1)
                        
                    except Exception as e:
                        st.error(f"Error adding user: {str(e)}")
        except Exception as e:
            st.error(f"Failed to load form data: {str(e)}")
    
    with tab3:
        try:
            st.subheader("Edit User")
            users = get_users(active_only=False)
            selected_user = st.selectbox(
                "Select User",
                options=users['id'],
                format_func=lambda x: users[users['id'] == x]['username'].iloc[0]
            )
            
            if selected_user:
                user = users[users['id'] == selected_user].iloc[0]
                
                with st.form("edit_user_form"):
                    new_username = st.text_input("Username", value=user['username'])
                    new_role = st.selectbox(
                        "Role",
                        ["admin", "manager", "sales"],
                        index=["admin", "manager", "sales"].index(user['role'])
                    )
                    new_full_name = st.text_input("Full Name", value=user['full_name'])
                    new_email = st.text_input("Email", value=user['email'])
                    new_phone = st.text_input("Phone", value=user['phone'])
                    is_active = st.checkbox("Active", value=bool(user['is_active']))
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.form_submit_button("Update User"):
                            try:
                                user_data = {
                                    'username': new_username,
                                    'role': new_role,
                                    'full_name': new_full_name,
                                    'email': new_email,
                                    'phone': new_phone
                                }
                                update_user(selected_user, user_data)
                                set_user_status(selected_user, is_active)
                                st.success("User updated successfully!")
                                time.sleep(1)
                                
                            except Exception as e:
                                st.error(f"Error updating user: {str(e)}")
                    
                    with col2:
                        if st.form_submit_button("Change Password"):
                            new_password = st.text_input("New Password", type="password", key="new_password")
                            if new_password:
                                try:
                                    change_user_password(selected_user, new_password)
                                    st.success("Password changed successfully!")
                                    time.sleep(1)
                                    
                                except Exception as e:
                                    st.error(f"Error: {str(e)}")
        except Exception as e:
            st.error(f"Failed to load user data: {str(e)}")

def reporting_page():
    """Render reporting page (only for managers and admins)"""
    if st.session_state.user['role'] not in ['admin', 'manager']:
        st.warning("You don't have permission to access this page")
        return
    
    st.title("Reporting")
    
    try:
        report_type = st.selectbox(
            "Select Report Type",
            ["Sales Report", "VAT Report", "Inventory Report", "Supplier Report"]
        )
        
        if report_type in ["Sales Report", "VAT Report"]:
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input("Start Date", datetime.now() - timedelta(days=30))
            with col2:
                end_date = st.date_input("End Date", datetime.now())
        
        if st.button("Generate Report"):
            with st.spinner("Generating report..."):
                try:
                    if report_type == "Sales Report":
                        report = generate_sales_report(start_date, end_date)
                    elif report_type == "VAT Report":
                        report = generate_vat_report(start_date, end_date)
                    elif report_type == "Inventory Report":
                        report = generate_inventory_report()
                    elif report_type == "Supplier Report":
                        report = get_suppliers()
                    
                    st.session_state.current_report = report
                    st.success("Report generated successfully!")
                except Exception as e:
                    st.error(f"Failed to generate report: {str(e)}")
        
        if 'current_report' in st.session_state and st.session_state.current_report is not None:
            st.subheader(f"{report_type} Results")
            st.dataframe(st.session_state.current_report)
            
            # Add visualization for sales report
            if report_type == "Sales Report":
                try:
                    fig, ax = plt.subplots()
                    sales_by_date = st.session_state.current_report.groupby('order_date')['total_amount'].sum()
                    if not sales_by_date.empty:
                        sales_by_date.plot(kind='line', ax=ax)
                        ax.set_title("Daily Sales Trend")
                        ax.set_ylabel("Total Amount")
                        st.pyplot(fig)
                    else:
                        st.info("No sales data to visualize")
                except Exception as e:
                    st.error(f"Error generating visualization: {str(e)}")
            
            # Export options
            csv = st.session_state.current_report.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"{report_type.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.csv",
                mime='text/csv'
            )
    except Exception as e:
        st.error(f"Failed to initialize reporting page: {str(e)}")

def login_page():
    """Render the login page"""
    st.title("Inventory & Sales Management System")
    
    with st.form("login_form"):
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        submit = st.form_submit_button("Login")
        
        if submit:
            with st.spinner("Authenticating..."):
                try:
                    user = authenticate_user(username, password)
                    if user:
                        st.session_state.user = user
                        update_last_login(user['id'])
                        st.success("Login successful!")
                        time.sleep(1)
                        
                    else:
                        st.error("Invalid username or password")
                except Exception as e:
                    st.error(f"Authentication error: {str(e)}")

# ==============================================
# MAIN APPLICATION
# ==============================================

def main():
    # Initialize app settings
    st.set_page_config(
        page_title="Inventory & Sales Management",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Initialize database and session
    try:
        initialize_database()
    except Exception as e:
        st.error(f"Failed to initialize database: {str(e)}")
        st.stop()
    
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'current_report' not in st.session_state:
        st.session_state.current_report = None
    
    # Custom CSS
    st.markdown("""
        <style>
            .main {padding: 2rem;}
            .sidebar .sidebar-content {background-color: #f8f9fa;}
            .metric-card {background-color: #f0f2f6; border-radius: 10px; padding: 15px; margin-bottom: 15px;}
            .stAlert {border-radius: 10px;}
            .stDataFrame {border-radius: 10px;}
            .stButton>button {border-radius: 5px;}
            .stTextInput>div>div>input {border-radius: 5px;}
            .stSelectbox>div>div>select {border-radius: 5px;}
            .stTextArea>div>div>textarea {border-radius: 5px;}
            .stDateInput>div>div>input {border-radius: 5px;}
            .stNumberInput>div>div>input {border-radius: 5px;}
        </style>
    """, unsafe_allow_html=True)
    
    # Show appropriate page based on auth state
    if st.session_state.user is None:
        login_page()
    else:
        # Sidebar navigation
        with st.sidebar:
            st.title(f"Welcome, {st.session_state.user.get('full_name', st.session_state.user['username'])}")
            st.caption(f"Role: {st.session_state.user['role'].title()}")
            
            # Navigation options based on role
            if st.session_state.user['role'] == 'sales':
                nav_options = ["Dashboard", "Sales"]
            elif st.session_state.user['role'] == 'manager':
                nav_options = ["Dashboard", "Inventory", "Products", "Sales", "Customers", "Suppliers", "Reports"]
            else:  # admin
                nav_options = ["Dashboard", "Inventory", "Products", "Sales", "Customers", "Suppliers", "Reports", "User Management"]
            
            selected_page = st.radio("Navigation", nav_options)
            
            if st.button("Logout"):
                st.session_state.user = None
                
        
        # Main content area
        try:
            if selected_page == "Dashboard":
                dashboard_page()
            elif selected_page == "Inventory":
                inventory_management_page()
            elif selected_page == "Products":
                product_management_page()
            elif selected_page == "Sales":
                sales_management_page()
            elif selected_page == "Customers":
                customer_management_page()
            elif selected_page == "Suppliers":
                supplier_management_page()
            elif selected_page == "Reports":
                reporting_page()
            elif selected_page == "User Management":
                user_management_page()
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    # Create required directories
    os.makedirs("assets/barcodes", exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    
    # Run the application
    try:
        main()
    except Exception as e:
        st.error(f"Application error: {str(e)}")
