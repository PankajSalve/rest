import os
import sqlite3
import json
import io
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file, Response
import qrcode
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = "restaurant_super_secret_key_change_in_prod"

ADMIN_USER = "admin"
ADMIN_PASS = "admin123"

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "restaurant.db")

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=20.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS menu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL NOT NULL,
                description TEXT,
                image_url TEXT,
                is_available INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                table_no TEXT NOT NULL,
                items_json TEXT NOT NULL,
                total_amount REAL NOT NULL,
                status TEXT DEFAULT 'Pending',
                created_at TEXT NOT NULL
            )
        """)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM menu")
        if cur.fetchone()[0] == 0:
            sample_dishes = [
                ("Paneer Butter Masala", "Main Course", 260.0, "Cottage cheese in rich tomato gravy.", "https://images.unsplash.com/photo-1631452180519-c014fe946bc7?w=500", 1),
                ("Veg Biryani", "Rice", 210.0, "Aromatic basmati rice cooked with garden spices.", "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?w=500", 1),
                ("Butter Naan", "Breads", 45.0, "Clay oven flatbread glazed with fresh butter.", "https://images.unsplash.com/photo-1626074353765-517a681e40be?w=500", 1),
                ("Crispy Corn Chilli", "Starters", 180.0, "Fried sweet corn tossed with capsicum and spices.", "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=500", 1),
                ("Mango Lassi", "Beverages", 90.0, "Refreshing thick yogurt shake with mango pulp.", "https://images.unsplash.com/photo-1546173159-315724a31696?w=500", 1),
                ("Cold Coffee", "Beverages", 110.0, "Creamy blended chilled brew topped with cocoa.", "https://images.unsplash.com/photo-1517701550927-30cf4ba1dba5?w=500", 1),
            ]
            conn.executemany("INSERT INTO menu (name, category, price, description, image_url, is_available) VALUES (?, ?, ?, ?, ?, ?)", sample_dishes)
    conn.close()

init_db()

# ----------------- CUSTOMER ROUTES -----------------
@app.route("/")
def home():
    return redirect("/table/T1")

@app.route("/table/<table_no>")
def customer_view(table_no):
    conn = get_db()
    items = conn.execute("SELECT * FROM menu WHERE is_available = 1").fetchall()
    conn.close()
    return render_template("customer.html", table_no=table_no, items=items)

@app.route("/api/order", methods=["POST"])
def place_order():
    data = request.json
    table_no = data.get("table_no", "T1")
    items = data.get("items", [])
    total = data.get("total", 0.0)

    if not items:
        return jsonify({"success": False, "message": "Cart is empty"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    with conn:
        conn.execute("INSERT INTO orders (table_no, items_json, total_amount, status, created_at) VALUES (?, ?, ?, 'Pending', ?)",
                     (table_no, json.dumps(items), total, now))
    conn.close()
    return jsonify({"success": True})

# ----------------- ADMIN ROUTES -----------------
@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        u = request.form.get("username")
        p = request.form.get("password")
        if u == ADMIN_USER and p == ADMIN_PASS:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        return render_template("admin.html", login_error="Invalid username or password")
    
    if session.get("admin"):
        return redirect(url_for("admin_dashboard"))
    return render_template("admin.html", show_login=True)

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    conn = get_db()
    menu = conn.execute("SELECT * FROM menu ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("admin.html", show_dashboard=True, menu=menu)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))

@app.route("/api/admin/orders")
def get_orders():
    if not session.get("admin"):
        return jsonify([]), 403
    conn = get_db()
    orders = conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(ix) for ix in orders])

@app.route("/api/admin/order/<int:order_id>/serve", methods=["POST"])
def mark_served(order_id):
    if not session.get("admin"):
        return jsonify({"success": False}), 403
    conn = get_db()
    with conn:
        conn.execute("UPDATE orders SET status = 'Served' WHERE id = ?", (order_id,))
    conn.close()
    return jsonify({"success": True})

@app.route("/admin/menu/add", methods=["POST"])
def add_menu_item():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    name = request.form.get("name")
    cat = request.form.get("category")
    price = float(request.form.get("price", 0))
    desc = request.form.get("description")
    img = request.form.get("image_url")

    conn = get_db()
    with conn:
        conn.execute("INSERT INTO menu (name, category, price, description, image_url, is_available) VALUES (?, ?, ?, ?, ?, 1)",
                     (name, cat, price, desc, img))
    conn.close()
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/menu/<int:item_id>/toggle")
def toggle_menu_item(item_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    conn = get_db()
    with conn:
        conn.execute("UPDATE menu SET is_available = CASE WHEN is_available=1 THEN 0 ELSE 1 END WHERE id = ?", (item_id,))
    conn.close()
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/menu/<int:item_id>/delete")
def delete_menu_item(item_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM menu WHERE id = ?", (item_id,))
    conn.close()
    return redirect(url_for("admin_dashboard"))

# 80mm PDF Bill Generation
@app.route("/admin/order/<int:order_id>/bill")
def print_bill(order_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    conn = get_db()
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    conn.close()
    if not order:
        return "Order not found", 404

    items = json.loads(order["items_json"])
    total = float(order["total_amount"])
    
    pdf = FPDF(unit="mm", format=(72, 160))
    pdf.set_margins(3, 4, 3)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 5, "GOURMET EXPRESS", ln=True, align="C")
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 4, f"Table: {order['table_no']} | Order #{order['id']}", ln=True, align="C")
    pdf.cell(0, 4, f"{order['created_at']}", ln=True, align="C")
    pdf.cell(0, 3, "--------------------------------------------", ln=True, align="C")

    pdf.set_font("Helvetica", "B", 7)
    pdf.cell(32, 4, "Item", 0, 0, "L")
    pdf.cell(10, 4, "Qty", 0, 0, "C")
    pdf.cell(12, 4, "Rate", 0, 0, "R")
    pdf.cell(12, 4, "Total", 0, 1, "R")
    pdf.cell(0, 2, "--------------------------------------------", ln=True, align="C")

    pdf.set_font("Helvetica", "", 7)
    for it in items:
        pdf.cell(32, 4, it['name'][:18], 0, 0, "L")
        pdf.cell(10, 4, str(it['qty']), 0, 0, "C")
        pdf.cell(12, 4, f"{it['price']:.2f}", 0, 0, "R")
        pdf.cell(12, 4, f"{(it['qty'] * it['price']):.2f}", 0, 1, "R")

    tax = round(total * 0.05, 2)
    pdf.cell(0, 3, "--------------------------------------------", ln=True, align="C")
    pdf.cell(45, 4, "Subtotal:", 0, 0, "R")
    pdf.cell(21, 4, f"INR {total:.2f}", 0, 1, "R")
    pdf.cell(45, 4, "GST (5%):", 0, 0, "R")
    pdf.cell(21, 4, f"INR {tax:.2f}", 0, 1, "R")
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(45, 5, "Grand Total:", 0, 0, "R")
    pdf.cell(21, 5, f"INR {total+tax:.2f}", 0, 1, "R")

    buf = io.BytesIO(bytes(pdf.output()))
    return send_file(buf, download_name=f"bill_{order_id}.pdf", mimetype="application/pdf")

# QR Generator
@app.route("/admin/qr/<table_no>")
def table_qr(table_no):
    base_url = request.host_url.rstrip("/")
    target = f"{base_url}/table/{table_no}"
    qr = qrcode.make(target)
    buf = io.BytesIO()
    qr.save(buf, "PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

if __name__ == "__main__":
    app.run(debug=True, port=5000)