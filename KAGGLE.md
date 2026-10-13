## Architectural Plan & System Blueprint                                                                                                                         
                                                                                                                                                                  
Here is the complete operational plan for running both the Docling-augmented Chat and the 10–15 minute Podcast Audio generator on your Kaggle TPU instance.       
──────                                                                                                                                                            
### System Overview & Hardware Division                                                                                                                           
                                                                                                                                                                  
Kaggle’s TPU environment gives you two distinct computing engines:                                                                                                
                                                                                                                                                                  
• 8 TPU Cores (128 GB total HBM): Dedicated entirely to the core Large Language Model. Because Docling handles parsing upstream and sends structured markdown, the
TPU can run a much larger, higher-reasoning text model (such as a 14B to 32B parameter model) with an extended context window (64k to 128k tokens) to swallow     
entire document dossiers without slowing down.                                                                                                                    
• Host CPU (96 vCPUs & ~330 GB System RAM): Dedicated to web search retrieval, script chunking, and multi-threaded Text-to-Speech (TTS) audio synthesis and       
stitching. This prevents audio generation from competing with the TPU for tensor memory.                                                                          
──────                                                                                                                                                            
### Feature 1: Structured Chat Engine (Docling + Markdown)                                                                                                        
                                                                                                                                                                  
#### Workflow                                                                                                                                                     
                                                                                                                                                                  
1. Source Ingestion: Your client application transmits the Docling markdown directly along with the user prompt to the endpoint. Because Docling preserves tables,
headings, and hierarchy, the text is treated as a verified factual knowledge base.                                                                                
2. Gap Detection & Web Augmentation:                                                                                                                              
    • Before answering, the system runs a fast query-extraction check.                                                                                            
    • If the prompt asks for real-time information, recent events, or context missing from the Docling sources, the server automatically queries search engines in
    the background.                                                                                                                                               
    • The retrieved search summaries are appended to the prompt as auxiliary reference notes.                                                                     
3. Reasoning & Markdown Generation:                                                                                                                               
    • The model synthesizes both the Docling data and search results.                                                                                             
    • It enforces strict markdown standards: formatted tables, bullet points, callout blocks, and bracketed source citations indicating whether a fact came from  
    your Docling document or from live web search.                                                                                                                
4. Delivery: The response is returned immediately over the tunnel as a clean markdown payload.                                                                    
──────                                                                                                                                                            
### Feature 2: The 10–15 Minute Audio Podcast Engine                                                                                                              
                                                                                                                                                                  
Generating a realistic 10–15 minute monologue requires careful pacing and a multi-stage production pipeline. A single audio generator cannot generate 15 minutes  
of uninterrupted speech in one pass without drifting or hallucinating voice timbre.                                                                               
                                                                                                                                                                  
#### 1. The Speech Math                                                                                                                                           
                                                                                                                                                                  
• Natural speaking rate for a podcast host is roughly 130 to 150 words per minute.                                                                                
• A 10-minute talk requires approximately 1,400 to 1,500 words.                                                                                                   
• A 15-minute talk requires approximately 2,000 to 2,250 words.                                                                                                   
                                                                                                                                                                  
#### 2. Stage 1: Narrative Script Generation (On TPU)                                                                                                             
                                                                                                                                                                  
• The LLM is directed to act as a seasoned podcast host (warm, articulate, insightful, speaking in a conversational, explanatory cadence).                        
• The model ingests the Docling sources (plus any supplementary web search results) and expands them into a complete narrative arc: an introduction hook, thematic
breakdowns, real-world analogies, rhetorical questions, and an analytical conclusion.                                                                             
• The system instructs the LLM to output clean, spoken-word English or Hindi text—omitting visual markdown symbols like asterisks, bullet points, or parenthetical
cues that would confuse a voice synthesizer.                                                                                                                      
                                                                                                                                                                  
#### 3. Stage 2: Voice Synthesis & The Persona (On Host CPU)                                                                                                      
                                                                                                                                                                  
• Voice Profile: The system uses a mature, deep, conversational neural voice profile modeled after a 40-something American male (authoritative, warm, and natural).
• Hindi Compatibility:                                                                                                                                            
    • The TTS pipeline uses multilingual neural voice models.                                                                                                     
    • When a Hindi request is triggered, the model switches dynamically to a native Hindi male voice persona while retaining the same warm, mature conversational 
    pacing.                                                                                                                                                       
• The Chunking & Stitching Strategy:                                                                                                                              
    • Generating 2,000 words in one audio shot can cause memory overflow or audio drift.                                                                          
    • The server splits the generated script into natural paragraph-level chunks (1 to 2 sentences each, split at punctuation marks).                             
    • Kaggle's 96-core CPU synthesizes these chunks in parallel threads.                                                                                          
    • The resulting audio clips are seamlessly concatenated into a single master MP3 audio file.                                                                  
                                                                                                                                                                  
──────                                                                                                                                                            
### The Web Search Engine ("Cherry on Top")                                                                                                                       
                                                                                                                                                                  
Web search operates as an automatic routing layer across both features:                                                                                           
                                                                                                                                                                  
1. Search Trigger: Activated either explicitly via a request toggle from your app or automatically when the query involves time-sensitive phrases, comparisons, or
queries outside the provided Docling text.
2. Context Fusion: The top search snippets and links are cleaned, formatted into brief bullet points, and injected into the prompt under a separate context header.
3. Conflict Resolution: The system prompt instructs the model to treat the Docling sources as primary ground truth, while using web results to fill temporal gaps,
update outdated metrics, or provide missing external context.
──────
### Endpoint Design & Interaction Model

Your server exposes two dedicated POST endpoints through the ngrok tunnel:

#### 1. /chat (Synchronous)

• Inputs: Docling markdown string, user prompt, and a flag indicating whether web search is allowed.
• Processing Time: 2 to 5 seconds.
• Output: Formatted markdown response, a list of web search queries executed (if any), and citation references.

#### 2. /podcast (Task / File Return)

• Inputs: Docling markdown string, topic/focus prompt, duration target (10 or 15 mins), and language selection (English or Hindi).
• Processing Flow:
    • Step A: Generate the 1,500–2,200 word spoken-word script on the TPU.
    • Step B: Stream the script through the parallel audio synthesis engine on the CPU.
    • Step C: Stitch audio segments and export the final MP3.
• Processing Time: Roughly 30 to 60 seconds total.
• Output: The complete audio file (downloadable directly or delivered as an audio stream) accompanied by the generated text transcript.
──────
### Best Practices for Running Smoothly on Kaggle

• Asynchronous Jobs for Audio: Because generating 15 minutes of speech takes around 45–60 seconds, your external app should handle the podcast request with an    
appropriate client timeout or a background job polling mechanism.
• Text Cleanliness: Docling does a great job structuring text, but ensure any massive base64 image strings embedded within the Docling output are stripped before 
hitting the TPU text prompt to keep token latency minimal.
• Kaggle Execution: Run the notebook using Kaggle's background run feature so that the ngrok tunnel remains active even if you close your local browser window.  