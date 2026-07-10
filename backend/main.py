"""
FastAPI server with WebSocket streaming support.
Select workflow via query param: ws://host/ws?mode=w1~w4
"""

import json
import logging
import traceback

logging.basicConfig(level=logging.INFO)
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
import uvicorn

from config import *
from limiter import limiter
from streaming.asr_azure import StreamingASR
from streaming.llm_api import StreamingLLM
from streaming.tts_azure import StreamingTTS
from pipelines.factory import init_pipelines, get_pipeline, list_pipelines
from rag.retriever import MedicalRAG
from api.auth import router as auth_router
from api.conversations import router as conv_router
from auth.jwt import verify_token
from database.models import User, Conversation, Message
from database import async_session_factory
from sqlalchemy import select

import re

async def rate_limit_handler(request, exc: RateLimitExceeded):
    seconds = 60
    try:
        m = re.search(r'per (\d+) (second|minute|hour|day)', str(exc))
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            if unit == 'second': seconds = n
            elif unit == 'minute': seconds = n * 60
            elif unit == 'hour': seconds = n * 3600
            elif unit == 'day': seconds = n * 86400
    except Exception:
        pass
    return JSONResponse(
        status_code=429,
        content={"detail": f"请求过于频繁，请等待 {seconds} 秒后重试", "retry_after": seconds},
    )

app = FastAPI(title="健康与医疗智能问答系统 — 流式管线版")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.include_router(auth_router)
app.include_router(conv_router)

asr = StreamingASR(AZURE_SPEECH_KEY, AZURE_SPEECH_REGION)

retriever = None
if RAG_ENABLED:
    try:
        model_name = RAG_EMBEDDING_MODEL
        if not Path(model_name).is_absolute():
            candidate = BASE_DIR / model_name
            if candidate.exists():
                model_name = str(candidate.resolve())
        retriever = MedicalRAG(
            persist_dir=RAG_PERSIST_DIR,
            model_name=model_name,
        )
        if retriever.is_ready():
            logging.info(f"RAG retriever ready: {retriever.get_count()} documents")
        else:
            logging.warning("RAG index is empty, run: python -m rag.prepare_data")
    except Exception as e:
        logging.warning(f"RAG init failed: {e}")

llm = StreamingLLM(DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
                   retriever=retriever, rag_top_k=RAG_TOP_K)
tts = StreamingTTS(AZURE_SPEECH_KEY, AZURE_SPEECH_REGION, TTS_VOICE)
init_pipelines(asr, llm, tts)


@app.get("/pipelines")
async def get_pipelines():
    return list_pipelines()


@app.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    mode: str = Query("w1"),
    token: str = Query(""),
    conv_id: int = Query(0),
):
    await ws.accept()

    user_id_val = None
    if token:
        try:
            payload = verify_token(token)
            user_id_val = int(payload.get("sub"))
            async with async_session_factory() as db:
                user = await db.scalar(select(User).where(User.id == user_id_val))
                if not user:
                    await ws.send_json({"error": "认证失败"})
                    await ws.close()
                    return
        except Exception:
            await ws.send_json({"error": "认证失败，请重新登录"})
            await ws.close()
            return

    pipeline = get_pipeline(mode)
    if pipeline is None:
        await ws.send_json({"error": f"未知工作流: {mode}"})
        await ws.close()
        return

    current_conv_id = conv_id if conv_id > 0 else 0

    async def save_round(asr_text: str, answer_text: str, rag_docs: list | None = None):
        nonlocal current_conv_id
        if not user_id_val or not asr_text.strip() or not answer_text.strip():
            return
        async with async_session_factory() as db:
            if current_conv_id == 0:
                conv = Conversation(
                    user_id=user_id_val,
                    title=asr_text[:30] if len(asr_text) > 30 else asr_text,
                )
                db.add(conv)
                await db.flush()
                current_conv_id = conv.id
                await ws.send_json({"type": "conv_created", "conv_id": conv.id, "title": conv.title})
            else:
                conv = await db.scalar(
                    select(Conversation).where(
                        Conversation.id == current_conv_id,
                        Conversation.user_id == user_id_val,
                    )
                )
                if not conv:
                    conv = Conversation(
                        user_id=user_id_val,
                        title=asr_text[:30] if len(asr_text) > 30 else asr_text,
                    )
                    db.add(conv)
                    await db.flush()
                    current_conv_id = conv.id
                    await ws.send_json({"type": "conv_created", "conv_id": conv.id, "title": conv.title})

            user_msg = Message(conversation_id=current_conv_id, role="user", content=asr_text)
            assistant_msg = Message(
                conversation_id=current_conv_id,
                role="assistant",
                content=answer_text,
                search_results=rag_docs,
            )
            db.add(user_msg)
            db.add(assistant_msg)
            conv.message_count = (conv.message_count or 0) + 2
            await db.commit()

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if "text" in msg:
                data = json.loads(msg["text"])
                if data.get("type") == "text_query":
                    text = data.get("text", "").strip()
                    if text:
                        await pipeline.run_text(text, ws, on_answer=save_round)
                    continue
                async def _single(msg=msg):
                    if "text" in msg:
                        yield (b"", True)
                    elif "bytes" in msg:
                        yield (msg["bytes"], False)
                await pipeline.run_stream(_single(), ws, on_answer=save_round)
            elif "bytes" in msg:
                async def _audio_iter():
                    yield (msg["bytes"], False)
                    async for chunk in _iter_audio_chunks(ws):
                        yield chunk
                await pipeline.run_stream(_audio_iter(), ws, on_answer=save_round)

    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as e:
        traceback.print_exc()
        try:
            await ws.send_json({"error": str(e)})
        except Exception:
            pass


async def _iter_audio_chunks(ws):
    """
    Async generator that yields (chunk_bytes, is_last).
    Audio chunks are binary WebSocket messages.
    Send {"type": "audio_end"} as text to signal end of utterance.
    """
    while True:
        msg = await ws.receive()
        if msg["type"] == "websocket.disconnect":
            break
        if "bytes" in msg:
            yield (msg["bytes"], False)
        elif "text" in msg:
            data = json.loads(msg["text"])
            if data.get("type") in ("audio_end", "stop"):
                yield (b"", True)
                break
            yield (b"", True)
            break


app.mount("/", StaticFiles(directory=str(Path(__file__).parent.parent / "frontend"), html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
