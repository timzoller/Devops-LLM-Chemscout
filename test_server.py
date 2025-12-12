
import requests
import time
import sys

def test_chat():
    url = "http://127.0.0.1:8010/api/chat"
    payload = {"message": "Hello, who are you?"}
    
    print(f"Testing {url}...")
    
    try:
        # Retry a few times in case server is slow to start
        for i in range(5):
            try:
                response = requests.post(url, json=payload, timeout=5)
                if response.status_code == 200:
                    print("Success! Response:")
                    print(response.json())
                    return
                else:
                    print(f"Status code: {response.status_code}")
                    print(response.text)
            except requests.exceptions.ConnectionError:
                print(f"Connection refused, retrying ({i+1}/5)...")
                time.sleep(2)
                continue
                
        print("Failed to connect after retries.")
        sys.exit(1)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_chat()
