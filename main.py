import streamlit as st
import psycopg2
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import bcrypt
import os
from datetime import datetime
import urllib.parse

# Database connection function
def get_connection():
    # Your Neon database URL
    db_url = "postgresql://neondb_owner:npg_OIs9AMbuLm4G@ep-winter-morning-adik1lij-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require"
    return psycopg2.connect(db_url)

# Database initialization
def init_main_database():
    """Initialize the main users database"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # Create users table in main database
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        
        # Create default admin user if no users exist
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            hashed_pw = hash_password("admin123")
            cur.execute(
                "INSERT INTO users (name, phone, password_hash) VALUES (%s, %s, %s)",
                ("Admin User", "admin", hashed_pw)
            )
            conn.commit()
        
    except Exception as e:
        st.error(f"Main database initialization error: {e}")
        conn.rollback()
    finally:
        conn.close()

def init_user_database(user_id):
    """Initialize database for a specific user"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # Create suppliers table
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS suppliers_{user_id} (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                contact_number TEXT NOT NULL,
                email TEXT,
                address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create products table
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS products_{user_id} (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                supplier_id INTEGER REFERENCES suppliers_{user_id}(id),
                quantity INTEGER NOT NULL DEFAULT 0,
                min_threshold INTEGER NOT NULL DEFAULT 10,
                unit_price DECIMAL(10,2),
                category TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create inventory_logs table
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS inventory_logs_{user_id} (
                id SERIAL PRIMARY KEY,
                product_id INTEGER REFERENCES products_{user_id}(id),
                action TEXT NOT NULL,
                quantity_change INTEGER NOT NULL,
                previous_quantity INTEGER NOT NULL,
                new_quantity INTEGER NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create WhatsApp templates table
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS whatsapp_templates_{user_id} (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                template_text TEXT NOT NULL,
                is_default BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        
        # Initialize WhatsApp templates after table creation
        init_whatsapp_templates(user_id)
        
    except Exception as e:
        st.error(f"User database initialization error: {e}")
        conn.rollback()
    finally:
        conn.close()

# Authentication functions
def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def register_user(name, phone, password):
    conn = get_connection()
    try:
        cur = conn.cursor()
        hashed_pw = hash_password(password)
        cur.execute(
            "INSERT INTO users (name, phone, password_hash) VALUES (%s, %s, %s) RETURNING id",
            (name, phone, hashed_pw)
        )
        user_id = cur.fetchone()[0]
        conn.commit()
        
        # Initialize user's personal database
        init_user_database(user_id)
        return user_id
    except psycopg2.IntegrityError:
        return None
    finally:
        conn.close()

def login_user(phone, password):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, password_hash FROM users WHERE phone = %s", (phone,))
        user = cur.fetchone()
        if user and verify_password(password, user[2]):
            return {"id": user[0], "name": user[1]}
        return None
    finally:
        conn.close()

# Supplier CRUD operations
def add_supplier(name, contact_number, email, address, user_id):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO suppliers_{user_id} (name, contact_number, email, address) VALUES (%s, %s, %s, %s) RETURNING id",
            (name, contact_number, email, address)
        )
        supplier_id = cur.fetchone()[0]
        conn.commit()
        return supplier_id
    finally:
        conn.close()

def get_suppliers(user_id):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT id, name, contact_number, email, address FROM suppliers_{user_id} ORDER BY name")
        return cur.fetchall()
    finally:
        conn.close()

def update_supplier(supplier_id, name, contact_number, email, address, user_id):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE suppliers_{user_id} SET name = %s, contact_number = %s, email = %s, address = %s WHERE id = %s",
            (name, contact_number, email, address, supplier_id)
        )
        conn.commit()
    finally:
        conn.close()

def delete_supplier(supplier_id, user_id):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM suppliers_{user_id} WHERE id = %s", (supplier_id,))
        conn.commit()
    finally:
        conn.close()

# Product CRUD operations
def add_product(name, supplier_id, quantity, min_threshold, unit_price, category, description, user_id):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO products_{user_id} (name, supplier_id, quantity, min_threshold, unit_price, category, description) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (name, supplier_id, quantity, min_threshold, unit_price, category, description)
        )
        product_id = cur.fetchone()[0]
        conn.commit()
        log_inventory_change(product_id, "ADD", quantity, 0, quantity, user_id)
        return product_id
    finally:
        conn.close()

def get_products(user_id):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT p.id, p.name, s.name as supplier_name, p.quantity, p.min_threshold, 
                   p.unit_price, p.category, p.description, s.contact_number
            FROM products_{user_id} p 
            LEFT JOIN suppliers_{user_id} s ON p.supplier_id = s.id 
            ORDER BY p.name
        """)
        return cur.fetchall()
    finally:
        conn.close()

def update_product_quantity(product_id, new_quantity, user_id, action="UPDATE"):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT quantity FROM products_{user_id} WHERE id = %s", (product_id,))
        old_quantity = cur.fetchone()[0]
        
        cur.execute(f"UPDATE products_{user_id} SET quantity = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (new_quantity, product_id))
        conn.commit()
        
        quantity_change = new_quantity - old_quantity
        log_inventory_change(product_id, action, quantity_change, old_quantity, new_quantity, user_id)
    finally:
        conn.close()

def get_low_stock_products(user_id):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT p.id, p.name, s.name as supplier_name, p.quantity, p.min_threshold, s.contact_number
            FROM products_{user_id} p 
            LEFT JOIN suppliers_{user_id} s ON p.supplier_id = s.id 
            WHERE p.quantity <= p.min_threshold
            ORDER BY p.quantity ASC
        """)
        return cur.fetchall()
    finally:
        conn.close()

