"""Independent Edge TTS authorization issued by the VideoFlow license server."""
import platform
import requests
import local_logger
from license_client import LICENSE_SERVER_URL, device_id


def verify_key(key: str, timeout: int = 12) -> tuple[bool, str]:
    key = str(key or '').strip()
    if not key:
        return False, '请填写 Edge TTS 使用密钥'
    try:
        response = local_logger.request(requests.post, LICENSE_SERVER_URL + '/api/edge-tts/verify',
            json={'license_key': key, 'device_id': device_id(), 'device_name': platform.node(), 'app_version': '1.0'}, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get('valid'), bool):
            return False, 'Edge TTS 授权服务器返回格式错误'
        return payload['valid'], str(payload.get('message') or 'Edge TTS 授权验证失败')
    except (requests.RequestException, ValueError, TypeError):
        return False, 'Edge TTS 授权验证失败，请检查密钥、网络和服务器部署'


def require_key(key: str):
    valid, message = verify_key(key)
    if not valid:
        raise PermissionError(message)
