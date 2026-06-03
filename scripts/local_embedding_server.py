import os
from typing import List, Union

import torch
import torch.nn.functional as F
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoModel, AutoTokenizer


MODEL_PATH = os.environ.get("EMBEDDING_MODEL", "/root/user/ldh/models/Qwen3-Embedding-0.6B")
MAX_LENGTH = int(os.environ.get("EMBEDDING_MAX_LENGTH", "1024"))

app = FastAPI()

tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
model = AutoModel.from_pretrained(
    MODEL_PATH,
    trust_remote_code=True,
    torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model.to(device)
model.eval()


class EmbeddingRequest(BaseModel):
    input: Union[str, List[str]]
    model: str | None = None


def _last_token_pool(last_hidden_states: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_size = last_hidden_states.shape[0]
    return last_hidden_states[torch.arange(batch_size, device=last_hidden_states.device), sequence_lengths]


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_PATH}


@app.post("/v1/embeddings")
def embeddings(request: EmbeddingRequest):
    texts = request.input if isinstance(request.input, list) else [request.input]
    encoded = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=MAX_LENGTH,
        return_tensors="pt",
    )
    encoded = {key: value.to(device) for key, value in encoded.items()}

    with torch.inference_mode():
        output = model(**encoded)
        pooled = _last_token_pool(output.last_hidden_state, encoded["attention_mask"])
        pooled = F.normalize(pooled, p=2, dim=1)

    vectors = pooled.float().cpu().tolist()
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in enumerate(vectors)
        ],
        "model": request.model or MODEL_PATH,
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }
