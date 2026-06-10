import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

# Using a lightweight, fast embedding model — works well offline on AMD GPU env
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMB_FN = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)


def build_store(
    chunks: list[str],
    collection_name: str = "doc_chunks",
) -> chromadb.Collection:
    """
    Create an in-memory ChromaDB collection and populate it with document chunks.
    In-memory is intentional for hackathon speed — no disk I/O, no persistence needed.
    """
    client = chromadb.Client()  # ephemeral, in-memory
    col = client.get_or_create_collection(
        name=collection_name,
        embedding_function=EMB_FN,
    )
    col.add(
        documents=chunks,
        ids=[f"chunk_{i}" for i in range(len(chunks))],
    )
    return col


def retrieve(
    col: chromadb.Collection,
    query: str,
    n: int = 3,
) -> list[str]:
    """
    Retrieve the top-n most semantically relevant chunks for a given query.
    Returns a list of document strings.
    """
    results = col.query(query_texts=[query], n_results=min(n, col.count()))
    return results["documents"][0]
