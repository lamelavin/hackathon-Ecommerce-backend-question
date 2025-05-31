from werkzeug.security import generate_password_hash, check_password_hash

def create_users(users_collection, username, password, role="user", cart=[]):
    hashed_pw = generate_password_hash(password)
    users_collection.insert_one({"username": username, "password": hashed_pw, "role":role})

def find_user(users_collection, username):
    return users_collection.find_one({"username": username})

def verify_password(password, hashed_pw):
    return check_password_hash(hashed_pw, password)
