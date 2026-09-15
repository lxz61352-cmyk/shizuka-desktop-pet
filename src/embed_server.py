# -*- coding: utf-8 -*-
r"""本地语义 embedding 服务：用 GPT-SoVITS 自带的 chinese-roberta 模型。
用 GPT-SoVITS 的 runtime python 运行： runtime\python.exe embed_server.py

POST /embed  {"texts": ["a", "b"]}  ->  {"vecs": [[...], ...]}
（GET /embed?text=... 或 ?texts=a\nb\nc 仍兼容）"""
from typing import List
import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModel
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

import os
MODEL_DIR = os.environ.get("DESKPET_EMBED_MODEL", "models/chinese-roberta-wwm-ext-large")
# 用 CPU：避免和 GPT-SoVITS 语音服务抢显存（每次只算 1 条 query，~0.5s，够用）
DEV = "cpu"

tok = AutoTokenizer.from_pretrained(MODEL_DIR)
model = AutoModel.from_pretrained(MODEL_DIR).eval().to(DEV)

app = FastAPI()


@torch.no_grad()
def _embed(texts):
    if not texts:
        return []
    b = tok(texts, padding=True, truncation=True, max_length=128, return_tensors="pt").to(DEV)
    o = model(**b).last_hidden_state
    mask = b["attention_mask"].unsqueeze(-1).to(o.dtype)
    v = (o * mask).sum(1) / mask.sum(1).clamp(min=1)
    return F.normalize(v.float(), dim=1).cpu().tolist()


class EmbReq(BaseModel):
    texts: List[str] = []


@app.post("/embed")
def embed_post(req: EmbReq):
    texts = [t if isinstance(t, str) else str(t) for t in (req.texts or [])]
    if not texts:
        return {"vecs": []}
    return {"vecs": _embed(texts)}


@app.get("/embed")
def embed_ep(text: str = "", texts: str = ""):
    arr = texts.split("\n") if texts else ([text] if text else [])
    if not arr:
        return {"vecs": []}
    return {"vecs": _embed(arr)}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9881)
