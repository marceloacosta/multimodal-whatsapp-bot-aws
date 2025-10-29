import os, json, urllib.request, boto3

GRAPH_BASE = "https://graph.facebook.com/v22.0"
PHONE_NUMBER_ID = os.environ["PHONE_NUMBER_ID"]           # WhatsApp phone number ID
SECRET_NAME = os.environ["WA_TOKEN_SECRET_NAME"]          # Secret JSON: {"token":"EAAG..."}

secrets = boto3.client("secretsmanager")
_token_cache = None

def token():
    global _token_cache
    if _token_cache:
        return _token_cache
    s = secrets.get_secret_value(SecretId=SECRET_NAME)["SecretString"]
    _token_cache = json.loads(s)["token"]
    return _token_cache

def _post(url: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token()}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

def send_text(to_e164: str, text: str):
    url = f"{GRAPH_BASE}/{PHONE_NUMBER_ID}/messages"
    body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_e164,                               # e.g., "1234567890" (without '+')
        "type": "text",
        "text": {"preview_url": False, "body": text[:4096]},
    }
    return _post(url, body)

def send_audio_link(to_e164: str, https_url: str):
    """
    Envía un audio a WhatsApp usando un link HTTPS directo (ej. presigned S3 URL).
    """
    url = f"{GRAPH_BASE}/{PHONE_NUMBER_ID}/messages"
    body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_e164,
        "type": "audio",
        "audio": {"link": https_url}
    }
    return _post(url, body)

def send_image_link(to_e164: str, https_url: str, caption: str = None):
    """
    Envía una imagen a WhatsApp usando un link HTTPS directo (ej. presigned S3 URL).
    """
    url = f"{GRAPH_BASE}/{PHONE_NUMBER_ID}/messages"
    body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_e164,
        "type": "image",
        "image": {"link": https_url}
    }
    if caption:
        body["image"]["caption"] = caption[:1024]  # WhatsApp caption limit
    return _post(url, body)

def lambda_handler(event, context):
    """
    Payloads esperados:
      # Texto
      {"to": "5693...", "text": "hola"}

      # Audio (URL presignada)
      {"to": "5693...", "audio_url": "https://.../tts/...mp3"}

      # Imagen (URL presignada)
      {"to": "5693...", "image_url": "https://.../generated-images/...png", "caption": "optional"}

    Prioridad: image > audio > text
    """
    to = event.get("to")
    text = (event.get("text") or "").strip()
    audio_url = (event.get("audio_url") or "").strip()
    image_url = (event.get("image_url") or "").strip()
    caption = (event.get("caption") or "").strip()

    if not to:
        return {"statusCode": 400, "body": "missing 'to'"}

    try:
        if image_url:
            resp = send_image_link(to, image_url, caption if caption else None)
        elif audio_url:
            resp = send_audio_link(to, audio_url)
        elif text:
            resp = send_text(to, text)
        else:
            return {"statusCode": 400, "body": "nothing to send"}
    except Exception as e:
        # Devuelve error simplificado para CloudWatch
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

    return {"statusCode": 200, "body": json.dumps(resp)}
