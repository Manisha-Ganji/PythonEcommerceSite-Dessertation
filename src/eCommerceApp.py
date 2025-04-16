from flask import Flask, render_template, request, redirect, url_for, session
import psycopg2 
import os
import boto3
import logging
from datetime import timedelta

# Initialize the Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)

# Secret key for session management (ensure this is secure in production)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))  # Secure key from environment or fallback to random
s3_bucket_name = "ecommerce-product-images-primary"

# Connect to the RDS database
def connect_db():
    try:
        return psycopg2.connect(
        host="ecommappdbprimary.cp8u60euuktu.us-east-1.rds.amazonaws.com",
        user="postgres",
        password="SanMan2020",
        dbname="postgres"
    )
    except psycopg2.Error as e:
        logging.error(f"Error connecting to database: {e}")
        raise e

# Home page - Display products
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
        if 'cart' not in session:
            session['cart'] = []

        try:
            price = float(product[2])
        except ValueError:
            price = 0.0  # Default value if price is invalid
        
        session['cart'].append({
            'id': product[0],
            'name': product[1],
            'price': price
        })

        session.modified = True
        logging.info(f"Added {product[1]} to cart.")
        return redirect(url_for('home'))
    
    logging.error(f"Product with ID {product_id} not found.")
    return "Product not found!", 404

# Checkout page
@app.route('/checkout')
def checkout():
    cart = session.get('cart', [])
    
    if not cart:
        return render_template('empty_cart.html')  # Or redirect to a message page

    total_price = sum(float(item['price']) for item in cart)
    logging.info(f"Cart total price: ${total_price:.2f}")
    
    return render_template('checkout.html', cart=cart, total_price=total_price)

# Order submission (simple demo)
@app.route('/submit_order', methods=['POST'])
def submit_order():
    customer_name = request.form.get('customer_name', '').strip()
    total_price = float(request.form.get('total_price', 0.0))

    if not customer_name:
        logging.error("Customer name is missing.")
        return redirect(url_for('checkout'))  # Redirect or show an error message
    
    if total_price <= 0:
        logging.error(f"Invalid total price: {total_price}")
        return redirect(url_for('checkout'))  # Redirect or show an error message

    conn = connect_db()
    cursor = conn.cursor()

    # Insert order into database
    cursor.execute("INSERT INTO orders (customer_name, total_price) VALUES (%s, %s)", (customer_name, total_price))
    conn.commit()
    cursor.close()
    conn.close()

    logging.info(f"Order submitted for customer: {customer_name} with total price: ${total_price:.2f}")

    # Clear the cart after order submission
    session.pop('cart', None)

    return redirect(url_for('home'))

# Route to show product images from S3
@app.route('/product_image/<string:image_name>')
def product_image(image_name):
    try:
        s3 = boto3.client('s3')
        file_url = s3.generate_presigned_url('get_object',
                                            Params={'Bucket': s3_bucket_name, 'Key': image_name},
                                            ExpiresIn=3600)  # 1 hour expiration
        logging.info(f"Generated presigned URL for image: {image_name}")
        return redirect(file_url)
    except boto3.exceptions.S3UploadFailedError as e:
        logging.error(f"Failed to generate presigned URL for {image_name}: {e}")
        return "Error loading image", 500
    except Exception as e:
        logging.error(f"Unexpected error generating URL: {e}")
        return "Error loading image", 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=80)
