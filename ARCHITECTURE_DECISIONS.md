# Architecture Decisions & Alternatives

## Overview

This project demonstrates a **hybrid architecture** that intentionally combines different AWS approaches to showcase flexibility and let you choose what works best for your use case.

## Hybrid Approach Explained

### What We Built

```
┌─────────────────────────────────────────────────────────────┐
│                    WhatsApp Message                          │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────┐
│              Lambda Orchestration Layer                      │
│  • inbound-webhook (receives webhook)                        │
│  • wa-process (main orchestrator)                            │
│  • wa-send (sends messages)                                  │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
           ┌───────────┴───────────┐
           ↓                       ↓
┌──────────────────┐    ┌──────────────────────┐
│ Direct Lambda    │    │ Bedrock Agent        │
│ Processing       │    │ Framework            │
│                  │    │                      │
│ • wa-image-      │    │ • Supervisor Agent   │
│   analyze        │    │ • ImageCreator       │
│ • wa-tts         │    │   Sub-Agent          │
│ • wa-audio-      │    │                      │
│   transcribe     │    │ Calls:               │
│                  │    │ • wa-image-generate  │
└──────────────────┘    └──────────────────────┘
```

### Why Hybrid?

**This is intentional to show that you can mix and match:**

1. **Direct Lambda Processing** (Image Analysis, TTS, Transcription)
   - ✅ Simple, straightforward
   - ✅ Full control over logic
   - ✅ Lower latency
   - ✅ Cost-effective for simple operations

2. **Bedrock Agent Framework** (Image Generation)
   - ✅ Natural language understanding
   - ✅ Complex prompt optimization
   - ✅ Multi-turn conversations
   - ✅ Agent collaboration (supervisor → sub-agent)

**Key Point:** Image generation uses agents because the user's natural language request needs to be transformed into a detailed, optimized prompt for the image model. Other features like image analysis don't need this complexity.

---

## Configuration: Environment Variables vs .env

### ⚠️ Important Clarification

**There is NO `.env` file required for deployment.**

The `env.example` file is provided as a **reference only** to document what environment variables exist. In production:

### Lambda Environment Variables

Set directly in AWS Console or via CLI:

```bash
# Example: Setting environment variables via CLI
aws lambda update-function-configuration \
  --function-name wa-process \
  --environment Variables='{
    BEDROCK_AGENT_ID=YOUR_AGENT_ID,
    BEDROCK_AGENT_ALIAS_ID=YOUR_ALIAS_ID,
    BEDROCK_REGION=us-east-1,
    MEDIA_BUCKET=my-media-bucket,
    WA_SEND_FUNCTION=wa-send
  }'
```

**Each Lambda has its own environment variables:**

- `inbound-webhook`: Webhook verification, bucket names
- `wa-process`: Agent IDs, region, function names
- `wa-image-generate`: Model IDs, bucket names, wa-send function
- `wa-send`: (gets secrets from Secrets Manager at runtime)
- etc.

### Secrets Manager (Only for Long-Term Tokens)

**Only WhatsApp credentials are stored in Secrets Manager:**

```json
{
  "WHATSAPP_PHONE_NUMBER_ID": "123456789",
  "WHATSAPP_ACCESS_TOKEN": "EAAxxxxx...",
  "WHATSAPP_VERIFY_TOKEN": "your_verify_token"
}
```

**Why?** These are:
- Long-term credentials
- Need rotation
- Used by multiple functions
- Security-sensitive

**Lambda functions fetch these at runtime:**

```python
# In Lambda code
secrets = secretsmanager.get_secret_value(SecretId="whatsapp-credentials")
secret_data = json.loads(secrets["SecretString"])
token = secret_data["WHATSAPP_ACCESS_TOKEN"]
```

---

## Alternative Architectures

This project is **one way** to build a WhatsApp bot on AWS. Here are alternatives:

### 1. Pure Lambda Orchestration (No Agents)

**What it means:**
- Remove Bedrock Agents entirely
- All logic in Lambda functions
- `wa-process` directly calls image generation Lambda

**Pros:**
- ✅ Simpler architecture
- ✅ Lower cost (no agent invocations)
- ✅ Faster (no agent overhead)
- ✅ More predictable

**Cons:**
- ❌ You write all the prompt engineering logic
- ❌ No natural language understanding
- ❌ Harder to maintain complex conversational flows

**When to use:** Simple bots with deterministic logic

### 2. Pure Agent Architecture (Everything via Agents)

**What it means:**
- Make image analysis, TTS, transcription into agent action groups
- Everything goes through Bedrock Agents
- No direct Lambda-to-Lambda calls

**Pros:**
- ✅ Unified conversational interface
- ✅ Agent handles all context
- ✅ Multi-turn conversations for everything
- ✅ Consistent architecture

**Cons:**
- ❌ Higher cost (agent invocations for simple tasks)
- ❌ Higher latency
- ❌ Overkill for simple operations

**When to use:** Complex conversational AI where everything needs context

