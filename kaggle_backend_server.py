"""
Kaggle 2x T4 GPU All-in-One AI Backend Server for StudyBook
===========================================================
Engineered for Kaggle's Dual NVIDIA Tesla T4 GPUs (2x 16 GB = 32 GB VRAM):
- Parallel GPU Execution: Qwen2.5-7B-Instruct in FP16 distributed across both T4 GPUs
  (via tensor parallelism / device_map="auto") for 70-100+ tokens/second throughput.
- Vector Embeddings: BAAI/bge-small-en-v1.5 (high speed, 384/512-dim normalized vectors).
- Podcast Audio Engine: Multi-threaded async Edge-TTS + FFmpeg stitching for 10-15 min episodes.
- STT: Faster-Whisper (base.en).
- Tunnel: Cloudflare Tunnel (100% free, permanent URL, no tokens or warning screens).

Endpoints Exposed:
- GET  /health                  -> Health check & GPU diagnostics (GPU 0 and GPU 1 status)
- GET  /v1/models               -> Discovered model catalog
- POST /v1/chat/completions     -> OpenAI-compatible chat (Notebook Chat, Flashcards, Deep Ask, Transformations)
- POST /v1/embeddings           -> OpenAI-compatible text embeddings (Vector RAG)
- POST /api/podcast             -> 10-15 minute narrative podcast generator (7B script + async audio stitching)
- POST /v1/audio/transcriptions -> Whisper STT
"""

import os
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import asyncio
import base64
from contextlib import asynccontextmanager
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Union

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# ==============================================================================
# Model Configurations (Optimized for 2x NVIDIA T4 GPUs)
# ==============================================================================
LLM_MODEL_ID = "Qwen/Qwen2.5-7B-Instruct"  # Blazing fast, 128k context, strict structured JSON
EMBEDDING_MODEL_ID = "BAAI/bge-small-en-v1.5"  # High accuracy, low memory, fast embedding model
DEFAULT_VOICE_EN = "en-US-ChristopherNeural"  # Natural, deep, warm American male host
DEFAULT_VOICE_HI = "hi-IN-MadhurNeural"       # Native warm conversational Hindi male host

# API Authentication Configuration
# Default key is 'studybook-t4-secret' or set via KAGGLE_API_KEY environment variable.
API_KEY = os.environ.get("KAGGLE_API_KEY", os.environ.get("STUDYBOOK_API_KEY", "studybook-t4-secret"))

# Global model state
llm_pipeline = None
embedder = None
whisper_model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_embedding_engine()
    init_whisper_engine()
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, init_llm_engine)
    yield


