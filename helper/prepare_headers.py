def prepare_headers(headers: dict = None, bearer_token: str = None) -> dict:
    final_headers = headers.copy() if headers else {}
    if bearer_token:
        final_headers["Authorization"] = f"Bearer {bearer_token}"
    return final_headers