### 3. Amazon Bedrock AgentCore (Not Used Here)

**What it is:** A newer AWS platform with modular services (Runtime, Gateway, Memory, Identity, Observability) for building agents with any framework.

**How it's different:**
- Works with any framework (LangGraph, CrewAI, LlamaIndex, etc.)
- Modular services you can use independently or together
- More infrastructure services (8-hour runtimes, session isolation, etc.)
- Framework-agnostic approach

**Pros:**
- ✅ Framework flexibility (bring your own)
- ✅ Advanced features (long runtimes, browser tool, code interpreter)
- ✅ Comprehensive observability built-in

**Cons:**
- ❌ Newer platform (less documentation/examples)
- ❌ Different pricing model
- ❌ Requires more architectural decisions

**When to use:** Need advanced agent infrastructure with custom frameworks

📚 Learn more: [AWS Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/)

### 4. Agent Framework (LangChain, CrewAI, etc.)

**What it means:**
- Use open-source agent frameworks
- Host your own agent logic in Lambda
- Bedrock just provides the models

**Pros:**
- ✅ Full control over agent behavior
- ✅ Framework ecosystem and tools
- ✅ Can run locally for testing
- ✅ Not locked into AWS agents

**Cons:**
- ❌ More dependencies to manage
- ❌ You handle state and memory
- ❌ More code complexity

**When to use:** Need portability or specific framework features

### 5. Step Functions Orchestration

**What it means:**
- Use AWS Step Functions for workflow
- Lambda functions as steps
- Visual workflow designer

**Pros:**
- ✅ Visual workflow
- ✅ Built-in retry and error handling
- ✅ Complex conditional logic
- ✅ Great for long-running processes

**Cons:**
- ❌ More AWS services to manage
- ❌ Additional cost
- ❌ Overkill for simple synchronous flows

**When to use:** Complex workflows with branching, retries, human approval

---

## Why This Hybrid Approach?

### Educational Value

This project shows **both** approaches so you can:

1. **See the difference** between direct Lambda and Agent frameworks
2. **Choose what works** for your specific use case
3. **Mix and match** as needed

### Real-World Practicality

- **Simple tasks** (image analysis) don't need agent overhead
- **Complex tasks** (image generation with prompt optimization) benefit from agents
- **Cost-effective** - only pay for agents where they add value

### Migration Path

This architecture makes it easy to:

1. **Start simple** with direct Lambda processing
2. **Add agents later** for specific features
3. **Convert** Lambda functions to agent actions gradually

---

## Decision Matrix

| Feature | Current | Pure Lambda | Pure Agent | Best For |
|---------|---------|-------------|------------|----------|
| **Image Analysis** | Lambda | ✅ | ⚠️ Overkill | Lambda - simple, fast, cheap |
| **Image Generation** | Agent | ⚠️ Basic | ✅ | Agent - needs prompt engineering |
| **Text-to-Speech** | Lambda | ✅ | ⚠️ Overkill | Lambda - deterministic operation |
| **Transcription** | Lambda | ✅ | ⚠️ Overkill | Lambda - AWS service call |
| **Conversation** | Agent | ⚠️ Limited | ✅ | Agent - natural language |

---

## Your Architecture Choices

### Option 1: Keep Hybrid (Current)
✅ **Use this if:** You want balance between simplicity and capability

### Option 2: Go Full Lambda
📝 **Remove:** Bedrock Agents, supervisor, sub-agent  
📝 **Change:** `wa-process` directly calls `wa-image-generate`  
✅ **Use this if:** You want simplicity and cost optimization

### Option 3: Go Full Agent
📝 **Add:** Action groups for image analysis, TTS, transcription  
📝 **Remove:** Direct Lambda invocations from `wa-process`  
✅ **Use this if:** You want unified conversational AI

### Option 4: Use Agent Framework
📝 **Add:** LangChain/CrewAI in Lambda  
📝 **Remove:** Bedrock Agents (keep models)  
✅ **Use this if:** You want portability and framework features

---

## Implementation Notes

### Current Setup Flexibility

The current code is designed to be **easily modified**:

1. **Remove agents?** 
   - Update `wa-process` to call `wa-image-generate` directly
   - Remove agent invocation code
   - Keep everything else

2. **Add more agent features?**
   - Create action groups for other Lambdas
   - Update supervisor instructions
   - Add to agent action groups

3. **Switch to agent framework?**
   - Replace agent invocation with framework code
   - Keep Lambda functions as tools
   - Update orchestration logic

---

## Conclusion

**Key Takeaway:** This hybrid architecture is a **starting point** and **learning resource**. 

Choose what fits your needs:
- ✅ **Simple bot?** Pure Lambda
- ✅ **Conversational AI?** Pure Agent
- ✅ **Balanced?** Hybrid (current)
- ✅ **Portable?** Agent Framework
- ✅ **Complex workflows?** Step Functions

**The beauty of AWS:** You can start one way and evolve as needs change.