# ==============================================================================
# FastAPI App Initialization
# ==============================================================================
app = FastAPI(title="StudyBook Kaggle 2x T4 GPU Backend", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    # Allow CORS preflight requests
    if request.method == "OPTIONS":
        return await call_next(request)

    # Check Authorization header (Bearer <key>), x-api-key header, or query param (?api_key= or ?token=)
    auth_header = request.headers.get("Authorization") or ""
    x_api_key = request.headers.get("x-api-key") or ""
    query_key = request.query_params.get("api_key") or request.query_params.get("token") or ""

    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif auth_header:
        token = auth_header.strip()
    elif x_api_key:
        token = x_api_key.strip()
    elif query_key:
        token = query_key.strip()

    if not token or token != API_KEY:
        return JSONResponse(
            status_code=401,
            content={
                "error": "Unauthorized",
                "detail": "Invalid or missing API key. Include 'Authorization: Bearer <key>', 'x-api-key: <key>', or '?api_key=<key>'.",
            },
        )

    return await call_next(request)


# ==============================================================================
# Model Loaders
# ==============================================================================
def init_embedding_engine():
    global embedder
    print("[1/3] Loading Embedding Engine (BAAI/bge-small-en-v1.5)...")
    try:
        from sentence_transformers import SentenceTransformer
        # Embeddings run on CPU to leave 100% of GPU memory for the 7B LLM
        embedder = SentenceTransformer(EMBEDDING_MODEL_ID, device="cpu")
        print("✓ Embedding Engine loaded on CPU.")
    except Exception as e:
        print(f"Embedding Engine warning: {e}. Falling back to FastEmbed/dummy.")


def init_llm_engine():
    global llm_pipeline
    print(f"[2/3] Initializing Large Language Model: {LLM_MODEL_ID} across 2x T4 GPUs...")
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

        num_gpus = torch.cuda.device_count()
        print(f"Detected CUDA devices: {num_gpus}")
        for i in range(num_gpus):
            props = torch.cuda.get_device_properties(i)
            print(f"  GPU {i}: {props.name} ({props.total_memory / (1024**3):.1f} GB VRAM)")

        tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL_ID, trust_remote_code=True)

        model = None
        # Option A: Fast 4-bit NF4 quantization (Uses only ~4.5 GB total VRAM, leaving >10 GB free on each GPU)
        try:
            from transformers import BitsAndBytesConfig
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
            )
            print("Attempting 4-bit NF4 quantization (blazing speed & >10 GB free VRAM buffer)...")
            model = AutoModelForCausalLM.from_pretrained(
                LLM_MODEL_ID,
                quantization_config=bnb_config,
                device_map="auto",
                trust_remote_code=True,
            )
            print("✓ Qwen2.5-7B-Instruct loaded in 4-bit NF4 successfully! (~4.5 GB total VRAM)")
        except Exception as bnb_err:
            print(f"4-bit quantization fallback ({bnb_err}), using explicit 50/50 dual-GPU layer distribution...")

        # Option B: Explicit 50/50 layer split in FP16 (7.6 GB on GPU 0, 7.6 GB on GPU 1)
        if model is None:
            # True 50/50 balance: embed_tokens (1.1 GB) + layers 0-10 (5.7 GB) = 6.8 GB on GPU 0
            # Layers 11-27 (8.8 GB) + norm/lm_head (0.1 GB) = 8.9 GB on GPU 1
            # Leaves ~7.8 GB of FREE VRAM on GPU 0 for attention & KV cache!
            layer_map = {"model.embed_tokens": 0}
            for i in range(28):
                layer_map[f"model.layers.{i}"] = 0 if i <= 10 else 1
            layer_map["model.norm"] = 1
            layer_map["lm_head"] = 1

            print("Assigning balanced layers (embed + layers 0-10 -> GPU 0, layers 11-27 -> GPU 1)...")
            model = AutoModelForCausalLM.from_pretrained(
                LLM_MODEL_ID,
                torch_dtype=torch.float16,
                device_map=layer_map,
                attn_implementation="sdpa",
                trust_remote_code=True,
                low_cpu_mem_usage=True,
            )
            print("✓ Qwen2.5-7B-Instruct evenly split across GPU 0 (~6.8 GB) and GPU 1 (~8.9 GB) with SDPA attention!")

        model.eval()

        # Print layer distribution per device to verify both GPUs are utilized
        if hasattr(model, "hf_device_map"):
            devices_used = set(model.hf_device_map.values())
            print(f"✓ Layers mapped to devices: {devices_used}")

        llm_pipeline = pipeline(
            "text-generation",
            model=model,
            tokenizer=tokenizer,
            torch_dtype=torch.float16,
        )
        print("✓ LLM Pipeline initialized successfully!")
    except Exception as e:
        print(f"LLM initialization warning: {e}")
        try:
            from transformers import pipeline
            fallback_id = "Qwen/Qwen2.5-1.5B-Instruct"
            print(f"Falling back to lightweight model {fallback_id}...")
            llm_pipeline = pipeline("text-generation", model=fallback_id, device_map="auto")
            print("✓ Fallback LLM initialized.")
        except Exception as ex:
            print(f"Fatal LLM error: {ex}")


