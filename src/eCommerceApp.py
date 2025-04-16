from flask import Flask, render_template, request, redirect, url_for, session
import psycopg2 
import os
import boto3

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Set secret key for session

# db_host = "ecommappdbprimary.cp8u60euuktu.us-east-1.rds.amazonaws.com"
# db_user = "postgres"
# db_password = "SanMan2020"
# db_name = "postgres"
# s3_bucket_name = "ecommerce-product-images-primary"

# Connect to the RDS database
def connect_db():
        # print(f"Connecting to DB: host={db_host}, dbname={db_name}, user={db_user}")  # Debugging
        return psycopg2.connect(
        host="ecommappdbprimary.cp8u60euuktu.us-east-1.rds.amazonaws.com",
        user="postgres",
        password="SanMan2020",
        dbname="postgres"
    )

# Home page
@app.route('/')
def home():
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price,image_name FROM products")
    products = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('index.html', products=products)

# Add to cart
@app.route('/add_to_cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if product:
        # Check if the cart exists in the session
        if 'cart' not in session:
            session['cart'] = []

        # Add the product to the cart in the session
        session['cart'].append({
            'id': product[0],
            'name': product[1],
            'price': product[2]
        })

        session.modified = True  # Mark the session as modified
        return redirect(url_for('home'))
    return "Product not found!", 404

# Checkout page
@app.route('/checkout')
def checkout():
    # Get the cart from the session
    cart = session.get('cart', [])
    total_price = sum(item['price'] for item in cart)
    
    return render_template('checkout.html', cart=cart, total_price=total_price)

# Order submission (simple demo)
@app.route('/submit_order', methods=['POST'])
def submit_order():
    # Simulate order creation
    conn = connect_db()
    cursor = conn.cursor()
    
    # Get customer name and total price
    customer_name = request.form.get('customer_name', 'John Doe')  # You could collect name through form
    total_price = float(request.form.get('total_price', 0.0))
    
    # Insert the order into the orders table
    cursor.execute("INSERT INTO orders (customer_name, total_price) VALUES (%s, %s)", (customer_name, total_price))
    conn.commit()
    cursor.close()
    conn.close()

    # Clear the cart after the order is submitted
    session.pop('cart', None)

    return redirect(url_for('home'))  # Redirect to home after order submission

# Route to show product images from S3
# @app.route('/product_image/<string:image_name>')
# def product_image(image_name):
#     s3 = boto3.client('s3')
#     file_url = s3.generate_presigned_url('get_object',
#                                         Params={'Bucket': s3_bucket_name, 'Key': image_name},
#                                         ExpiresIn=3600)  # 1 hour expiration
#     return redirect(file_url)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=80)
