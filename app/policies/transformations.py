from typing import Any


def rewrite_path(raw_path: str, strip_prefix: str | None, path_prefix: str | None) -> str:
    normalized = "/" + raw_path.lstrip("/") if raw_path else ""

    if strip_prefix:
        clean_strip = "/" + strip_prefix.strip("/")
        if normalized == clean_strip:
            normalized = ""
        elif normalized.startswith(clean_strip + "/"):
            normalized = normalized[len(clean_strip):]

    if path_prefix:
        clean_prefix = path_prefix.strip("/")
        if clean_prefix:
            suffix = normalized.lstrip("/")
            normalized = f"/{clean_prefix}/{suffix}" if suffix else f"/{clean_prefix}"

    return normalized.lstrip("/")

def transform_headers(
        headers: dict[str, str],
        headers_remove: list[str] | None,
        headers_add: dict[str, str] | None,
        jwt_payload: dict[str, Any] | None,
) -> dict[str, str]:
    remove_set = {h.lower() for h in (headers_remove or [])}
    result = {k: v for k, v in headers.items() if k.lower() not in remove_set}
    if headers_add:
        for k, v in headers_add.items():
            result[k] = str(v)
    if jwt_payload and "sub" in jwt_payload:
        result["X-User-Id"] = jwt_payload["sub"]
    return result