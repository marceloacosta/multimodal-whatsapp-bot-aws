#!/usr/bin/env python3
"""
WhatsApp Multimodal Bot Architecture Diagram
Generates a complete architecture diagram of the AWS solution
"""

from diagrams import Diagram, Cluster, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.network import APIGateway
from diagrams.aws.storage import S3
from diagrams.aws.security import SecretsManager, IAM
from diagrams.aws.ml import Bedrock
from diagrams.onprem.client import Users, Client

graph_attr = {
    "fontsize": "16",
    "bgcolor": "white",
    "pad": "0.5",
}

with Diagram("WhatsApp Multimodal Bot - AWS Architecture", 
             direction="LR", 
             filename="whatsapp_bot_architecture",
             graph_attr=graph_attr,
             show=False):
    
    # External users
    user = Users("User")
    whatsapp = Client("WhatsApp\nBusiness API")
    
    # Entry point
    api_gateway = APIGateway("API Gateway\n/webhook")
    
    # Secrets & Config
    with Cluster("Configuration"):
        secrets = SecretsManager("Secrets Manager\n(WhatsApp tokens)")
        iam = IAM("IAM Roles\n& Policies")
    
    # Main Lambda functions
    with Cluster("Lambda Functions"):
        inbound = Lambda("inbound-webhook\n(Webhook handler)")
        process = Lambda("wa-process\n(Orchestrator)")
        send = Lambda("wa-send\n(Send messages)")
        
        with Cluster("Media Processing"):
            tts = Lambda("wa-tts\n(Text-to-Speech)")
            audio_transcribe = Lambda("wa-audio-transcribe\n(Speech-to-Text)")
            transcribe_finish = Lambda("wa-transcribe-finish\n(Transcription handler)")
            image_analyze = Lambda("wa-image-analyze\n(Image Analysis)")
            image_generate = Lambda("wa-image-generate\n(Image Generation)")
    
    # AWS AI Services
    with Cluster("AWS Bedrock"):
        supervisor_agent = Bedrock("Supervisor Agent\n(Claude 3.5 Sonnet)")
        image_creator_agent = Bedrock("ImageCreator\nSub-Agent")
        
        with Cluster("Foundation Models"):
            claude_vision = Bedrock("Claude 3.5 Sonnet v2\n(Vision)")
            claude_haiku = Bedrock("Claude 3.5 Haiku\n(Captions)")
            titan_image = Bedrock("Titan Image\nGenerator v2")
    
    # Storage
    with Cluster("Storage"):
        media_bucket = S3("S3 Bucket\n(Media files)")
        generated_images = S3("S3 Bucket\n(Generated images)")
    
    # Flow: User interaction
    user >> Edge(label="WhatsApp\nmessage") >> whatsapp
    whatsapp >> Edge(label="Webhook\nPOST") >> api_gateway
    api_gateway >> Edge(label="Invoke") >> inbound
    
    # Flow: Inbound processing
    inbound >> Edge(label="Classify &\nRoute") >> process
    inbound >> Edge(label="Upload\nmedia") >> media_bucket
    
    # Flow: Secrets
    inbound >> Edge(style="dotted", color="gray") >> secrets
    send >> Edge(style="dotted", color="gray") >> secrets
    
    # Flow: Main orchestration
    process >> Edge(label="Text/Image\nrequests") >> supervisor_agent
    supervisor_agent >> Edge(label="Delegate\nimage gen") >> image_creator_agent
    
    # Flow: Image analysis
    process >> Edge(label="Analyze\nimage") >> image_analyze
    image_analyze >> Edge(label="Get image") >> media_bucket
    image_analyze >> Edge(label="Vision\nAPI") >> claude_vision
    
    # Flow: Image generation
    image_creator_agent >> Edge(label="Generate\nimage") >> image_generate
    image_generate >> Edge(label="Generate\nimage") >> titan_image
    image_generate >> Edge(label="Generate\ncaption") >> claude_haiku
    image_generate >> Edge(label="Save\nimage") >> generated_images
    image_generate >> Edge(label="Send to\nuser") >> send
    
    # Flow: Audio processing
    process >> Edge(label="TTS\nrequest") >> tts
    tts >> Edge(label="Audio") >> media_bucket
    
    process >> Edge(label="STT\nrequest") >> audio_transcribe
    audio_transcribe >> Edge(label="Get audio") >> media_bucket
    audio_transcribe >> Edge(label="Callback") >> transcribe_finish
    
    # Flow: Sending messages
    process >> Edge(label="Send text/\naudio/image") >> send
    send >> Edge(label="WhatsApp\nAPI") >> whatsapp
    whatsapp >> Edge(label="Deliver") >> user
    
    # IAM relationships
    iam >> Edge(style="dotted", color="gray", label="Permissions") >> [
        process, send, image_generate, image_analyze, tts, audio_transcribe
    ]

print("✅ Architecture diagram generated: whatsapp_bot_architecture.png")

