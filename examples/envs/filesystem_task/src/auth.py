def authenticate(username: str, password: str) -> bool:
    return bool(username) and bool(password)
