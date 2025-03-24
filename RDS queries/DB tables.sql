CREATE SEQUENCE products_id_seq;

CREATE TABLE products (
    id INT DEFAULT nextval('products_id_seq') PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
	image_name VARCHAR(255) NOT NULL
);

INSERT INTO products (name, price, image_name) 
VALUES ('Cloud Computing', 200.00, 'CloudComputing.jpg'),
       ('Big Data', 150.00, 'BigData.jpg');
	   
CREATE SEQUENCE orders_id_seq;

CREATE TABLE orders (
    id INT DEFAULT nextval('orders_id_seq') PRIMARY KEY,
    customer_name VARCHAR(255),
    total_price DECIMAL(10, 2)
);