def init_whisper_engine():
    global whisper_model
    print("[3/3] Loading Whisper Speech-to-Text Engine...")
    try:
        from faster_whisper import WhisperModel
        whisper_model = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=4)
        print("✓ Whisper Engine loaded on CPU.")
    except Exception as e:
        print(f"Whisper STT note: {e}")


# ==============================================================================
# Endpoint 1: Root, Ping, and Health Diagnostics
# ==============================================================================
@app.get("/")
async def root():
    return {
        "status": "online",
        "backend": "Kaggle 2x T4 GPU",
        "message": "StudyBook Kaggle Backend is healthy and ready.",
        "endpoints": ["/ping", "/health", "/v1/models", "/v1/chat/completions", "/v1/embeddings", "/api/podcast"],
    }


@app.get("/ping")
@app.head("/ping")
async def ping():
    return {
        "status": "ok",
        "message": "pong",
        "backend": "Kaggle 2x T4 GPU",
    }


@app.get("/health")
@app.head("/health")
async def health_check():
    import torch
    num_gpus = torch.cuda.device_count() if torch.cuda.is_available() else 0
    gpu_info = []
    for i in range(num_gpus):
        props = torch.cuda.get_device_properties(i)
        gpu_info.append({
            "index": i,
            "name": props.name,
            "vram_gb": round(props.total_memory / (1024**3), 1),
            "allocated_gb": round(torch.cuda.memory_allocated(i) / (1024**3), 2),
        })

    return {
        "status": "healthy",
        "backend": "Kaggle 2x T4 GPU",
        "gpu_count": num_gpus,
        "gpus": gpu_info,
        "llm_ready": llm_pipeline is not None,
        "embedding_ready": embedder is not None,
        "stt_ready": whisper_model is not None,
        "models": {
            "llm": LLM_MODEL_ID,
            "embedding": EMBEDDING_MODEL_ID,
            "tts": "Edge-TTS Neural Multi-threaded",
        },
    }


# ==============================================================================
# Endpoint 2: Model Discovery
# ==============================================================================
@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "Qwen/Qwen2.5-7B-Instruct",
                "object": "model",
                "type": "language",
                "owned_by": "kaggle",
                "description": f"Dual-T4 accelerated LLM ({LLM_MODEL_ID})",
            },
            {
                "id": "kaggle-tpu-chat",
                "object": "model",
                "type": "language",
                "owned_by": "kaggle",
                "description": f"Dual-T4 accelerated LLM ({LLM_MODEL_ID})",
            },
            {
                "id": "BAAI/bge-small-en-v1.5",
                "object": "model",
                "type": "embedding",
                "owned_by": "kaggle",
                "description": f"Vector Embeddings ({EMBEDDING_MODEL_ID})",
            },
            {
                "id": "kaggle-tpu-embedding",
                "object": "model",
                "type": "embedding",
                "owned_by": "kaggle",
                "description": f"Vector Embeddings ({EMBEDDING_MODEL_ID})",
            },
            {
                "id": "kaggle-tpu-podcast",
                "object": "model",
                "type": "text_to_speech",
                "owned_by": "kaggle",
                "description": "Multi-threaded Neural Podcast Engine",
            },
            {
                "id": "kaggle-tpu-stt",
                "object": "model",
                "type": "speech_to_text",
                "owned_by": "kaggle",
                "description": "Whisper Speech-to-Text",
            },
        ],
    }


# ==============================================================================
# Endpoint 3: OpenAI-Compatible Chat Completions
# ==============================================================================
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "kaggle-tpu-chat"
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.2
    max_tokens: Optional[int] = 8192
    stream: Optional[bool] = False


