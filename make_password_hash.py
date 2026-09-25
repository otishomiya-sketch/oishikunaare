"""Generate a password hash for the [admins] table in Streamlit Secrets.

Usage:
    python3 make_password_hash.py
"""

import getpass

from auth import MIN_PASSWORD_LENGTH, make_hash

if __name__ == "__main__":
    user_id = input("ID: ").strip()
    password = getpass.getpass("パスワード: ")
    if password != getpass.getpass("パスワード（確認）: "):
        raise SystemExit("パスワードが一致しません。")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"パスワードは{MIN_PASSWORD_LENGTH}文字以上にしてください。")

    print("\n以下の1行を Secrets の [admins] の下に追加してください:\n")
    print(f'{user_id} = "{make_hash(password)}"')
