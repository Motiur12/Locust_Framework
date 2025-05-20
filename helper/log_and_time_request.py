import logging
import json
from requests import Response

def log_and_time_request(
    method_name: str,
    endpoint: str,
    response: Response,
    duration: float,
    console_logging: bool = False
) -> None:
    log_data = {
        "method": method_name.upper(),
        "url": response.url,
        "status_code": response.status_code,
        "duration_ms": round(duration * 1000, 2),
        "response_size_bytes": len(response.content),
    }

    try:
        log_data["response_snippet"] = response.text[:200]
    except Exception as e:
        log_data["response_snippet"] = f"Error getting response text: {e}"

    message = f"[{method_name.upper()}] {endpoint} - {response.status_code} in {log_data['duration_ms']}ms"

    if console_logging:
        logging.info(message)

    # logging.info(json.dumps(log_data, indent=2))
