from flask import Flask, request, jsonify
from flask_cors import CORS
import boto3
import requests
from datetime import datetime
import os

app = Flask(__name__)
CORS(app)

# ---------- AWS CONFIG ----------
dynamodb = boto3.resource('dynamodb', region_name='us-east-2')
users_table = dynamodb.Table('Users')
sessions_table = dynamodb.Table('chatsessions')

# ---------- OPENROUTER CONFIG ----------
OPENROUTER_API_KEY = "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"  # replace with actual key
OPENROUTER_MODEL = "deepseek/deepseek-r1-0528-qwen3-8b:free"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")
    name = data.get("name", "")

    if not email or not password:
        return jsonify(success=False, error="Missing email or password"), 400

    existing = users_table.get_item(Key={"email": email})
    if "Item" in existing:
        return jsonify(success=False, error="Email already exists"), 409

    users_table.put_item(Item={"email": email, "password": password, "name": name})
    return jsonify(success=True, data={"email": email, "name": name}), 201

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify(success=False, error="Missing email or password"), 400

    result = users_table.get_item(Key={"email": email})
    user = result.get("Item")
    if not user or user["password"] != password:
        return jsonify(success=False, error="Invalid credentials"), 401

    return jsonify(success=True, data={"email": email, "name": user.get("name", "")}), 200

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    msg = data.get("message")
    session_id = data.get("sessionId")
    email = data.get("email")

    if not msg or not session_id or not email:
        return jsonify(success=False, error="Missing fields"), 400

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": OPENROUTER_MODEL,
        "stream": False,
        "messages": [{"role": "user", "content": msg}]
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=body, timeout=30)
        ai_reply = response.json()['choices'][0]['message']['content']
    except Exception as e:
        return jsonify(success=False, error="AI response failed"), 500

    # Save user message
    sessions_table.put_item(Item={
        "sessionId": session_id,
        "timestamp": datetime.utcnow().isoformat(),
        "email": email,
        "sender": "user",
        "message": msg
    })

    # Save AI reply
    sessions_table.put_item(Item={
        "sessionId": session_id,
        "timestamp": datetime.utcnow().isoformat(),
        "email": email,
        "sender": "ai",
        "message": ai_reply
    })

    return jsonify(success=True, data={"response": ai_reply}), 200

@app.route("/sessions", methods=["GET"])
def get_sessions():
    email = request.args.get("email")
    if not email:
        return jsonify(success=False, error="Missing email"), 400

    try:
        response = sessions_table.scan()
        items = response.get("Items", [])
        user_items = [i for i in items if i.get("email") == email]
        sessions = {}
        for item in user_items:
            sid = item["sessionId"]
            if sid not in sessions:
                sessions[sid] = []
            sessions[sid].append({
                "timestamp": item["timestamp"],
                "message": item["message"],
                "sender": item["sender"]
            })

        session_list = [{
            "sessionId": sid,
            "timestamp": sorted(v, key=lambda x: x["timestamp"])[0]["timestamp"],
            "messages": sorted(v, key=lambda x: x["timestamp"])
        } for sid, v in sessions.items()]

        return jsonify(success=True, sessions=session_list), 200

    except Exception as e:
        print("Error loading sessions:", e)
        return jsonify(success=False, error="Failed to load sessions"), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)