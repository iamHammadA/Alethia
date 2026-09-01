from openai import OpenAI

# 1. Paste your Cloudflare URL from Colab
CLOUDFLARE_URL = "https://knows-logic-hunter-performing.trycloudflare.com/"

# 2. Configure standard OpenAI client
client = OpenAI(
    base_url=f"{CLOUDFLARE_URL}/v1",
    api_key="ollama",  # Placeholder key
    timeout=60.0
)

print("Sending request to Colab GPU...")

# 3. Send prompt
response = client.chat.completions.create(
    model="llama3.2:3b",
    messages=[
        {"role": "system", "content": "You are a helpful Python developer."},
        {"role": "user", "content": "Write a Python function to check if a key exists in a dictionary."}
    ]
)

# 4. Save response directly to variable
llm_output = response.choices[0].message.content

print("\n=== RESPONSE STORED IN VARIABLE ===")
print(llm_output)