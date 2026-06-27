import requests
import database

def login_user(user_id, username, password):
    """Logs in a user, saves details to database, and publishes a slack alert."""
    print(f"[Auth] Attempting login for {username}")
    
    # Save the login session in the database
    database.save_user(user_id, username)
    
    # Notify Slack about security access event
    slack_payload = {"text": f"User {username} successfully logged in!"}
    try:
        # Calls external Slack webhook API
        requests.post("https://hooks.slack.com/services/mock_webhook", json=slack_payload)
    except Exception as e:
        print(f"[Auth] Slack notification failed: {e}")
        
    return {"status": "authenticated"}
#as=asadadasdf