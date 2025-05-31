from flask import Flask, request, jsonify, send_from_directory
import jwt
import datetime
from pymongo import MongoClient
from functools import wraps
from typing import Callable, Any

from config import MONGO_URI, SECRET_KEY
from models.user import create_users, find_user, verify_password

app = Flask(__name__)
app.config["MONGO_URI"] = MONGO_URI
app.config["SECRET_KEY"] = SECRET_KEY

client = MongoClient(app.config["MONGO_URI"])
db = client.get_database()
users = db.users # db collection to store all the users
products = db.products # creating a new db collection to store the products
orders = db.orders # new db to store all orders

@app.route('/')
def home():
    return app.send_static_file('index.html')

@app.route('/<path:path>')
def static_proxy(path):
    return app.send_static_file(path)


# register
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    username = data.get("username")
    password = data.get("password")
    role = data.get("role")
    cart = data.get("cart")

    if not username or not password:
        return jsonify({"message": "Username and password required"}), 400
    
    if find_user(users, username):
        return jsonify({"message": "User already exists"}), 400
    
    create_users(users, username, password, role, cart)
    return jsonify({"message": "User created"}), 201

# login
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"message": "Username and password required"}), 400
    
    user = find_user(users, username)
    if not user:
        return jsonify({"message": "User does not exist"}), 401

    if verify_password(password, user['password']):
        payload = {
            "username": username,
            "role":user['role'],
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        }
        token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')
        return jsonify({"token": token})
    
    return jsonify({"message": "Invalid credentials"}), 401

# profile access
@app.route('/profile')
def profile():
    token = request.headers.get("Authorization")
    if not token or not token.startswith("Bearer "):
        return jsonify({"message": "Token required"}), 401
    
    token = token.split(" ")[1]

    try:
        decoded = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        return jsonify({"message": f"Welcome {decoded['username']}!"})
    except jwt.ExpiredSignatureError:
        return jsonify({"message": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"message": "Invalid token"}), 401

# admin role required checker
def admin_role_required(func: Callable) -> Any:
    @wraps(func)
    def decorated(*args, **kwargs) -> Any:
        token = request.headers.get('Authorization')
        if token.startswith("Bearer "):
            token = token.split(' ')[1]
        
        if not token:
            return jsonify({"message":"token is missing"}), 401

        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
            current_user = data['username']
            if data.get('role') != 'admin':
                return jsonify({"message":"Admin role required"}), 403
        except jwt.ExpiredSignatureError:
            return jsonify({"message":"Token expired. Login required"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"message":"Invalid token"}), 401

        return func(current_user, *args, **kwargs)
    
    return decorated
            
# adding a new product
@app.route('/add_product', methods=['POST'])
@admin_role_required
def add_product(username):
    print(f"Welcome {username}, you have the access to the admin panel")
    data = request.get_json()
    name = data.get("name")
    price = data.get("price")
    description = data.get("description")
    image_url = data.get("image_url")

    if not name or not price or not description:
        return jsonify({"message":"Name, price, and description required."}), 401

    products.insert_one({
        "name":name,
        "price":price,
        "description":description,
        "image_url": image_url,
        "added_by":username
    })
    return jsonify({"message":"Product added successfully"}), 200

@app.route('/list_products', methods=["GET"])
def get_all_products():
    return jsonify(list(products.find({}, {"_id":0}))), 200

@app.route("/delete_product", methods=["DELETE"])
@admin_role_required
def delete_product(username):
    data = request.json
    name = data.get('name')

    if not name:
        return jsonify({"message":"Name is required to delete"}), 400
    
    result = products.delete_one({"name":name})

    if result.deleted_count == 0:
        return jsonify({"message":"Product not found"}), 404

    return jsonify({"message":f"Product '{name}' deleted by {username}"}), 200

@app.route('/product', methods=["GET"])
def product():
    data = request.json
    name = data.get('name')

    if not name:
        return jsonify({"message":"Product name required"}), 401
    
    product = products.find_one({"name":name})

    return jsonify({"message":f"here is the product:\n{product}"})

@app.route('/update_product/<product_name>', methods=['PUT'])
@admin_role_required
def update_product(username, product_name):
    data = request.json


    update_fields = {}
    if "name" in data:
        update_fields["name"] = data["name"]

    if "price" in data:
        update_fields["price"] = data["price"]

    if "description" in data:
        update_fields["description"] = data["description"]

    if not update_fields:
        return jsonify({"message":"No update fields provided"}), 400
    
    results = products.update_one(
        {"name":product_name},
        {"$set": update_fields}
    )

    if results.matched_count == 0:
        return jsonify({"messge":"Product not found"}), 404
    
    return jsonify({"message":f"Product {product_name} was updated successfully by {username}"}), 200


def token_required(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"message": "Token is missing or invalid"}), 401
        
        token = auth_header.split(' ')[1]

        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
            current_user = data.get('username')
            if not current_user:
                return jsonify({"message": "Invalid token payload"}), 401
            

        except jwt.ExpiredSignatureError:
            return jsonify({"message": "Token expired. Login required"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"message": "Invalid token"}), 401

        return func(current_user, *args, **kwargs)

    return decorated

@app.route('/add_to_cart/<product_name>', methods=['PUT'])
@token_required
def add_to_cart(current_user, product_name):
    user = users.find_one({'username': current_user})
    product = products.find_one({'name': product_name})

    if not product:
        return jsonify({"message": "Product not found"}), 404

    if not user:
        return jsonify({"message": "User not found"}), 404

    if 'cart' not in user:
        user['cart'] = []

    if any(p.get('name') == product_name for p in user.get('cart', [])):
        return jsonify({"message": "Product already in cart"}), 400

    users.update_one(
        {'username': current_user},
        {'$push': {'cart': product}}
    )

    return jsonify({"message": "Product added to cart"}), 200



@app.route('/place_order', methods=["POST"])
@token_required
def place_order(current_user):
    data = request.json
    product_name = data.get("product_name")
    phone_number = data.get("phone_number")
    address = data.get("address")
    state = data.get("state")
    country = data.get("country")

    if not all([product_name, phone_number, address, state, country]):
        return jsonify({"message": "All fields are required"}), 400

    user = users.find_one({'username': current_user})
    product = products.find_one({'name': product_name})

    if not user:
        return jsonify({"message": "User not found"}), 404
    if not product:
        return jsonify({"message": "Product not found"}), 404

    order_data = {
        "username": current_user,
        "product_name": product_name,
        "phone_number": phone_number,
        "address": address,
        "state": state,
        "country": country,
        "ordered_at": datetime.datetime.utcnow()
    }

    orders.insert_one(order_data)

    return jsonify({"message": "Order placed successfully!"}), 201


@app.route('/view_cart', methods=['GET'])
@token_required
def view_cart(current_user):
    user = users.find_one({'username': current_user}, {"_id": 0, "cart": 1})
    if not user:
        return jsonify({"message": "User not found"}), 404
    cart = user.get('cart', [])  
    return jsonify({"cart": cart}), 200

if __name__ == "__main__":
    app.run(debug=True)