def log_inventory_change(product_id, action, quantity_change, previous_quantity, new_quantity, user_id):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO inventory_logs_{user_id} (product_id, action, quantity_change, previous_quantity, new_quantity) VALUES (%s, %s, %s, %s, %s)",
            (product_id, action, quantity_change, previous_quantity, new_quantity)
        )
        conn.commit()
    finally:
        conn.close()

def init_whatsapp_templates(user_id):
    """Initialize WhatsApp templates table for user"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # Create default templates if none exist
        cur.execute(f"SELECT COUNT(*) FROM whatsapp_templates_{user_id}")
        if cur.fetchone()[0] == 0:
            default_templates = [
                ("Professional Reorder", """Hello {supplier_name},

I hope this message finds you well. We need to reorder the following items:

{items_list}

Please confirm availability and provide updated pricing in Rupees (₹).

Best regards,
{company_name}""", True),
                ("Urgent Reorder", """🚨 URGENT REORDER REQUEST 🚨

Hi {supplier_name},

We urgently need the following items:

{items_list}

Please prioritize this order and confirm delivery timeline with pricing in ₹.

Thanks,
{company_name}""", False),
                ("Friendly Reorder", """Hi {supplier_name}! 👋

Hope you're doing great! We need to stock up on:

{items_list}

Let me know when you can deliver these with pricing in ₹. Thanks!

{company_name}""", False)
            ]
            
            for template in default_templates:
                cur.execute(
                    f"INSERT INTO whatsapp_templates_{user_id} (name, template_text, is_default) VALUES (%s, %s, %s)",
                    template
                )
        
        conn.commit()
    except Exception as e:
        st.error(f"WhatsApp templates initialization error: {e}")
        conn.rollback()
    finally:
        conn.close()

def get_whatsapp_templates(user_id):
    """Get all WhatsApp templates for a user"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT id, name, template_text, is_default FROM whatsapp_templates_{user_id} ORDER BY is_default DESC, name")
        return cur.fetchall()
    finally:
        conn.close()

def add_whatsapp_template(name, template_text, user_id):
    """Add a new WhatsApp template"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO whatsapp_templates_{user_id} (name, template_text) VALUES (%s, %s) RETURNING id",
            (name, template_text)
        )
        template_id = cur.fetchone()[0]
        conn.commit()
        return template_id
    finally:
        conn.close()

def delete_whatsapp_template(template_id, user_id):
    """Delete a WhatsApp template"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM whatsapp_templates_{user_id} WHERE id = %s AND is_default = FALSE", (template_id,))
        conn.commit()
    finally:
        conn.close()

def update_whatsapp_template(template_id, name, template_text, user_id):
    """Update a WhatsApp template"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE whatsapp_templates_{user_id} SET name = %s, template_text = %s WHERE id = %s AND is_default = FALSE",
            (name, template_text, template_id)
        )
        conn.commit()
    finally:
        conn.close()

def generate_whatsapp_message(supplier_name, contact_number, items_with_quantities, template_text=None, company_name="Inventory Management Team"):
    """Generate WhatsApp message with custom template and quantities"""
    if not template_text:
        template_text = """Hello {supplier_name},

We need to reorder the following items:

{items_list}

Please let us know the availability and pricing.

