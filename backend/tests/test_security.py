def test_hash_and_verify_password():
    from app.core.security import hash_password, verify_password

    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h) is True
    assert verify_password("wrong", h) is False


def test_token_roundtrip_contains_user_id():
    from app.core.security import create_access_token, decode_access_token

    token = create_access_token("abc-123")
    payload = decode_access_token(token)
    assert payload["user_id"] == "abc-123"
