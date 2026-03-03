# Product Requirements Document (PRD): OpenClaw Replica 

## 1. Product Overview
The product is a personalized, 24/7 AI employee built inside **Claude Code**, designed as a secure and cost-effective replica of "Clawbot" or "OpenClaw". It acts as an always-on assistant integrated directly into the user's workflow, building upon previous community frameworks like "Jarvis Jr". 

## 2. Value Proposition & Cost Structure
*   **Cost Efficiency**: Instead of relying on expensive API calls that can cost between $500 to $5,000 a month, this system operates on a fixed cost. It leverages the Claude Pro/Max plan for ~$200/month, with telephony and voice services adding $11-$20/month, resulting in an estimated fixed total of ~$250/month.
*   **Security & Control**: Mitigates the critical security flaws and prompt injection vulnerabilities of the public Clawbot by keeping the infrastructure localized, secure, and personalized rather than exposing it to the internet via public MCP servers.

## 3. Core Features & Requirements

### 3.1. Omnichannel Telegram Interface
*   **Multi-Modal Inputs/Outputs**: The user can communicate with the AI via text messages, voice messages, images, and files. The AI can respond with text, files, images, and voice replies. 
*   **Future Video Integration**: Planned capability to analyze video messages sent through Telegram.

### 3.2. Bi-Directional Calling & Post-Call Actions
*   **Two-Way Calls**: The user can call the AI at any time, and the AI can proactively call the user. 
*   **Post-Call Processing**: After a call ends, the system captures the context, transcribes the conversation, logs who said what, and sends a summary to Telegram.
*   **Action Execution**: The AI can execute complex tasks requested during the call (e.g., researching a topic, reading/saving PDFs to Google Drive, evaluating content, writing a script) and then automatically call the user back to report the results.

### 3.3. Proactive Check-Ins
*   **Scheduled Monitoring**: The AI operates on an "always-on architecture" and checks the user's email, calendar, projects, tasks, and Notion partnerships every 30 minutes.
*   **Anti-Spam Framework**: To prevent noisy or repetitive notifications, the AI uses an evaluation framework to decide whether to silently skip, send a text, or call the user based on the urgency/relevance of the findings (e.g., distinguishing between a known partner and a new sponsorship inquiry).

### 3.4. Semantic Memory & Goal Tracking
*   **Persistent Context**: The AI features persistent semantic memory, allowing it to remember past conversations, facts, and timelines (e.g., what was discussed yesterday vs. a month ago).
*   **Goal Detection**: During conversations, the AI actively detects and logs user goals, facts, and items the user wants to remember. 
*   **Self-Awareness**: The AI keeps a log of what it said during previous check-ins to avoid repeating itself.

### 3.5. System Access & Tool Integrations (Skills/MCP)
*   The AI has full system access to control the user's local computer, execute commands, and use built-in or custom skills/MCP servers.
*   **Specific Integrations**: Gmail, Google Calendar, Google Drive, Notion, and specialized skills like creating presentation slides from project documentation.

### 3.6. Observability & Constraints
*   **Observability Dashboard**: A live system observatory that tracks if the Telegram bot is online, database connection status, system uptime, goal tracking, and a live feed of the AI's current actions (e.g., "user prompt submitted gmail business").
*   **Time Limits**: The AI is restricted to a 2-hour limit for autonomous task execution, after which it must report back to the user to prevent it from going "rogue" indefinitely.

---

# Technical Architecture Document

## 1. System Architecture Overview
The system utilizes an always-on "headless" architecture, currently hosted on a local laptop (with the option to deploy to a secure VPS). It binds an advanced Large Language Model to a messaging interface, telephony routing, and a vector database for semantic memory.

## 2. Technology Stack
*   **Core AI Engine**: **Claude Code** (leveraging Anthropic's "Opus 4.5" model via a fixed-rate subscription).
*   **Messaging Middleware**: 
    *   **Telegram API**: Serves as the primary user interface.
    *   **Bun**: JavaScript runtime used for the relay.
    *   **grammY**: Framework used for building the Telegram bot.
*   **Telephony & Voice**:
    *   **Twilio**: Provides the phone number and handles routing for bi-directional phone calls.
    *   **ElevenLabs**: Powers the voice agent and conversational AI interactions.
*   **Database & Memory**: **Supabase** (currently on the free plan) is used to store semantic memory, conversational transcripts, and logs.

## 3. Data Flow & Subsystems

### 3.1. Messaging & Action Flow
1. User sends a message/command via Telegram.
2. The request passes through the **Bun relay** and **grammY** to reach the headless **Claude Code** instance.
3. Claude Code processes the request using the **Context API**, fetching past Telegram messages, semantic memory from **Supabase**, and previous system logs.
4. Claude interacts with local tools/MCP servers (e.g., reading a PDF, checking Gmail).
5. Claude routes the synthesized response back through the relay to Telegram.

### 3.2. Memory Ingestion System
1. After a call or chat interaction concludes, the system extracts timestamps, keywords, and dialogue.
2. The transcript is segmented by speaker ("what bot said", "what user said") and saved into **Supabase**.
3. The system parses the interaction to classify items into "goals", "facts", or "things to remember" before committing them to the database.

### 3.3. Proactive Evaluation Loop
1. A cron-job or scheduled loop triggers every 30 minutes.
2. Claude Code executes read commands on connected integrations (Gmail, Calendar, Notion).
3. The AI cross-references the new data with its internal log of previous check-ins and semantic memory.
4. It passes the findings through an evaluation skill to determine the action tier (Skip -> Send Text -> Initiate Call).

## 4. Security Infrastructure
*   **Telephony Verification**: To prevent malicious actors from calling the Twilio number, accessing the user's tools, or manipulating the AI's memory, the system enforces **Caller ID checking**. It will only process commands if the incoming call matches the owner's authorized phone number.
*   **Execution Timeouts**: Autonomous loops are hard-capped at 2 hours. The system automatically halts and awaits user confirmation/reporting before continuing.
*   **Infrastructure Isolation**: By using custom integrations and local Claude Code environments rather than public internet MCP servers, the system reduces the surface area for prompt injections.

## 5. Future Technical Roadmap
*   **Multi-Agent Ecosystem**: Expanding the architecture to host multiple specialized agents (e.g., CFO, CEO, Critic) in different Telegram chats under a unified "founder infrastructure".
*   **Video Processing Pipeline**: Adding capabilities to parse and analyze video files natively within the Telegram interface.