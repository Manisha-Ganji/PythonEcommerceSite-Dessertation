from flask import Flask, render_template, request, redirect, url_for, session
import psycopg2
import os
import boto3
import logging
from datetime import timedelta
import requests

# Initialize the Flask app
app = Flask(__name__)

# Configure logging
LOG_FILE = '/home/ec2-user/flask-app.log'
logging.basicConfig(
    level=logging.INFO,
     format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()  # still sends to console/systemd
    ]
    )

# Secret key for session management (ensure this is secure in production)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))  # Secure key from environment or fallback to random

def get_region():
    try:
        # Step 1: Get IMDSv2 token
        token_response = requests.put(
            "http://169.254.169.254/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            timeout=2
        )
        token = token_response.text

        # Step 2: Use token to fetch availability zone
        az_response = requests.get(
            "http://169.254.169.254/latest/meta-data/placement/availability-zone",
            headers={"X-aws-ec2-metadata-token": token},
            timeout=2
        )
        az = az_response.text
        region = az[:-1]

        logging.info(f"Detected region from EC2 metadata: {region}")
        return region

    except requests.RequestException as e:
        logging.error(f"Error fetching region from EC2 metadata: {e}")
        return None
    
region = get_region()
logging.info(f"Region: {region}")

# Initialize the SSM client based on the current EC2 region
ssm = boto3.client('ssm', region_name=region)

# Fetch region-specific parameters from SSM
dbconn = ssm.get_parameter(Name='/eCommApp/db/active')['Parameter']['Value']
s3_bucket_name = ssm.get_parameter(Name='/eCommApp/s3/active')['Parameter']['Value']

# Parse RDS connection details
dbvalues = dbconn.split(',')

DB_NAME = dbvalues[0]
DB_USER = dbvalues[1]
DB_PASSWORD = dbvalues[2]
DB_HOST = dbvalues[3]
DB_PORT= dbvalues[4]

# Connect to the RDS database
def connect_db():
    try:
        logging.info("Connecting to the database...")
        conn = psycopg2.connect(
            host=DB_HOST,
            port = DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            dbname=DB_NAME
        )
        logging.info("Database connection successful.")
        return conn
    except psycopg2.Error as e:
        logging.error(f"Error connecting to database: {e}")
        raise e

# Home page - Display products
@app.route('/')
def home():
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price, image_name FROM products")
    products = cursor.fetchall()
    cursor.close()
    conn.close()

    # Check if a product was recently added to the cart
    just_added = session.pop('just_added', False)
    last_product = session.pop('last_product', None)

    return render_template('index.html', products=products, just_added=just_added, last_product=last_product)

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

        # Check if product is already in the cart
        product_in_cart = next((item for item in session['cart'] if item['id'] == product[0]), None)

        if product_in_cart:
            # If the product already exists in the cart, increment its quantity and update total price
            product_in_cart['quantity'] += 1
            product_in_cart['price'] += float(product[2])  # Add the price again to update the total
        else:
            # If the product is not in the cart, add it with quantity 1
            session['cart'].append({
                'id': product[0],
                'name': product[1],
                'price': float(product[2]),
                'quantity': 1
            })

        session.modified = True

        # Store session variables for the modal
        session['just_added'] = True
        session['last_product'] = product[1]

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