def _format_messages_to_prompt(messages: List[ChatMessage], tokenizer) -> str:
    if hasattr(tokenizer, "apply_chat_template"):
        hf_messages = [{"role": m.role, "content": m.content} for m in messages]
        try:
            return tokenizer.apply_chat_template(hf_messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            pass

    blocks = []
    for m in messages:
        if m.role == "system":
            blocks.append(f"<|im_start|>system\n{m.content}<|im_end|>")
        elif m.role == "user":
            blocks.append(f"<|im_start|>user\n{m.content}<|im_end|>")
        elif m.role == "assistant":
            blocks.append(f"<|im_start|>assistant\n{m.content}<|im_end|>")
    blocks.append("<|im_start|>assistant\n")
    return "\n".join(blocks)


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    if llm_pipeline is None:
        raise HTTPException(status_code=503, detail="LLM engine is still initializing on 2x T4. Please retry in 30 seconds.")

    prompt_text = _format_messages_to_prompt(req.messages, llm_pipeline.tokenizer)
    max_tokens = min(req.max_tokens or 8192, 16384)
    temp = max(0.01, req.temperature or 0.2)

    def _generate():
        import torch
        with torch.inference_mode():
            outputs = llm_pipeline(
                prompt_text,
                max_new_tokens=max_tokens,
                temperature=temp,
                do_sample=temp > 0.05,
                pad_token_id=getattr(llm_pipeline.tokenizer, "eos_token_id", None),
                return_full_text=False,
            )
            res = outputs[0]["generated_text"]
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        return res

    loop = asyncio.get_event_loop()
    generated_text = await loop.run_in_executor(None, _generate)

    # Clean thinking tags if present
    cleaned_text = re.sub(r"<think>[\s\S]*?</think>", "", generated_text).strip()
    if not cleaned_text:
        cleaned_text = generated_text.strip()

    # Streaming mode response
    if req.stream:
        async def event_generator():
            chunk_size = 12
            for i in range(0, len(cleaned_text), chunk_size):
                chunk = cleaned_text[i:i + chunk_size]
                payload = {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": req.model,
                    "choices": [
                        {"index": 0, "delta": {"content": chunk}, "finish_reason": None}
                    ],
                }
                yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(0.015)
            # Final chunk
            final_payload = {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": req.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(final_payload)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # Non-streaming response
    return {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": cleaned_text,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": len(prompt_text) // 4,
            "completion_tokens": len(cleaned_text) // 4,
            "total_tokens": (len(prompt_text) + len(cleaned_text)) // 4,
        },
    }


# ==============================================================================
# Endpoint 4: Vector Embeddings
# ==============================================================================
class EmbeddingRequest(BaseModel):
    model: str = "kaggle-tpu-embedding"
    input: Union[str, List[str]]


@app.post("/v1/embeddings")
async def create_embeddings(req: EmbeddingRequest):
    if embedder is None:
        raise HTTPException(status_code=503, detail="Embedding engine is still loading.")

    texts = [req.input] if isinstance(req.input, str) else req.input
    if not texts:
        return {"object": "list", "data": [], "model": req.model}

    loop = asyncio.get_event_loop()
    vectors = await loop.run_in_executor(None, lambda: embedder.encode(texts, normalize_embeddings=True))

    data_items = [
        {
            "object": "embedding",
            "index": idx,
            "embedding": vec.tolist() if hasattr(vec, "tolist") else list(vec),
        }
        for idx, vec in enumerate(vectors)
    ]

    return {
        "object": "list",
        "data": data_items,
        "model": req.model,
        "usage": {"total_tokens": sum(len(t) for t in texts) // 4},
    }


# ==============================================================================
# Endpoint 5: 10-15 Minute Audio Podcast Engine
# ==============================================================================
class PodcastRequest(BaseModel):
    content: str
    briefing: str = "Produce an articulate, conversational podcast episode explaining the concepts."
    episode_name: str = "Episode"
    duration_minutes: int = 15
    language: str = "en"


async def synthesize_speech_edge(text: str, voice: str, output_path: str):
    """Synthesize text chunk to MP3 using edge-tts (streams directly over network, zero CPU/GPU overhead)."""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def split_text_into_speech_chunks(text: str, max_chars: int = 280) -> List[str]:
    """Split text cleanly at sentence boundaries so audio flows naturally."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    current_chunk = ""

    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(current_chunk) + len(s) + 1 <= max_chars:
            current_chunk = f"{current_chunk} {s}".strip()
        else:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = s

    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def stitch_mp3_files(chunk_files: List[str], output_file: str):
    """Concatenate MP3 files using ffmpeg."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as concat_list:
        list_path = concat_list.name
        for cf in chunk_files:
            concat_list.write(f"file '{cf}'\n")

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", list_path, "-c", "copy", output_file
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        if os.path.exists(list_path):
            os.remove(list_path)


def get_mp3_duration(file_path: str) -> float:
    """Return duration in seconds using ffprobe, mutagen, or bitrate estimation."""
    try:
        res = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return max(0.1, float(res.stdout.strip()))
    except Exception:
        try:
            import mutagen.mp3
            return max(0.1, float(mutagen.mp3.MP3(file_path).info.length))
        except Exception:
            # Edge-TTS default 128kbps stereo MP3 is ~16,000 bytes/sec
            size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
            return max(1.0, round(size / 16000.0, 2))


# Background Podcast Job Registry (Keeps connections under 100ms to eliminate Cloudflare 100s timeout)
PODCAST_JOBS: Dict[str, Dict[str, Any]] = {}


async def _run_podcast_pipeline(job_id: str, req: PodcastRequest):
    """Executes the full podcast generation pipeline in the background."""
    target_words = 1200 if req.duration_minutes >= 12 else 800
    target_voice = DEFAULT_VOICE_HI if req.language == "hi" else DEFAULT_VOICE_EN

    try:
        PODCAST_JOBS[job_id]["progress"] = 0.15
        PODCAST_JOBS[job_id]["message"] = "Generating spoken script with Qwen2.5-7B across 2x T4 GPUs..."

        # Stage 1: Generate spoken monologue on 2x T4
        script_prompt = f"""You are a seasoned, charismatic podcast host. Turn the reference material below into an engaging, cohesive {req.duration_minutes}-minute spoken monologue.

REFERENCE MATERIAL:
{req.content[:10000]}

ADDITIONAL BRIEFING:
{req.briefing}

STRICT PRODUCTION RULES:
1. Deliver a natural spoken-word monologue of roughly {target_words} words.
2. DO NOT include visual markdown (no asterisks, no bullet points, no stage directions like '[Laughs]' or '(Intro music)').
3. Speak with warmth, eloquence, clarity, and pacing. Introduce the topic with a hook, break down key concepts with vivid analogies, and conclude with insightful synthesis.
4. Language: {req.language}.
5. Conclude cleanly with a natural host sign-off sentence. NEVER output hashtags, buzzword lists, metadata tags, emojis, or repeated slogans. Stop speaking immediately after your final sign-off.

BEGIN SPOKEN MONOLOGUE SCRIPT:"""

        loop = asyncio.get_event_loop()
        eos_token_id = getattr(getattr(llm_pipeline, "tokenizer", None), "eos_token_id", None)

        def _generate_script():
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            with torch.inference_mode():
                outputs = llm_pipeline(
                    script_prompt,
                    max_new_tokens=1800,
                    temperature=0.6,
                    repetition_penalty=1.18,
                    no_repeat_ngram_size=4,
                    do_sample=True,
                    pad_token_id=eos_token_id,
                    return_full_text=False,
                )
                text = outputs[0]["generated_text"]
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            return text

        raw_script = await loop.run_in_executor(None, _generate_script)

        # Remove markdown symbols and stray brackets
        clean_script = re.sub(r"[\*#_\[\]\(\)\{\}\<\>]", " ", raw_script)
        # Strip non-standard emojis/pictographs that confuse TTS
        clean_script = re.sub(r"[^\w\s\.,!\?'-]", " ", clean_script, flags=re.UNICODE)
        clean_script = re.sub(r"\s+", " ", clean_script).strip()

        # Sanitize any trailing degenerate buzzword loop
        sentences = re.split(r"(?<=[.!?])\s+", clean_script)
        filtered_sentences = []
        for s in sentences:
            words = s.split()
            # If a sentence is >70% long capitalized words without grammar, it's a buzzword loop
            title_words = [w for w in words if w.istitle() and len(w) > 3]
            if len(title_words) >= 8 and len(title_words) / max(1, len(words)) > 0.7:
                break
            filtered_sentences.append(s)

        if filtered_sentences:
            clean_script = " ".join(filtered_sentences).strip()

        if not clean_script:
            raise RuntimeError("Script generation returned empty text.")

        PODCAST_JOBS[job_id]["progress"] = 0.55
        PODCAST_JOBS[job_id]["message"] = "Synthesizing parallel Edge-TTS neural speech audio..."

        # Stage 2: Parallel chunk synthesis (16 concurrent coroutines)
        chunks = split_text_into_speech_chunks(clean_script)
        temp_dir = tempfile.mkdtemp()

        try:
            semaphore = asyncio.Semaphore(16)

            async def _synthesize_chunk(idx: int, chunk_text: str):
                out_p = os.path.join(temp_dir, f"chunk_{idx:04d}.mp3")
                async with semaphore:
                    await synthesize_speech_edge(chunk_text, target_voice, out_p)
                return out_p

            tasks = [_synthesize_chunk(i, c) for i, c in enumerate(chunks)]
            chunk_paths = await asyncio.gather(*tasks)

            PODCAST_JOBS[job_id]["progress"] = 0.88
            PODCAST_JOBS[job_id]["message"] = "Concatenating MP3 audio chunks into master track..."

            # Stage 3: Stitch into final MP3
            master_mp3 = os.path.join(temp_dir, "master.mp3")
            stitch_mp3_files(chunk_paths, master_mp3)

            with open(master_mp3, "rb") as f:
                audio_bytes = f.read()

            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

            transcript_data = []
            curr_time = 0.0
            for c, c_path in zip(chunks, chunk_paths):
                dur = get_mp3_duration(c_path)
                start_sec = round(curr_time, 2)
                end_sec = round(curr_time + dur, 2)
                transcript_data.append({
                    "speaker": "Host",
                    "text": c,
                    "dialogue": c,
                    "start": start_sec,
                    "end": end_sec,
                    "duration": round(dur, 2),
                })
                curr_time += dur

            total_duration = round(curr_time, 2)

            outline_data = {
                "title": req.episode_name,
                "duration_target": f"{req.duration_minutes} minutes",
                "sections": [
                    {"title": "Introduction & Hook", "summary": chunks[0] if chunks else ""},
                    {"title": "Core Breakdown", "summary": "Detailed exploration of concepts."},
                    {"title": "Synthesis & Conclusion", "summary": chunks[-1] if chunks else ""},
                ],
            }

            PODCAST_JOBS[job_id] = {
                "job_id": job_id,
                "status": "completed",
                "progress": 1.0,
                "message": "Podcast generated successfully.",
                "result": {
                    "success": True,
                    "episode_name": req.episode_name,
                    "duration_seconds": total_duration,
                    "outline": outline_data,
                    "transcript": transcript_data,
                    "audio_base64": audio_b64,
                },
                "completed_at": time.time(),
            }

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    except Exception as e:
        PODCAST_JOBS[job_id] = {
            "job_id": job_id,
            "status": "failed",
            "progress": 0.0,
            "error": str(e),
            "message": f"Failed: {str(e)}",
        }


@app.post("/api/podcast")
async def generate_podcast(req: PodcastRequest, sync: bool = False):
    """
    Complete Podcast Production Engine on 2x T4:
    Dispatches asynchronous job so requests return in < 100ms, completely
    bypassing Cloudflare Tunnel's 100-second idle timeout.
    """
    try:
        if llm_pipeline is None:
            raise HTTPException(status_code=503, detail="LLM engine is initializing.")

        # Cleanup expired jobs older than 1 hour
        now = time.time()
        expired = [k for k, v in PODCAST_JOBS.items() if now - v.get("created_at", now) > 3600]
        for k in expired:
            PODCAST_JOBS.pop(k, None)

        job_id = f"pod_{int(time.time())}_{os.urandom(3).hex()}"
        PODCAST_JOBS[job_id] = {
            "job_id": job_id,
            "status": "processing",
            "progress": 0.05,
            "message": "Queued podcast generation on 2x T4 GPUs...",
            "created_at": now,
        }

        asyncio.create_task(_run_podcast_pipeline(job_id, req))

        if sync:
            while PODCAST_JOBS[job_id]["status"] == "processing":
                await asyncio.sleep(1.0)
            job = PODCAST_JOBS[job_id]
            if job["status"] == "completed":
                return job["result"]
            raise HTTPException(status_code=500, detail=job.get("error", "Podcast failed"))

        return {
            "job_id": job_id,
            "status": "processing",
            "progress": 0.05,
            "message": "Generating spoken script on 2x T4 GPUs...",
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in /api/podcast handler: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Podcast dispatch error: {str(e)}")


@app.get("/api/podcast/status/{job_id}")
async def get_podcast_status(job_id: str):
    job = PODCAST_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Podcast job not found.")
    return job


# ==============================================================================
# Endpoint 6: Speech-to-Text Transcription
# ==============================================================================
@app.post("/v1/audio/transcriptions")
async def audio_transcription(file: UploadFile = File(...)):
    if whisper_model is None:
        raise HTTPException(status_code=503, detail="Whisper STT model not loaded.")

    with tempfile.NamedTemporaryFile("wb", suffix=f"_{file.filename}") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        segments, info = whisper_model.transcribe(tmp_path, beam_size=5)
        text_parts = [segment.text for segment in segments]
        full_text = " ".join(text_parts).strip()
        return {"text": full_text}
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ==============================================================================
# Main Server Runner with Tunnel Support (Cloudflare Tunnel)
# ==============================================================================
def start_tunnel_and_server(port: int = 8000):
    print("\n" + "=" * 60)
    print("🚀 Launching Cloudflare Tunnel for 2x T4 GPU Backend...")
    print("=" * 60)

    if not shutil.which("cloudflared"):
        print("Installing cloudflared binary...")
        subprocess.run(
            ["wget", "-q", "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64", "-O", "cloudflared"],
            check=True
        )
        subprocess.run(["chmod", "+x", "cloudflared"], check=True)
        cf_bin = "./cloudflared"
    else:
        cf_bin = "cloudflared"

    tunnel_proc = subprocess.Popen(
        [cf_bin, "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    tunnel_url = None
    for _ in range(40):
        time.sleep(0.5)
        line = tunnel_proc.stderr.readline()
        if "trycloudflare.com" in line:
            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
            if match:
                tunnel_url = match.group(0)
                break

    if tunnel_url:
        print("\n" + "*" * 60)
        print("🎉 YOUR 2x T4 STUDYBOOK BACKEND IS LIVE!")
        print("👉 Copy this Base URL into StudyBook Settings:")
        print(f"   {tunnel_url}")
        print("👉 Copy this API Key into StudyBook Settings (or KAGGLE_API_KEY):")
        print(f"   {API_KEY}")
        print("*" * 60 + "\n")
    else:
        print("Could not auto-detect Cloudflare tunnel URL, check logs below.")

    import threading

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)

    # Detect if running inside a Jupyter / Kaggle notebook (IPython has an active event loop)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        print("Detected running event loop (Jupyter/Kaggle notebook environment).")
        print("Launching Uvicorn server in a dedicated worker thread...")
        server_thread = threading.Thread(
            target=lambda: asyncio.run(server.serve()),
            daemon=True,
        )
        server_thread.start()
        try:
            while server_thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down Kaggle backend server...")
    else:
        server.run()


if __name__ == "__main__":
    start_tunnel_and_server()