Thanks,
{company_name}"""
    
    # Format items list
    items_list = ""
    for item in items_with_quantities:
        items_list += f"• {item['name']}: {item['quantity']} units (Current stock: {item['current_stock']})\n"
    
    # Replace placeholders
    message = template_text.replace("{supplier_name}", supplier_name)
    message = message.replace("{items_list}", items_list.strip())
    message = message.replace("{company_name}", company_name)
    
    encoded_message = urllib.parse.quote(message)
    whatsapp_url = f"https://wa.me/{contact_number.replace('+', '')}?text={encoded_message}"
    return whatsapp_url

def load_custom_css():
    st.markdown("""
    <style>
    /* Import Google Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap');
    
    /* Global Styles */
    .main {
        font-family: 'Inter', sans-serif;
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%) !important;
        padding: 0 !important;
        color: #f8fafc !important;
        min-height: 100vh;
    }
    
    .block-container {
        padding: 1rem !important;
        max-width: 1200px !important;
        background: transparent !important;
        color: #f8fafc !important;
    }
    
    /* Hide Streamlit default elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {visibility: hidden;}
    
    /* Custom Header */
    .custom-header {
        background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 50%, #ec4899 100%);
        padding: 3rem 2rem;
        border-radius: 24px;
        margin-bottom: 2rem;
        text-align: center;
        box-shadow: 0 25px 50px rgba(59, 130, 246, 0.3), 0 0 0 1px rgba(255, 255, 255, 0.1);
        position: relative;
        overflow: hidden;
        border: 1px solid rgba(255, 255, 255, 0.2);
        backdrop-filter: blur(10px);
    }
    
    .custom-header::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="20" cy="20" r="2" fill="rgba(255,255,255,0.1)"/><circle cx="80" cy="40" r="3" fill="rgba(255,255,255,0.1)"/><circle cx="40" cy="80" r="1" fill="rgba(255,255,255,0.1)"/></svg>');
        pointer-events: none;
    }
    
    .custom-header h1 {
        color: white;
        font-size: 2.5rem;
        font-weight: 700;
        margin: 0;
        text-shadow: 1px 1px 3px rgba(0,0,0,0.3);
        position: relative;
        z-index: 1;
    }
    
    .custom-header p {
        color: rgba(255,255,255,0.95);
        font-size: 1.1rem;
        margin: 0.8rem 0 0 0;
        font-weight: 400;
        position: relative;
        z-index: 1;
    }
    
    /* Navigation Cards */
    .nav-container {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        gap: 2rem;
        margin: 2rem 0;
    }
    
    .nav-card {
        background: rgba(255, 255, 255, 0.1);
        border-radius: 20px;
        padding: 2rem;
        text-align: center;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.2);
        border: 1px solid rgba(255, 255, 255, 0.2);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        cursor: pointer;
        position: relative;
        overflow: hidden;
        backdrop-filter: blur(16px);
    }
    
    .nav-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 4px;
        background: #2563eb;
        transform: translateX(-100%);
        transition: transform 0.3s ease;
    }
    
    .nav-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(37, 99, 235, 0.15);
        border-color: #2563eb;
    }
    
    .nav-card:hover::before {
        transform: translateX(0);
    }
    
    .nav-card-icon {
        font-size: 3rem;
        margin-bottom: 1rem;
    }
    
    .nav-card-title {
        font-size: 1.2rem;
        font-weight: 600;
        color: #1f2937;
        margin: 0 0 0.5rem 0;
    }
    
    .nav-card-desc {
        font-size: 0.9rem;
        color: #6b7280;
        margin: 0;
        line-height: 1.4;
    }
    
    /* Metric Cards */
    .metrics-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 2rem;
        margin: 2rem 0;
    }
    
    .metric-card {
        background: rgba(15, 23, 42, 0.8);
        border-radius: 16px;
        padding: 2rem 1.5rem;
        text-align: center;
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 10px 10px -5px rgba(0, 0, 0, 0.2);
        border: 1px solid rgba(148, 163, 184, 0.2);
        position: relative;
        overflow: hidden;
        backdrop-filter: blur(16px);
        transition: all 0.3s ease;
    }
    
    .metric-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.6);
        border-color: rgba(59, 130, 246, 0.5);
    }
    
    .metric-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: linear-gradient(90deg, #3b82f6, #8b5cf6, #ec4899);
    }
    
    .metric-value {
        font-size: 2.5rem;
        font-weight: 800;
        background: linear-gradient(135deg, #60a5fa, #a78bfa);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin: 0 0 0.5rem 0;
        font-family: 'JetBrains Mono', monospace;
    }
    
    .metric-label {
        font-size: 1rem;
        color: #cbd5e1;
        font-weight: 600;
        margin: 0;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    /* Forms */
    .stTextInput > div > div > input,
    .stSelectbox > div > div > select,
    .stTextArea > div > div > textarea,
    .stNumberInput > div > div > input {
        border-radius: 12px !important;
        border: 1px solid rgba(148, 163, 184, 0.3) !important;
        padding: 1rem !important;
        font-size: 1rem !important;
        transition: all 0.3s ease !important;
        background: rgba(15, 23, 42, 0.6) !important;
        color: #f8fafc !important;
        backdrop-filter: blur(8px);
    }
    
    .stTextInput > div > div > input:focus,
    .stSelectbox > div > div > select:focus,
    .stTextArea > div > div > textarea:focus,
    .stNumberInput > div > div > input:focus {
        border-color: #3b82f6 !important;
        box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2) !important;
        outline: none !important;
        background: rgba(15, 23, 42, 0.8) !important;
    }
    
    .stButton > button {
        background: linear-gradient(135deg, #3b82f6, #8b5cf6) !important;
        color: white !important;
        border: none !important;
        border-radius: 12px !important;
        padding: 1rem 2rem !important;
        font-weight: 700 !important;
        font-size: 1rem !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        box-shadow: 0 10px 25px rgba(59, 130, 246, 0.3) !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    .stButton > button:hover {
        background: linear-gradient(135deg, #1d4ed8, #7c3aed) !important;
        transform: translateY(-2px) !important;
        box-shadow: 0 20px 40px rgba(59, 130, 246, 0.4) !important;
    }
    
    /* Tables */
    .dataframe {
        background: white !important;
        border-radius: 16px !important;
        overflow: hidden !important;
        box-shadow: 0 8px 30px rgba(0,0,0,0.05) !important;
        border: 1px solid #f1f5f9 !important;
    }
    
    /* Alert Cards */
    .alert-card {
        background: #fef2f2;
        color: #991b1b;
        border-radius: 12px;
        padding: 1.5rem;
        margin: 1.5rem 0;
        box-shadow: 0 2px 8px rgba(239, 68, 68, 0.1);
        border: 2px solid #fecaca;
    }
    
    .alert-card h3 {
        margin: 0 0 1rem 0;
        font-weight: 600;
        font-size: 1.3rem;
        color: #dc2626;
    }
    
    .alert-card p {
        margin: 0;
        line-height: 1.5;
        color: #991b1b;
    }
    
    /* Success Cards */
    .success-card {
        background: #f0fdf4;
        color: #166534;
        border-radius: 12px;
        padding: 1.5rem;
        margin: 1.5rem 0;
        box-shadow: 0 2px 8px rgba(16, 185, 129, 0.1);
        border: 2px solid #bbf7d0;
    }
    
    .success-card h3 {
        margin: 0 0 1rem 0;
        font-weight: 600;
        font-size: 1.3rem;
        color: #059669;
    }
    
    /* Product Cards */
    .product-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
        gap: 1.5rem;
        margin: 2rem 0;
    }
    
    .product-card {
        background: rgba(15, 23, 42, 0.8);
        border-radius: 16px;
        padding: 1.5rem;
        box-shadow: 0 10px 25px rgba(0, 0, 0, 0.3);
        border: 1px solid rgba(148, 163, 184, 0.2);
        transition: all 0.3s ease;
        backdrop-filter: blur(16px);
    }
    
    .product-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
        border-color: rgba(59, 130, 246, 0.5);
    }
    
    .product-name {
        font-size: 1.2rem;
        font-weight: 700;
        color: #f8fafc;
        margin: 0 0 0.5rem 0;
    }
    
    .product-supplier {
        color: #94a3b8;
        font-size: 1rem;
        margin: 0 0 1rem 0;
    }
    
    .stock-status {
        display: inline-block;
        padding: 0.4rem 0.8rem;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 500;
    }
    
    .stock-low {
        background: #fef2f2;
        color: #dc2626;
        border: 1px solid #fecaca;
    }
    
    .stock-good {
        background: #f0fdf4;
        color: #16a34a;
        border: 1px solid #bbf7d0;
    }
    
    /* Login Container */
    .login-container {
        max-width: 500px !important;
        margin: 3rem auto !important;
        background: rgba(15, 23, 42, 0.9) !important;
        border-radius: 24px !important;
        padding: 3rem !important;
        box-shadow: 0 25px 50px rgba(0, 0, 0, 0.5) !important;
        border: 1px solid rgba(148, 163, 184, 0.2) !important;
        backdrop-filter: blur(20px);
    }
    
    .login-header {
        text-align: center;
        margin-bottom: 2rem;
    }
    
    .login-title {
        font-size: 2.5rem !important;
        font-weight: 800 !important;
        background: linear-gradient(135deg, #60a5fa, #a78bfa) !important;
        -webkit-background-clip: text !important;
        -webkit-text-fill-color: transparent !important;
        background-clip: text !important;
        margin: 0 0 0.5rem 0 !important;
    }
    
    .login-subtitle {
        color: #cbd5e1 !important;
        margin: 0 !important;
        font-size: 1.1rem !important;
    }
    
    /* Page Headers */
    .page-header {
        background: rgba(15, 23, 42, 0.8) !important;
        border-radius: 16px !important;
        padding: 2rem !important;
        margin-bottom: 2rem !important;
        border: 1px solid rgba(148, 163, 184, 0.2) !important;
        box-shadow: 0 10px 25px rgba(0, 0, 0, 0.3) !important;
        backdrop-filter: blur(16px);
    }
    
    .page-title {
        font-size: 2rem !important;
        font-weight: 700 !important;
        color: #f8fafc !important;
        margin: 0 0 0.5rem 0 !important;
    }
    
    .page-subtitle {
        color: #cbd5e1 !important;
        margin: 0 !important;
        font-size: 1.1rem !important;
    }
    
    /* Tables */
    .dataframe {
        background: rgba(15, 23, 42, 0.8) !important;
        border-radius: 12px !important;
        overflow: hidden !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08) !important;
        border: 1px solid rgba(148, 163, 184, 0.2) !important;
    }
    
    /* Expander styling */
    .streamlit-expanderHeader {
        background: rgba(15, 23, 42, 0.8) !important;
        border-radius: 8px !important;
        border: 1px solid rgba(148, 163, 184, 0.2) !important;
        padding: 1rem !important;
    }
    
    /* Sidebar styling */
    .css-1d391kg {
        background: rgba(15, 23, 42, 0.9) !important;
        border-right: 1px solid rgba(148, 163, 184, 0.2) !important;
    }
    
    /* WhatsApp Button */
    .whatsapp-btn {
        display: inline-block;
        background: #25D366;
        color: white;
        padding: 0.75rem 1.5rem;
        border-radius: 8px;
        text-decoration: none;
        font-weight: 600;
        margin-top: 1rem;
        box-shadow: 0 2px 8px rgba(37, 211, 102, 0.2);
        transition: all 0.2s ease;
    }
    
    .whatsapp-btn:hover {
        background: #22c55e;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(37, 211, 102, 0.3);
        text-decoration: none;
        color: white;
    }
    
    /* Streamlit specific overrides */
    .stApp {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%) !important;
        color: #f8fafc !important;
    }
    
    .main .block-container {
        background: transparent !important;
        color: #f8fafc !important;
    }
    
    /* Fix all text elements */
    .stMarkdown, .stText, p, span, div, label, .stSelectbox label, .stTextInput label, .stNumberInput label, .stTextArea label {
        color: #f8fafc !important;
    }
    
    /* Ensure form labels are light */
    .stSelectbox > label, .stTextInput > label, .stNumberInput > label, .stTextArea > label, .stButton > label {
        color: #e2e8f0 !important;
        font-weight: 600 !important;
        font-size: 1rem !important;
    }
    
    /* Fix metric labels and values */
    [data-testid="metric-container"] {
        color: #f8fafc !important;
    }
    
    [data-testid="metric-container"] > div {
        color: #f8fafc !important;
    }
    
    /* Tabs styling */
    .stTabs [data-baseweb="tab-list"] {
        background: rgba(15, 23, 42, 0.6) !important;
        border-radius: 12px !important;
        padding: 0.5rem !important;
    }
    
    .stTabs [data-baseweb="tab"] {
        background: transparent !important;
        color: #cbd5e1 !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
    }
    
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #3b82f6, #8b5cf6) !important;
        color: white !important;
    }
    
    /* Info and success boxes */
    .stInfo {
        background: rgba(59, 130, 246, 0.1) !important;
        border: 1px solid rgba(59, 130, 246, 0.3) !important;
        border-radius: 12px !important;
        color: #dbeafe !important;
    }
    
    .stSuccess {
        background: rgba(34, 197, 94, 0.1) !important;
        border: 1px solid rgba(34, 197, 94, 0.3) !important;
        border-radius: 12px !important;
        color: #dcfce7 !important;
    }
    
    .stError {
        background: rgba(239, 68, 68, 0.1) !important;
        border: 1px solid rgba(239, 68, 68, 0.3) !important;
        border-radius: 12px !important;
        color: #fecaca !important;
    }
    </style>
    """, unsafe_allow_html=True)

def show_login_page():
    load_custom_css()
    
    # Custom login container
    st.markdown("""
    <div class="custom-header">
        <h1>🏢 InventoryPro</h1>
        <p>Professional Inventory Management System</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("""
        <div class="login-container">
            <div class="login-header">
                <h2 class="login-title">Welcome</h2>
                <p class="login-subtitle">Access your personal inventory system</p>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        tab1, tab2 = st.tabs(["🔐 Sign In", "📝 Create Account"])
        
        with tab1:
            st.info("📱 Demo Login: Phone: 'admin' | Password: 'admin123'")
            
            with st.form("login_form"):
                phone = st.text_input("📞 Phone Number", placeholder="Enter your phone number")
                password = st.text_input("🔒 Password", type="password", placeholder="Enter your password")
                login_btn = st.form_submit_button("🚀 Sign In", use_container_width=True)
                
                if login_btn:
                    if phone and password:
                        user = login_user(phone, password)
                        if user:
                            st.session_state.user = user
                            # Initialize user database if it doesn't exist
                            try:
                                get_suppliers(user['id'])
                            except:
                                init_user_database(user['id'])
                            st.success("✅ Welcome back!")
                            st.rerun()
                        else:
                            st.error("❌ Invalid credentials!")
                    else:
                        st.error("⚠️ Please fill all fields!")
        
        with tab2:
            with st.form("register_form"):
                name = st.text_input("👤 Full Name", placeholder="Enter your full name")
                phone = st.text_input("📞 Phone Number", placeholder="Enter your phone number")
                password = st.text_input("🔒 Password", type="password", placeholder="Create a password")
                register_btn = st.form_submit_button("✨ Create Account", use_container_width=True)
                
                if register_btn:
                    if name and phone and password:
                        user_id = register_user(name, phone, password)
                        if user_id:
                            st.success("🎉 Account created! You get your own private database. Please sign in.")
                        else:
                            st.error("❌ Phone number already exists!")
                    else:
                        st.error("⚠️ Please fill all fields!")

def show_navigation():
    st.markdown(f"""
    <div class="custom-header">
        <h1>🏢 Welcome Back, {st.session_state.user['name']}!</h1>
        <p>Your Personal Inventory Management Dashboard</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown('<div class="nav-container">', unsafe_allow_html=True)
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    navigation_items = [
        ("📊", "Dashboard", "Analytics & Overview", "dashboard"),
        ("➕", "Add Product", "Add New Items", "add_product"),
        ("🏢", "Suppliers", "Manage Suppliers", "suppliers"),
        ("⚠️", "Alerts", "Stock Warnings", "alerts"),
        ("📱", "WhatsApp", "Message Templates", "whatsapp_templates")
    ]
    
    selected_page = None
    
    for i, (icon, title, desc, key) in enumerate(navigation_items):
        with [col1, col2, col3, col4, col5][i]:
            if st.button(f"{title}", key=f"nav_{key}", use_container_width=True, help=f"Go to {title}"):
                selected_page = key
    
    st.markdown('</div>', unsafe_allow_html=True)
    return selected_page

# Streamlit UI
def main():
    st.set_page_config(
        page_title="InventoryPro", 
        page_icon="🏢", 
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    
    # Initialize main database
    init_main_database()
    
    # Session state initialization
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'current_page' not in st.session_state:
        st.session_state.current_page = "dashboard"
    
    # Authentication
    if st.session_state.user is None:
        show_login_page()
    else:
        load_custom_css()
        
        # Header with logout
        col1, col2 = st.columns([4, 1])
        with col2:
            if st.button("🚪 Logout", type="secondary"):
                st.session_state.user = None
                st.session_state.current_page = "dashboard"
                st.rerun()
        
        # Navigation
        selected_page = show_navigation()
        if selected_page:
            st.session_state.current_page = selected_page
            st.rerun()
        
        # Ensure user database is properly initialized
        user_id = st.session_state.user['id']
        try:
            # Test if WhatsApp templates table exists
            get_whatsapp_templates(user_id)
        except:
            # If not, initialize it
            init_whatsapp_templates(user_id)
        
        # Show current page
        if st.session_state.current_page == "dashboard":
            show_dashboard()
        elif st.session_state.current_page == "add_product":
            show_add_product()
        elif st.session_state.current_page == "suppliers":
            show_manage_suppliers()
        elif st.session_state.current_page == "alerts":
            show_low_stock_alerts()
        elif st.session_state.current_page == "whatsapp_templates":
            show_whatsapp_templates()

def show_dashboard():
    st.markdown("""
    <div class="page-header">
        <h2 class="page-title">📊 Dashboard Overview</h2>
        <p class="page-subtitle">Monitor your inventory performance and metrics</p>
    </div>
    """, unsafe_allow_html=True)
    
    user_id = st.session_state.user['id']
    
    # Get data
    products = get_products(user_id)
    low_stock = get_low_stock_products(user_id)
    suppliers = get_suppliers(user_id)
    
    # Metrics row
    st.markdown('<div class="metrics-grid">', unsafe_allow_html=True)
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{len(products)}</div>
            <div class="metric-label">📦 Total Products</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        total_value = sum([float(p[5]) * p[3] for p in products if p[5]]) if products else 0
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">₹{total_value:,.0f}</div>
            <div class="metric-label">💰 Inventory Value</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{len(low_stock)}</div>
            <div class="metric-label">⚠️ Low Stock Items</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{len(suppliers)}</div>
            <div class="metric-label">🏢 Active Suppliers</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    if products:
        col1, col2 = st.columns(2)
        
        with col1:
            # Stock levels chart
            df = pd.DataFrame(products, columns=['id', 'name', 'supplier', 'quantity', 'min_threshold', 'unit_price', 'category', 'description', 'supplier_contact'])
            fig = px.bar(df.head(8), x='name', y='quantity', title="📊 Stock Levels by Product",
                        color='quantity', color_continuous_scale='Blues')
            fig.update_layout(
                plot_bgcolor='white',
                paper_bgcolor='white',
                font_family="Inter",
                title_font_size=18,
                xaxis_tickangle=-45,
                showlegend=False
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Category distribution
            if df['category'].notna().any():
                category_counts = df['category'].value_counts()
                fig = px.pie(values=category_counts.values, names=category_counts.index, 
                           title="📈 Products by Category")
                fig.update_layout(
                    plot_bgcolor='white',
                    paper_bgcolor='white',
                    font_family="Inter",
                    title_font_size=18,
                    showlegend=True
                )
                st.plotly_chart(fig, use_container_width=True)
    
    # Quick inventory management
    st.markdown("""
    <div class="page-header">
        <h3 class="page-title">🔄 Quick Inventory Updates</h3>
        <p class="page-subtitle">Update stock levels for your products</p>
    </div>
    """, unsafe_allow_html=True)
    
    if products:
        st.markdown('<div class="product-grid">', unsafe_allow_html=True)
        
        for product in products[:6]:  # Show first 6 products
            stock_status = "stock-low" if product[3] <= product[4] else "stock-good"
            status_text = "🔴 Low Stock" if product[3] <= product[4] else "✅ In Stock"
            
            col1, col2, col3 = st.columns([3, 1, 1])
            
            with col1:
                st.markdown(f"""
                <div class="product-card">
                    <div class="product-name">{product[1]}</div>
                    <div class="product-supplier">Supplier: {product[2] or 'N/A'}</div>
                    <span class="stock-status {stock_status}">{status_text}</span>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                st.metric("Current Stock", product[3])
            
            with col3:
                new_qty = st.number_input("Update", min_value=0, value=product[3], key=f"qty_{product[0]}")
                if st.button("💾", key=f"update_{product[0]}", help="Update quantity"):
                    if new_qty != product[3]:
                        action = "INCREASE" if new_qty > product[3] else "DECREASE"
                        update_product_quantity(product[0], new_qty, user_id, action)
                        st.success(f"Updated {product[1]}")
                        st.rerun()
        
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("📦 No products yet. Add your first product to get started!")

def show_add_product():
    st.markdown("""
    <div class="page-header">
        <h2 class="page-title">➕ Add New Product</h2>
        <p class="page-subtitle">Add items to your inventory system</p>
    </div>
    """, unsafe_allow_html=True)
    
    user_id = st.session_state.user['id']
    suppliers = get_suppliers(user_id)
    
    if not suppliers:
        st.markdown("""
        <div class="alert-card">
            <h3>⚠️ No Suppliers Found</h3>
            <p>Please add suppliers first before adding products!</p>
        </div>
        """, unsafe_allow_html=True)
        return
    
    with st.form("add_product_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            name = st.text_input("📦 Product Name", placeholder="Enter product name")
            supplier_options = {f"{s[1]} ({s[2]})": s[0] for s in suppliers}
            selected_supplier = st.selectbox("🏢 Supplier", options=list(supplier_options.keys()))
            quantity = st.number_input("📊 Initial Quantity", min_value=0, value=0)
            min_threshold = st.number_input("⚠️ Minimum Threshold", min_value=1, value=10)
        
        with col2:
            unit_price = st.number_input("💰 Unit Price (₹)", min_value=0.0, value=0.0, step=0.01)
            category = st.text_input("🏷️ Category", placeholder="e.g., Electronics, Food, etc.")
            description = st.text_area("📝 Description", placeholder="Product description...")
        
        submitted = st.form_submit_button("✨ Add Product", use_container_width=True)
        
        if submitted and name and selected_supplier:
            supplier_id = supplier_options[selected_supplier]
            product_id = add_product(name, supplier_id, quantity, min_threshold, unit_price, category, description, user_id)
            if product_id:
                st.success(f"🎉 Product '{name}' added successfully!")
                st.rerun()

def show_manage_suppliers():
    st.markdown("""
    <div class="page-header">
        <h2 class="page-title">🏢 Supplier Management</h2>
        <p class="page-subtitle">Manage your supplier relationships</p>
    </div>
    """, unsafe_allow_html=True)
    
    user_id = st.session_state.user['id']
    
    tab1, tab2 = st.tabs(["➕ Add Supplier", "📋 Manage Existing"])
    
    with tab1:
        with st.form("add_supplier_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            
            with col1:
                name = st.text_input("🏢 Supplier Name", placeholder="Enter supplier name")
                contact_number = st.text_input("📞 Contact Number", placeholder="+1234567890")
            
            with col2:
                email = st.text_input("📧 Email", placeholder="supplier@email.com")
                address = st.text_area("📍 Address", placeholder="Full address...")
            
            submitted = st.form_submit_button("✨ Add Supplier", use_container_width=True)
            
            if submitted and name and contact_number:
                supplier_id = add_supplier(name, contact_number, email, address, user_id)
                if supplier_id:
                    st.success(f"🎉 Supplier '{name}' added successfully!")
                    st.rerun()
    
    with tab2:
        suppliers = get_suppliers(user_id)
        
        if suppliers:
            for supplier in suppliers:
                with st.expander(f"🏢 {supplier[1]} - {supplier[2]}", expanded=False):
                    col1, col2, col3 = st.columns([2, 2, 1])
                    
                    with col1:
                        st.write(f"**📞 Contact:** {supplier[2]}")
                        st.write(f"**📧 Email:** {supplier[3] or 'N/A'}")
                    
                    with col2:
                        st.write(f"**📍 Address:** {supplier[4] or 'N/A'}")
                    
                    with col3:
                        if st.button("🗑️ Delete", key=f"del_supplier_{supplier[0]}", type="secondary"):
                            delete_supplier(supplier[0], user_id)
                            st.success("Supplier deleted!")
                            st.rerun()
        else:
            st.info("No suppliers found. Add your first supplier!")

def show_low_stock_alerts():
    st.markdown("""
    <div class="page-header">
        <h2 class="page-title">⚠️ Low Stock Alerts</h2>
        <p class="page-subtitle">Monitor and reorder low stock items</p>
    </div>
    """, unsafe_allow_html=True)
    
    user_id = st.session_state.user['id']
    low_stock = get_low_stock_products(user_id)
    
    if not low_stock:
        st.markdown("""
        <div class="success-card">
            <h3>🎉 All Good!</h3>
            <p>All products are well stocked. No alerts at this time.</p>
        </div>
        """, unsafe_allow_html=True)
        return
    
    st.markdown(f"""
    <div class="alert-card">
        <h3>⚠️ Attention Needed</h3>
        <p>You have <strong>{len(low_stock)}</strong> products running low on stock!</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Smart WhatsApp Composer
    st.markdown("""
    <div class="page-header">
        <h3 class="page-title">📱 Smart WhatsApp Message Composer</h3>
        <p class="page-subtitle">Compose messages with supplier and product selection</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Get all suppliers with low stock items
    suppliers = get_suppliers(user_id)
    supplier_options = {}
    for supplier in suppliers:
        # Check if this supplier has low stock items
        supplier_low_stock = [item for item in low_stock if item[2] == supplier[1]]
        if supplier_low_stock:
            supplier_options[f"{supplier[1]} ({supplier[2]})"] = {
                'id': supplier[0],
                'name': supplier[1],
                'contact': supplier[2],
                'items': supplier_low_stock
            }
    
    if supplier_options:
        col1, col2 = st.columns([1, 1])
        
        with col1:
            selected_supplier_key = st.selectbox(
                "🏢 Select Supplier",
                options=list(supplier_options.keys()),
                help="Choose supplier to send message to"
            )
            
            selected_supplier = supplier_options[selected_supplier_key]
            
            # Template selection
            templates = get_whatsapp_templates(user_id)
            template_options = {f"{t[1]} {'(Default)' if t[3] else ''}": t for t in templates}
            selected_template_name = st.selectbox(
                "📋 Message Template",
                options=list(template_options.keys())
            )
            selected_template = template_options[selected_template_name]
        
        with col2:
            company_name = st.text_input(
                "🏪 Company Name",
                value="Inventory Management Team"
            )
        
        st.markdown("### 📦 Select Items to Reorder")
        
        # Items selection with quantities
        selected_items = []
        for item in selected_supplier['items']:
            col1, col2, col3, col4, col5, col6 = st.columns([0.5, 2, 1, 1, 1, 1.5])
            
            with col1:
                include = st.checkbox("", key=f"include_{item[0]}", value=True)
            
            with col2:
                st.markdown(f"**{item[1]}**")
            
            with col3:
                st.metric("Current", item[3])
            
            with col4:
                st.metric("Min", item[4])
            
            with col5:
                suggested = max(1, item[4] * 2 - item[3])
                st.metric("Suggested", f"+{suggested}")
            
            with col6:
                if include:
                    quantity = st.number_input(
                        "Order Qty",
                        min_value=1,
                        value=suggested,
                        key=f"order_qty_{item[0]}"
                    )
                    selected_items.append({
                        'name': item[1],
                        'quantity': quantity,
                        'current_stock': item[3]
                    })
        
        if selected_items:
            st.markdown("---")
            
            # Message preview
            preview_message = selected_template[2].replace("{supplier_name}", selected_supplier['name'])
            items_list = ""
            for item_data in selected_items:
                items_list += f"• {item_data['name']}: {item_data['quantity']} units (Current stock: {item_data['current_stock']})\n"
            preview_message = preview_message.replace("{items_list}", items_list.strip())
            preview_message = preview_message.replace("{company_name}", company_name)
            
            with st.expander("📋 Message Preview", expanded=True):
                st.text_area("Preview", value=preview_message, height=200, disabled=True)
            
            # Send button
            whatsapp_url = generate_whatsapp_message(
                selected_supplier['name'], 
                selected_supplier['contact'], 
                selected_items, 
                selected_template[2], 
                company_name
            )
            
            col1, col2, col3 = st.columns([1, 1, 1])
            with col2:
                st.markdown(f"""
                <div style="text-align: center; margin: 1rem 0;">
                    <a href="{whatsapp_url}" target="_blank" style="
                        display: inline-block;
                        background: linear-gradient(135deg, #25D366, #128C7E);
                        color: white;
                        padding: 1rem 2rem;
                        border-radius: 12px;
                        text-decoration: none;
                        font-weight: 700;
                        font-size: 1.1rem;
                        box-shadow: 0 10px 25px rgba(37, 211, 102, 0.3);
                        transition: all 0.3s ease;
                        text-transform: uppercase;
                        letter-spacing: 0.5px;
                    " onmouseover="this.style.transform='translateY(-2px)'; this.style.boxShadow='0 15px 35px rgba(37, 211, 102, 0.4)';" 
                       onmouseout="this.style.transform='translateY(0px)'; this.style.boxShadow='0 10px 25px rgba(37, 211, 102, 0.3)';">
                        📱 Send to {selected_supplier['name']}
                    </a>
                </div>
                """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Traditional view for reference
    st.markdown("### 📊 Low Stock Items by Supplier")
    
    # Group by supplier
    supplier_groups = {}
    for item in low_stock:
        supplier = item[2] or "Unknown Supplier"
        if supplier not in supplier_groups:
            supplier_groups[supplier] = []
        supplier_groups[supplier].append(item)
    
    for supplier_name, items in supplier_groups.items():
        with st.expander(f"🏢 {supplier_name} ({len(items)} items)", expanded=False):
            for item in items:
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.write(f"📦 **{item[1]}**")
                with col2:
                    st.metric("Current", item[3])
                with col3:
                    st.metric("Minimum", item[4])

def show_whatsapp_templates():
    st.markdown("""
    <div class="page-header">
        <h2 class="page-title">📱 WhatsApp Message Templates</h2>
        <p class="page-subtitle">Create and manage your message templates for supplier communication</p>
    </div>
    """, unsafe_allow_html=True)
    
    user_id = st.session_state.user['id']
    
    # Ensure templates table exists
    try:
        templates = get_whatsapp_templates(user_id)
    except:
        # If table doesn't exist, create it
        init_whatsapp_templates(user_id)
        templates = get_whatsapp_templates(user_id)
    
    tab1, tab2 = st.tabs(["📝 Create Template", "📋 Manage Templates"])
    
    with tab1:
        st.markdown("### ✨ Create New Template")
        
        with st.form("create_template_form", clear_on_submit=True):
            template_name = st.text_input("📌 Template Name", placeholder="e.g., Urgent Reorder, Monthly Order")
            
            st.markdown("**Available Placeholders:**")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.info("🏢 **{supplier_name}** - Supplier's name")
            with col2:
                st.info("📦 **{items_list}** - List of items to order")
            with col3:
                st.info("🏪 **{company_name}** - Your company name")
            
            template_text = st.text_area(
                "📝 Message Template",
                placeholder="""Hello {supplier_name},

We need to reorder the following items:

{items_list}

Please confirm availability and pricing in ₹.

Best regards,
{company_name}""",
                height=200
            )
            
            # Preview section
            if template_text:
                st.markdown("### 👀 Preview")
                preview = template_text.replace("{supplier_name}", "ABC Supplies")
                preview = preview.replace("{items_list}", "• Product A: 50 units (Current stock: 5)\n• Product B: 30 units (Current stock: 2)")
                preview = preview.replace("{company_name}", "Your Company")
                
                st.text_area("Preview", value=preview, height=150, disabled=True)
            
            submitted = st.form_submit_button("💾 Save Template", use_container_width=True)
            
            if submitted and template_name and template_text:
                template_id = add_whatsapp_template(template_name, template_text, user_id)
                if template_id:
                    st.success(f"🎉 Template '{template_name}' created successfully!")
                    st.rerun()
    
    with tab2:
        st.markdown("### 📚 Your Templates")
        
        if templates:
            for template in templates:
                with st.expander(f"{'⭐' if template[3] else '📝'} {template[1]}", expanded=False):
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        if template[3]:  # Default template - read only
                            st.text_area("Template Content", value=template[2], height=150, disabled=True, key=f"template_view_{template[0]}")
                        else:
                            # Editable template
                            if f"edit_mode_{template[0]}" not in st.session_state:
                                st.session_state[f"edit_mode_{template[0]}"] = False
                            
                            if not st.session_state[f"edit_mode_{template[0]}"]:
                                st.text_area("Template Content", value=template[2], height=150, disabled=True, key=f"template_view_{template[0]}")
                            else:
                                # Edit form
                                with st.form(f"edit_template_{template[0]}"):
                                    new_name = st.text_input("Template Name", value=template[1], key=f"edit_name_{template[0]}")
                                    new_content = st.text_area("Template Content", value=template[2], height=150, key=f"edit_content_{template[0]}")
                                    
                                    col_save, col_cancel = st.columns(2)
                                    with col_save:
                                        save_btn = st.form_submit_button("💾 Save Changes", use_container_width=True)
                                    with col_cancel:
                                        cancel_btn = st.form_submit_button("❌ Cancel", use_container_width=True)
                                    
                                    if save_btn and new_name and new_content:
                                        update_whatsapp_template(template[0], new_name, new_content, user_id)
                                        st.session_state[f"edit_mode_{template[0]}"] = False
                                        st.success("Template updated!")
                                        st.rerun()
                                    
                                    if cancel_btn:
                                        st.session_state[f"edit_mode_{template[0]}"] = False
                                        st.rerun()
                    
                    with col2:
                        if template[3]:  # Default template
                            st.info("⭐ Default Template\n(Cannot be modified)")
                        else:
                            st.markdown("**Actions:**")
                            
                            if not st.session_state.get(f"edit_mode_{template[0]}", False):
                                if st.button("✏️ Edit", key=f"edit_template_{template[0]}", use_container_width=True):
                                    st.session_state[f"edit_mode_{template[0]}"] = True
                                    st.rerun()
                            
                            if st.button("🗑️ Delete", key=f"delete_template_{template[0]}", type="secondary", use_container_width=True):
                                delete_whatsapp_template(template[0], user_id)
                                st.success("Template deleted!")
                                st.rerun()
        else:
            st.info("No custom templates found. Create your first template above!")

if __name__ == "__main__":
    main()
