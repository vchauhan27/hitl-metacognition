import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

# ---------------------------------------------------------
# Environment
# ---------------------------------------------------------
 
load_dotenv()

CHROMA_DIR = "./chroma_db"
CHROMA_COLLECTION = "notes"
NOTES_FILE = str(Path(__file__).parent / "data" / "notes.txt")

# ---------------------------------------------------------
# Metacognition Harness Parameters
# ---------------------------------------------------------
ARM = "C" # Active arm: "A" (bare), "B" (prompt-only), "C" (harness)
RETRIEVAL_THRESHOLD = 0.5
JEV_VAGUE_THRESHOLD = 0.85
MEMORY_AGE_LIMIT_DAYS = 30

# ---------------------------------------------------------
# LLM & Embeddings
# ---------------------------------------------------------

def get_llm():

    return ChatOpenAI(
        model="qwen/qwen-2.5-7b-instruct",
        api_key=os.environ.get("OPENROUTER_API_KEY"),  # type: ignore
        base_url="https://openrouter.ai/api/v1",
        temperature=0.5,
    )

def get_jev_model_name():
    return "typesafe/jev-1.13"

def get_jev_client():
    from typesafe_sdk import TypeSafeClient
    return TypeSafeClient(
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api",
        timeout=30.0,  
    )

class OpenRouterEmbeddings(OpenAIEmbeddings):
    def embed_documents(self, texts, chunk_size=None, **kwargs):
        embeddings = []
        for text in texts:
            response = self.client.create(model=self.model, input=text)
            embeddings.append(response.data[0].embedding)
        return embeddings

    def embed_query(self, text, **kwargs):
        response = self.client.create(model=self.model, input=text)
        return response.data[0].embedding

def get_embeddings():
        
    return OpenRouterEmbeddings(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("OPENROUTER_API_KEY"),  # type: ignore
        model="baai/bge-m3",
    )