#!/usr/bin/env python3
"""
WhatsApp Multimodal Bot Architecture Diagram
Generates a complete architecture diagram of the AWS solution
"""

from diagrams import Diagram, Cluster, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.network import APIGateway
from diagrams.aws.storage import S3
from diagrams.aws.security import SecretsManager
from diagrams.aws.ml import Bedrock
from diagrams.onprem.client import Users

graph_attr = {
    "fontsize": "14",
    "bgcolor": "white",
    "rankdir": "LR",
    "ranksep": "1.5",
    "nodesep": "0.8",
}

with Diagram("WhatsApp Multimodal Bot - AWS Architecture", 
             direction="LR", 
             filename="whatsapp_bot_architecture",
             graph_attr=graph_attr,
             show=False):
    
    # Stage 1: Entry
    user = Users("User\n(WhatsApp)")
    api = APIGateway("API\nGateway")
    
    # Stage 2: Webhook
    webhook = Lambda("inbound-\nwebhook")
    
    # Stage 3: Orchestrator
    orchestrator = Lambda("wa-process\n(Orchestrator)")
    
    # Stage 4: Processing (parallel)
    with Cluster("Processing Lambdas"):
        image_analyze = Lambda("Image\nAnalyze")
        image_generate = Lambda("Image\nGenerate")
        tts = Lambda("TTS")
        transcribe_start = Lambda("Audio\nTranscribe")
        transcribe_finish = Lambda("Transcribe\nFinish")
    
    # Stage 5: AI Services
    with Cluster("Bedrock"):
        supervisor = Bedrock("Supervisor\nAgent")
        sub_agent = Bedrock("ImageCreator\nSub-Agent")
        models = Bedrock("Foundation\nModels")
    
    # Stage 6: Storage & Output
    s3 = S3("S3\nStorage")
    sender = Lambda("wa-send")
    secrets = SecretsManager("Secrets")
    
    # Main flow (left to right)
    user >> api >> webhook >> orchestrator
    
    # Orchestrator branches
    orchestrator >> supervisor
    orchestrator >> image_analyze >> models
    orchestrator >> tts
    orchestrator >> transcribe_start
    
    # Agent flow
    supervisor >> sub_agent >> image_generate >> models
    
    # Storage interactions
    image_generate >> s3
    tts >> s3
    
    # Async transcription flow
    transcribe_start >> Edge(label="S3 event") >> s3 >> transcribe_finish >> orchestrator
    
    # Send back to user
    orchestrator >> sender >> api >> user
    image_generate >> sender
    
    # Config (dotted lines)
    secrets >> Edge(style="dotted", color="gray") >> sender

print("✅ Architecture diagram generated: whatsapp_bot_architecture.png")
