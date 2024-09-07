import os
import json
import logging
import uvicorn
import requests
from typing import AnyStr, Optional
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
import hashlib
import hmac
from dotenv import load_dotenv
load_dotenv()

from korvus import Collection, Pipeline
import asyncio

KORVUS_DATABASE_URL = os.environ["KORVUS_DATABASE_URL"]

collection = Collection("korvus-demo-v0", KORVUS_DATABASE_URL)
pipeline = Pipeline(
    "v1",
    {
        "text": {
            "splitter": {"model": "recursive_character"},
            "semantic_search": {"model": "Alibaba-NLP/gte-base-en-v1.5"},
        }
    },
)

async def add_pipeline():
    await collection.add_pipeline(pipeline)

asyncio.run(add_pipeline())

async def rag(query):
    print(f"Querying for response to: {query}")
    results = await collection.rag(
        {
            "CONTEXT": {
                "vector_search": {
                    "query": {
                        "fields": {"text": {"query": query}},
                    },
                    "document": {"keys": ["id"]},
                    "limit": 1,
                },
                "aggregate": {"join": "\n"},
            },
            "chat": {
                "model": "meta-llama/Meta-Llama-3-8B-Instruct",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a friendly and helpful chatbot called Gerrit. The people who write you are usually young people from all over the world who come to Czech republic for a short-term university exchange programme. Sometimes they ask for information prior to arriving, sometimes they ask for information while already in Czech republic. Your answers must always be within 100 tokens",
                    },
                    {
                        "role": "user",
                        "content": f"Given the context\n:{{CONTEXT}}\nAnswer the question: {query}",
                    },
                ],
                "max_tokens": 100,
            },
        },
        pipeline,
    )
    print(results)
    return results

app = FastAPI(root_path="/api/v1")

# Logging toolbox 🔊
# TODO change logging level dynamically
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("webhook")


@app.get("/")
async def index():
    return {"data": "Hello World"}

@app.get("/webhook")
async def verify_token(
    verify_token: Optional[str] = Query(
        None, alias="hub.verify_token", regex="^[A-Za-z1-9-_]*$"
    ),
    challenge: Optional[str] = Query(
        None, alias="hub.challenge"
    ),
    mode: Optional[str] = Query(
        "subscribe", alias="hub.mode", regex="^[A-Za-z1-9-_]*$"
    ),
) -> Optional[str]:
    token = os.environ["FB_VERIFY_TOKEN"]
    print(token)
    logger.debug(mode, verify_token, challenge)
    if not token or len(token) < 8:
        logger.error(
            "🔒Token not defined. Must be at least 8 chars or numbers."
            "💡Tip: set -a; source .env; set +a"
        )
        raise HTTPException(status_code=500, detail="Webhook unavailable.")
    elif verify_token == token and mode == "subscribe":
        return Response(f"{challenge}")
    else:
        raise HTTPException(status_code=403, detail="Token invalid.")


@app.post("/webhook")
async def trigger_response(request: Request) -> None:
    data = await request.json()
    logger.info(data)
    payload = (
        json.dumps(data, separators=(",", ":"))
        .replace("/", "\\/")
        .replace("@", "\\u0040")
        .replace("%", "\\u0025")
        .replace("<", "\\u003C")
        .encode()
    )
    app_secret = os.environ["FB_APP_SECRET"].encode()
    logger.debug(app_secret)
    expected_signature = hmac.new(
        app_secret, payload, digestmod=hashlib.sha1
    ).hexdigest()
    logger.debug(expected_signature)
    signature = request.headers["x-hub-signature"][5:]
    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=403, detail="Message not authenticated.")
    try:
        message = data["entry"][0]["messaging"][0]["message"]
        logger.info(message)
        sender_id = data["entry"][0]["messaging"][0]["sender"]["id"]
        if message["text"]:
            llm_response = await rag(message["text"])
            llm_response = llm_response.get("rag")[0]
            llm_response = llm_response.replace('\n', ' ')
            logger.info(llm_response)
            request_body = {
                "recipient": {"id": sender_id},
                "message": {"text": llm_response},
            }
            FB_PAGE_ACCESS_TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
            response = requests.post(
                f"https://graph.facebook.com/v11.0/me/messages?access_token={FB_PAGE_ACCESS_TOKEN}",
                json=request_body,
            ).json()
            logger.info(response)
    except KeyError:
        logger.info("Message sent and received by recipient. ✅")
        pass
    return None
